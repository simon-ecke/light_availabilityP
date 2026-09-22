"""
ldbv_download.py
================

LDBV data acquisition for DGM1 (WCS 2.0.1) and DOM20 (Metalink tile download).

DGM1 (1m Digital Ground Model):
    Downloaded via WCS 2.0.1 from geoservices.bayern.de.
    Requires LDBV credentials (HTTPBasicAuth).

DOM20 (20cm Digital Surface Model):
    Not available via WCS. Downloaded as 1km x 1km tiles from bayernwolke.de
    (open data, no authentication needed).
    Tiles follow a UTM32 / EPSG:25832 kilometer grid naming convention.

Adapted from:
    - C:\\Users\\lwfeckesim\\04_peakfinder\\peakfinder\\modules\\ndsm_tools.py (WCS)
    - C:\\Users\\lwfeckesim\\14_dtm_loader\\modules\\metalink.py (tile download)
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import getpass
import random
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any

import numpy as np
import requests
from requests.auth import HTTPBasicAuth

try:
    import aiohttp
    import aiofiles
    from tqdm.asyncio import tqdm as atqdm
    HAS_ASYNC = True
except ImportError:
    HAS_ASYNC = False

from tqdm import tqdm


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

# DGM1 WCS endpoint (requires LDBV credentials)
WCS_DGM_URL = "https://geoservices.bayern.de/pro/wcs/dgm/v1/wcs_inspire_dgm1?"
COVERAGE_DGM = "EL.ElevationGridCoverage"

# DOM20 tile download (open data, no auth required)
DOM20_MIRROR_URLS = [
    "https://download1.bayernwolke.de/a/dom20/DOM/",
    "https://download2.bayernwolke.de/a/dom20/DOM/"
]

# DOM20 tile grid: 1km x 1km in EPSG:25832
DOM20_TILE_SIZE_M = 1000
DOM20_PIXEL_SIZE_M = 0.2  # 20cm native resolution


# ═══════════════════════════════════════════════════════════════════════════════
# CREDENTIALS
# ═══════════════════════════════════════════════════════════════════════════════

def get_credentials(user: Optional[str] = None,
                   password: Optional[str] = None,
                   allow_prompt: bool = True) -> Tuple[str, str]:
    """
    Get LDBV credentials from arguments, environment, or interactive prompt.

    Parameters
    ----------
    user : str, optional
        Username (if None, checks LDBV_USER env var)
    password : str, optional
        Password (if None, checks LDBV_PASS env var)
    allow_prompt : bool
        If True, prompt interactively if credentials missing

    Returns
    -------
    tuple
        (username, password)

    Raises
    ------
    RuntimeError
        If credentials cannot be obtained
    """
    u = user or os.environ.get("LDBV_USER")
    p = password or os.environ.get("LDBV_PASS")

    if (not u or not p) and allow_prompt:
        if not u:
            u = input("LDBV username: ")
        if not p:
            p = getpass.getpass("LDBV password: ")

    if not u or not p:
        raise RuntimeError(
            "Missing LDBV credentials. Set LDBV_USER/LDBV_PASS environment "
            "variables or provide user/password arguments."
        )

    return u, p


# ═══════════════════════════════════════════════════════════════════════════════
# DGM1 WCS DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════════════

def download_dgm_wcs(
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    out_path: str,
    user: str,
    password: str,
    pixel_m: float = 1.0,
    timeout: int = 300
) -> str:
    """
    Download DGM1 via WCS 2.0.1 for the given extent in EPSG:25832.

    Tries multiple axis label conventions (the LDBV server may accept
    different axis names depending on version/configuration):
        - (X, Y)
        - (E, N)
        - (Easting, Northing)

    Falls back to requesting without SCALESIZE if size-based request fails.

    Parameters
    ----------
    minx, miny, maxx, maxy : float
        Bounding box in EPSG:25832
    out_path : str
        Output GeoTIFF path
    user, password : str
        LDBV credentials
    pixel_m : float
        Target pixel size in meters (default 1.0 for native DGM1)
    timeout : int
        Request timeout in seconds

    Returns
    -------
    str
        Path to downloaded file

    Raises
    ------
    RuntimeError
        If download fails after all attempts
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    auth = HTTPBasicAuth(user, password)

    dx, dy = (maxx - minx), (maxy - miny)
    nx = max(1, int(round(dx / pixel_m)))
    ny = max(1, int(round(dy / pixel_m)))

    # Try multiple axis label conventions
    axis_candidates = [("X", "Y"), ("E", "N"), ("Easting", "Northing")]

    last_err = None

    # First attempt: with SCALESIZE
    for axes in axis_candidates:
        params = [
            ("SERVICE", "WCS"),
            ("REQUEST", "GetCoverage"),
            ("VERSION", "2.0.1"),
            ("COVERAGEID", COVERAGE_DGM),
            ("SUBSETTINGCRS", "EPSG:25832"),
            ("OUTPUTCRS", "EPSG:25832"),
            ("SUBSET", f"{axes[0]}({minx},{maxx})"),
            ("SUBSET", f"{axes[1]}({miny},{maxy})"),
            ("FORMAT", "image/tiff;application=geotiff"),
            ("SCALESIZE", f"{axes[0]}({nx})"),
            ("SCALESIZE", f"{axes[1]}({ny})"),
        ]

        try:
            r = requests.get(WCS_DGM_URL, params=params, auth=auth, stream=True, timeout=timeout)
            ctype = r.headers.get("content-type", "")

            if r.status_code == 200 and ("tiff" in ctype or "geotiff" in ctype):
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        if chunk:
                            f.write(chunk)
                return out_path
            else:
                last_err = (
                    f"WCS DGM axes {axes}: status={r.status_code} "
                    f"content-type={ctype} msg={r.text[:300]}"
                )
        except requests.RequestException as e:
            last_err = f"WCS DGM axes {axes}: {e}"

    # Second attempt: without SCALESIZE (let server choose native resolution)
    for axes in axis_candidates:
        params = [
            ("SERVICE", "WCS"),
            ("REQUEST", "GetCoverage"),
            ("VERSION", "2.0.1"),
            ("COVERAGEID", COVERAGE_DGM),
            ("SUBSETTINGCRS", "EPSG:25832"),
            ("OUTPUTCRS", "EPSG:25832"),
            ("SUBSET", f"{axes[0]}({minx},{maxx})"),
            ("SUBSET", f"{axes[1]}({miny},{maxy})"),
            ("FORMAT", "image/tiff;application=geotiff"),
        ]

        try:
            r = requests.get(WCS_DGM_URL, params=params, auth=auth, stream=True, timeout=timeout)
            ctype = r.headers.get("content-type", "")

            if r.status_code == 200 and ("tiff" in ctype or "geotiff" in ctype):
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        if chunk:
                            f.write(chunk)
                return out_path
            else:
                last_err = (
                    f"WCS DGM axes {axes} (no SCALESIZE): status={r.status_code} "
                    f"content-type={ctype} msg={r.text[:300]}"
                )
        except requests.RequestException as e:
            last_err = f"WCS DGM axes {axes} (no SCALESIZE): {e}"

    raise RuntimeError(f"DGM WCS download failed. Last error: {last_err}")


