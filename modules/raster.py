"""
raster.py
=========

Raster operations: loading, alignment validation, nDOM derivation, clipping.
"""

from typing import Tuple, Dict, Optional
import numpy as np
import rasterio as rio
from rasterio.warp import reproject, Resampling
from rasterio.mask import mask
import geopandas as gpd


def load_raster(raster_path: str) -> Tuple[np.ndarray, Dict]:
    """
    Load raster and return array with metadata.

    Parameters
    ----------
    raster_path : str
        Path to raster file

    Returns
    -------
    tuple
        (data_array, metadata_dict)
    """
    with rio.open(raster_path) as src:
        data = src.read(1)
        metadata = {
            'transform': src.transform,
            'crs': src.crs,
            'nodata': src.nodata,
            'dtype': src.dtypes[0],
            'width': src.width,
            'height': src.height,
            'bounds': src.bounds,
            'res': src.res
        }
    return data, metadata


def validate_raster_alignment(meta1: Dict, meta2: Dict,
                              res_tolerance: float = 1e-6) -> None:
    """
    Validate that two rasters are aligned for subtraction.

    Parameters
    ----------
    meta1, meta2 : dict
        Raster metadata dictionaries
    res_tolerance : float
        Tolerance for resolution comparison

    Raises
    ------
    ValueError
        If rasters are not aligned
    """
    # Check CRS
    if meta1['crs'] != meta2['crs']:
        raise ValueError(
            f"CRS mismatch: {meta1['crs']} != {meta2['crs']}"
        )

    # Check resolution
    res1, res2 = meta1['res'], meta2['res']
    if (abs(res1[0] - res2[0]) > res_tolerance or
        abs(res1[1] - res2[1]) > res_tolerance):
        raise ValueError(
            f"Resolution mismatch: {res1} != {res2}"
        )

    # Check shape
    if (meta1['width'] != meta2['width'] or
        meta1['height'] != meta2['height']):
        raise ValueError(
            f"Shape mismatch: ({meta1['height']}, {meta1['width']}) != "
            f"({meta2['height']}, {meta2['width']})"
        )


def align_raster_to_reference(
    src_path: str,
    ref_path: str,
    out_path: str,
    resampling: str = "bilinear",
    nodata: float = -9999.0
) -> str:
    """
    Reproject/resample source raster to match reference raster's grid.

    This is used to align DGM (1m) to DOM (0.2m) grid via upsampling.

    Parameters
    ----------
    src_path : str
        Source raster to resample
    ref_path : str
        Reference raster (defines target grid)
    out_path : str
        Output path for aligned raster
    resampling : str
        Resampling method ('nearest', 'bilinear', 'cubic')
    nodata : float
        Nodata value for output

    Returns
    -------
    str
        Output path
    """
    resampling_map = {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
    }
    rsp = resampling_map.get(resampling, Resampling.bilinear)

    with rio.open(ref_path) as ref, rio.open(src_path) as src:
        # Create output profile matching reference
        dst_profile = ref.profile.copy()
        dst_profile.update(
            dtype="float32",
            count=1,
            nodata=nodata,
            compress="deflate",
            predictor=3,
            zlevel=6
        )

        # Allocate output array
        data = np.full((ref.height, ref.width), nodata, dtype="float32")

        # Reproject source to reference grid
        reproject(
            source=rio.band(src, 1),
            destination=data,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=ref.transform,
            dst_crs=ref.crs,
            dst_nodata=nodata,
            resampling=rsp,
        )

        # Write output
        with rio.open(out_path, "w", **dst_profile) as dst:
            dst.write(data, 1)

    return out_path


def compute_ndom(
    dom_path: str,
    dgm_aligned_path: str,
    ndom_out_path: str,
    nodata: float = -9999.0
) -> str:
    """
    Compute normalized height model: nDOM = DOM - DGM.

    Parameters
    ----------
    dom_path : str
        DOM (Digital Surface Model) path
    dgm_aligned_path : str
        DGM (Digital Ground Model) aligned to DOM grid
    ndom_out_path : str
        Output path for nDOM
    nodata : float
        Nodata value

    Returns
    -------
    str
        Output path
    """
    with rio.open(dom_path) as dom, rio.open(dgm_aligned_path) as dgm:
        # Load arrays
        dom_arr = dom.read(1).astype("float32")
        dgm_arr = dgm.read(1).astype("float32")

        # Create mask for nodata/NaN values
        mask_arr = (
            (dom_arr == dom.nodata) |
            (dgm_arr == dgm.nodata) |
            np.isnan(dom_arr) |
            np.isnan(dgm_arr)
        )

        # Compute nDOM with nodata handling
        ndom_arr = np.where(mask_arr, nodata, dom_arr - dgm_arr)

        # Prepare output profile
        prof = dom.profile.copy()
        prof.update(
            dtype="float32",
            nodata=nodata,
            compress="deflate",
            predictor=3,
            zlevel=6
        )

        # Write output
        with rio.open(ndom_out_path, "w", **prof) as dst:
            dst.write(ndom_arr, 1)

    return ndom_out_path


def clip_raster_to_geometry(
    raster_array: np.ndarray,
    raster_meta: Dict,
    geometry_gdf: gpd.GeoDataFrame
) -> Tuple[np.ndarray, Dict]:
    """
    Clip raster to geometry extent.

    Parameters
    ----------
    raster_array : np.ndarray
        Raster data array
    raster_meta : dict
        Raster metadata
    geometry_gdf : gpd.GeoDataFrame
        Geometry to clip to

    Returns
    -------
    tuple
        (clipped_array, updated_metadata)
    """
    # Reproject geometry to raster CRS if needed
    if geometry_gdf.crs != raster_meta['crs']:
        geometry_gdf = geometry_gdf.to_crs(raster_meta['crs'])

    # Create temporary in-memory raster for masking
    with rio.MemoryFile() as memfile:
        with memfile.open(
            driver='GTiff',
            height=raster_meta['height'],
            width=raster_meta['width'],
            count=1,
            dtype=raster_array.dtype,
            crs=raster_meta['crs'],
            transform=raster_meta['transform'],
            nodata=raster_meta['nodata']
        ) as dataset:
            dataset.write(raster_array, 1)

            # Perform masking
            out_image, out_transform = mask(
                dataset,
                geometry_gdf.geometry,
                crop=True,
                all_touched=False
            )

            # Update metadata
            updated_meta = raster_meta.copy()
            updated_meta.update({
                'height': out_image.shape[1],
                'width': out_image.shape[2],
                'transform': out_transform
            })

    return out_image[0], updated_meta


def save_raster(
    array: np.ndarray,
    metadata: Dict,
    output_path: str
) -> None:
    """
    Save raster array to file with metadata.

    Parameters
    ----------
    array : np.ndarray
        Raster data
    metadata : dict
        Raster metadata
    output_path : str
        Output file path
    """
    profile = {
        'driver': 'GTiff',
        'height': metadata['height'],
        'width': metadata['width'],
        'count': 1,
        'dtype': array.dtype,
        'crs': metadata['crs'],
        'transform': metadata['transform'],
        'nodata': metadata['nodata'],
        'compress': 'deflate',
        'predictor': 3,
        'zlevel': 6
    }

    with rio.open(output_path, 'w', **profile) as dst:
        dst.write(array, 1)


def get_raster_stats(
    array: np.ndarray,
    nodata_value: Optional[float]
) -> Dict:
    """
    Compute basic raster statistics.

    Parameters
    ----------
    array : np.ndarray
        Raster data
    nodata_value : float or None
        Nodata value to exclude

    Returns
    -------
    dict
        Statistics dictionary
    """
    # Create mask for valid data
    if nodata_value is not None:
        valid_mask = (array != nodata_value) & ~np.isnan(array) & np.isfinite(array)
    else:
        valid_mask = ~np.isnan(array) & np.isfinite(array)

    valid_data = array[valid_mask]

    if len(valid_data) == 0:
        return {
            'total_cells': array.size,
            'valid_cells': 0,
            'nodata_cells': array.size,
            'min': None,
            'max': None,
            'mean': None,
            'std': None
        }

    return {
        'total_cells': array.size,
        'valid_cells': len(valid_data),
        'nodata_cells': array.size - len(valid_data),
        'min': float(valid_data.min()),
        'max': float(valid_data.max()),
        'mean': float(valid_data.mean()),
        'std': float(valid_data.std())
    }