# ═══════════════════════════════════════════════════════════════════════════════
# DOM20 TILE GRID LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

def compute_dom20_tiles(
    minx: float,
    miny: float,
    maxx: float,
    maxy: float
) -> List[str]:
    """
    Compute DOM20 tile filenames that intersect the given bounding box.

    Tile naming convention: "{col}_{row}_20_DOM.tif"
    where:
        col = floor(Easting / 1000)  with UTM zone prefix "32"
        row = floor(Northing / 1000)

    The grid uses 1km x 1km tiles in EPSG:25832.

    Parameters
    ----------
    minx, miny, maxx, maxy : float
        Bounding box in EPSG:25832

    Returns
    -------
    list of str
        Tile filenames
    """
    # Compute kilometer grid indices
    col_min = int(math.floor(minx / DOM20_TILE_SIZE_M))
    col_max = int(math.floor(maxx / DOM20_TILE_SIZE_M))
    row_min = int(math.floor(miny / DOM20_TILE_SIZE_M))
    row_max = int(math.floor(maxy / DOM20_TILE_SIZE_M))

    # Handle edge case: if extent aligns exactly with tile boundary
    if maxx % DOM20_TILE_SIZE_M == 0:
        col_max -= 1
    if maxy % DOM20_TILE_SIZE_M == 0:
        row_max -= 1

    tiles = []
    for col in range(col_min, col_max + 1):
        for row in range(row_min, row_max + 1):
            # Tile naming uses the full easting km index (including UTM zone prefix "32")
            # e.g., easting 722000m -> col=722, tile name "32722_..."
            tile_name = f"32{col}_{row}_20_DOM.tif"
            tiles.append(tile_name)

    return tiles


def generate_dom20_meta4(
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    out_path: str
) -> str:
    """
    Generate a Metalink 4 (.meta4) file for the DOM20 tiles intersecting the extent.

    Parameters
    ----------
    minx, miny, maxx, maxy : float
        Bounding box in EPSG:25832
    out_path : str
        Output path for .meta4 file

    Returns
    -------
    str
        Path to generated .meta4 file
    """
    tiles = compute_dom20_tiles(minx, miny, maxx, maxy)

    if not tiles:
        raise ValueError(
            f"No DOM20 tiles intersect the given extent: "
            f"({minx}, {miny}) to ({maxx}, {maxy})"
        )

    # Build XML
    ns = "urn:ietf:params:xml:ns:metalink"
    root = ET.Element("metalink", xmlns=ns)

    generator = ET.SubElement(root, "generator")
    generator.text = "canopy_histogram_ldbv"

    from datetime import datetime, timezone
    published = ET.SubElement(root, "published")
    published.text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for tile_name in tiles:
        file_el = ET.SubElement(root, "file", name=tile_name)
        for mirror in DOM20_MIRROR_URLS:
            url_el = ET.SubElement(file_el, "url")
            url_el.text = mirror + tile_name

    # Write file
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)

    return out_path


# ═══════════════════════════════════════════════════════════════════════════════
# DOM20 TILE DOWNLOAD (Metalink-based)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_meta4(meta4_path: str) -> List[Dict[str, Any]]:
    """Parse meta4 file into list of {name, sha, urls} dicts."""
    ns = {"ml": "urn:ietf:params:xml:ns:metalink"}
    tree = ET.parse(meta4_path)
    items = []

    for f in tree.findall(".//ml:file", ns):
        urls = [u.text for u in f.findall(".//ml:url", ns)]
        h = f.find(".//ml:hash[@type='sha256']", ns) or f.find(".//ml:hash", ns)
        sha = h.text if h is not None else None
        items.append({"name": f.attrib["name"], "sha": sha, "urls": urls})

    return items


async def _try_download_url(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    dest: Path,
    url: str,
    sha_expected: Optional[str],
    timeout: aiohttp.ClientTimeout,
) -> None:
    """Download url to dest; verify SHA-256 if available."""
    async with sem, session.get(url, timeout=timeout) as r:
        r.raise_for_status()
        async with aiofiles.open(dest, "wb") as f:
            async for chunk in r.content.iter_chunked(1 << 16):
                await f.write(chunk)

    if sha_expected:
        sha_actual = hashlib.sha256(dest.read_bytes()).hexdigest()
        if sha_actual != sha_expected:
            dest.unlink(missing_ok=True)
            raise ValueError(f"{dest.name}: checksum mismatch")


async def _fetch_one_tile(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    item: Dict[str, Any],
    out_dir: Path,
) -> str:
    """Try every mirror until one succeeds, with exponential back-off."""
    name, sha, urls = item["name"], item["sha"], item["urls"]
    dest = out_dir / name

    # Already present and verified?
    if sha and dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() == sha:
        return name
    if not sha and dest.exists() and dest.stat().st_size > 0:
        return name

    random.shuffle(urls)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=60)

    for i, url in enumerate(urls, 1):
        try:
            await _try_download_url(session, sem, dest, url, sha, timeout)
            return name
        except (aiohttp.ClientError, asyncio.TimeoutError):
            if i == len(urls):
                raise
            timeout = aiohttp.ClientTimeout(
                total=None,
                sock_connect=timeout.sock_connect * 2,
                sock_read=timeout.sock_read * 2,
            )


async def _fetch_meta4_async(
    meta4_path: str,
    out_dir: str,
    workers: int = 8,
    proxy: Optional[str] = None,
) -> None:
    """Download all files listed in meta4 into out_dir."""
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    items = _load_meta4(meta4_path)
    sem = asyncio.Semaphore(workers)
    connector = aiohttp.TCPConnector(limit=workers, ttl_dns_cache=600)

    sess_kwargs: dict = {"connector": connector}
    if proxy:
        sess_kwargs["proxy"] = proxy

    async with aiohttp.ClientSession(**sess_kwargs) as session:
        tasks = [_fetch_one_tile(session, sem, it, out_dir_path) for it in items]
        for coro in atqdm(asyncio.as_completed(tasks), total=len(tasks), desc="DOM20 tiles"):
            await coro


def download_dom20_tiles(
    meta4_path: str,
    out_dir: str,
    workers: int = 8,
    proxy: Optional[str] = os.environ.get("HTTPS_PROXY"),
) -> None:
    """
    Download DOM20 tiles from meta4 file.
    Works in both scripts (asyncio.run) and notebooks (creates task).

    Parameters
    ----------
    meta4_path : str
        Path to .meta4 file
    out_dir : str
        Directory to save tiles
    workers : int
        Parallel download connections
    proxy : str, optional
        HTTPS proxy URL
    """
    if not HAS_ASYNC:
        raise ImportError(
            "DOM20 download requires: conda install -c conda-forge aiohttp aiofiles tqdm"
        )

    async def _runner():
        await _fetch_meta4_async(meta4_path, out_dir, workers, proxy)

    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            return asyncio.create_task(_runner())
    except RuntimeError:
        pass

    asyncio.run(_runner())


def download_dom20_sync(
    meta4_path: str,
    out_dir: str,
    proxy: Optional[str] = os.environ.get("HTTPS_PROXY"),
) -> None:
    """
    Synchronous fallback for DOM20 tile download using requests.
    Slower than async but has no aiohttp dependency.

    Parameters
    ----------
    meta4_path : str
        Path to .meta4 file
    out_dir : str
        Directory to save tiles
    proxy : str, optional
        HTTPS proxy URL
    """
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    items = _load_meta4(meta4_path)
    proxies = {"https": proxy, "http": proxy} if proxy else None

    for item in tqdm(items, desc="DOM20 tiles"):
        name = item["name"]
        dest = out_dir_path / name

        # Skip if already downloaded
        if dest.exists() and dest.stat().st_size > 0:
            continue

        # Try mirrors
        for url in item["urls"]:
            try:
                r = requests.get(url, stream=True, timeout=120, proxies=proxies)
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        if chunk:
                            f.write(chunk)
                break  # success
            except requests.RequestException:
                continue
        else:
            raise RuntimeError(f"Failed to download {name} from all mirrors")


# ═══════════════════════════════════════════════════════════════════════════════
# DOM20 TILE MERGE
# ═══════════════════════════════════════════════════════════════════════════════

def merge_dom20_tiles(tile_dir: str, out_tif: str) -> str:
    """
    Merge DOM20 tiles into a single GeoTIFF mosaic.

    Parameters
    ----------
    tile_dir : str
        Directory containing downloaded DOM20 tiles
    out_tif : str
        Output mosaic path

    Returns
    -------
    str
        Path to merged mosaic
    """
    import rasterio
    from rasterio.windows import from_bounds

    tile_dir_path = Path(tile_dir)
    out_tif_path = Path(out_tif)

    # Remove corrupt leftovers
    out_tif_path.unlink(missing_ok=True)

    src_files = list(tile_dir_path.glob("*_20_DOM.tif"))
    if not src_files:
        raise RuntimeError(f"No DOM20 tiles found in {tile_dir}")

    # Use first tile as template
    with rasterio.open(src_files[0]) as ref:
        dx = ref.transform.a
        dy = -ref.transform.e
        dtype = ref.dtypes[0]
        nodata = ref.nodata
        crs = ref.crs

    # Compute overall extent
    bounds = [rasterio.open(fp).bounds for fp in src_files]
    left = min(b.left for b in bounds)
    bottom = min(b.bottom for b in bounds)
    right = max(b.right for b in bounds)
    top = max(b.top for b in bounds)

    width = int(round((right - left) / dx))
    height = int(round((top - bottom) / dy))

    def _block(size_px: int) -> int:
        return max(16, min(512, (size_px // 16) * 16))

    meta = dict(
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype=dtype,
        nodata=nodata,
        crs=crs,
        transform=rasterio.transform.from_origin(left, top, dx, dy),
        tiled=True,
        blockxsize=_block(width),
        blockysize=_block(height),
        compress="lzw",
        BIGTIFF="IF_SAFER",
    )

    os.makedirs(os.path.dirname(out_tif) or ".", exist_ok=True)

    with rasterio.open(out_tif, "w", **meta) as dst:
        for fp in tqdm(src_files, desc="merging"):
            with rasterio.open(fp) as src:
                win = from_bounds(*src.bounds, transform=dst.transform)
                dst.write(src.read(1), window=win, indexes=1)

    return out_tif


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION: Full Download + Derive nDOM
# ═══════════════════════════════════════════════════════════════════════════════

def download_and_derive_ndom(
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
    user: str,
    password: str,
    target_resolution_m: float = 0.2,
    temp_dir: str = "temp",
    proxy: Optional[str] = os.environ.get("HTTPS_PROXY"),
    verbose: bool = True
) -> Tuple[str, str, str]:
    """
    Full pipeline: Download DOM20 tiles + DGM1 WCS, then derive nDOM.

    Steps:
    1. Generate .meta4 for DOM20 tiles intersecting the extent
    2. Download DOM20 tiles (async, no auth needed)
    3. Merge DOM20 tiles into single mosaic
    4. Download DGM1 via WCS (with auth)
    5. Align DGM1 to DOM20 grid (upsample 1m -> 0.2m)
    6. Compute nDOM = DOM - DGM_aligned

    Parameters
    ----------
    minx, miny, maxx, maxy : float
        Bounding box in EPSG:25832
    user, password : str
        LDBV credentials (for DGM1 WCS)
    target_resolution_m : float
        Target resolution for nDOM (default 0.2m = DOM native)
    temp_dir : str
        Directory for intermediate files
    proxy : str, optional
        HTTPS proxy URL
    verbose : bool
        Print progress messages

    Returns
    -------
    tuple
        (dom_mosaic_path, dgm_path, ndom_path)
    """
    from . import raster

    os.makedirs(temp_dir, exist_ok=True)

    # Define paths
    meta4_path = os.path.join(temp_dir, "dom20_tiles.meta4")
    dom_tiles_dir = os.path.join(temp_dir, "dom20_tiles")
    dom_mosaic_path = os.path.join(temp_dir, "dom20_mosaic.tif")
    dgm_path = os.path.join(temp_dir, "dgm1_downloaded.tif")
    dgm_aligned_path = os.path.join(temp_dir, "dgm1_aligned_to_dom.tif")
    ndom_path = os.path.join(temp_dir, "ndom_derived.tif")

    # Step 1: Generate meta4 for DOM20 tiles
    if verbose:
        print("[1/6] Computing DOM20 tile list...")
    tiles = compute_dom20_tiles(minx, miny, maxx, maxy)
    if verbose:
        print(f"      {len(tiles)} tile(s): {', '.join(tiles[:5])}" +
              (f" ...and {len(tiles)-5} more" if len(tiles) > 5 else ""))

    generate_dom20_meta4(minx, miny, maxx, maxy, meta4_path)

    # Step 2: Download DOM20 tiles
    if verbose:
        print("[2/6] Downloading DOM20 tiles (open data, no auth)...")

    if HAS_ASYNC:
        download_dom20_tiles(meta4_path, dom_tiles_dir, workers=8, proxy=proxy)
    else:
        download_dom20_sync(meta4_path, dom_tiles_dir, proxy=proxy)

    # Step 3: Merge DOM20 tiles
    if verbose:
        print("[3/6] Merging DOM20 tiles into mosaic...")
    merge_dom20_tiles(dom_tiles_dir, dom_mosaic_path)

    # Step 4: Download DGM1 via WCS
    if verbose:
        print("[4/6] Downloading DGM1 via WCS 2.0.1...")
    download_dgm_wcs(minx, miny, maxx, maxy, dgm_path, user, password, pixel_m=1.0)

    # Step 5: Align DGM to DOM grid
    if verbose:
        print(f"[5/6] Aligning DGM1 to DOM grid ({target_resolution_m}m)...")
    raster.align_raster_to_reference(dgm_path, dom_mosaic_path, dgm_aligned_path, resampling="bilinear")

    # Step 6: Compute nDOM
    if verbose:
        print("[6/6] Computing nDOM = DOM - DGM...")
    raster.compute_ndom(dom_mosaic_path, dgm_aligned_path, ndom_path)

    if verbose:
        print(f"      Done. nDOM saved to: {ndom_path}")

    return dom_mosaic_path, dgm_path, ndom_path
