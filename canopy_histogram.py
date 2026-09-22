"""
canopy_histogram.py
===================

Main entry point for forestry canopy height analysis using LDBV products.

This module provides the primary function `canopy_histogram_ldbv()` for analyzing
canopy height distributions at forestry inventory locations.
"""

from typing import List, Tuple, Union, Optional, Dict
from pathlib import Path
import os

from modules import validation, geometry, raster, analysis, plotting, ldbv_download


def canopy_histogram_ldbv(
    coords: Union[List[Tuple[float, float]], Tuple[float, float]],
    radius_m: float,
    classes: List[float],
    threshold_height_m: float = 15.0,
    min_prop_above_threshold: float = 0.25,
    transect_mode: str = "buffer_line",
    input_crs: str = "EPSG:4326",
    target_resolution_m: float = 0.2,
    analysis_raster: Optional[str] = None,
    dom_raster: Optional[str] = None,
    dgm_raster: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    output_plot_path: Optional[str] = None,
    output_clipped_raster_path: Optional[str] = None,
    temp_dir: str = "temp",
    verbose: bool = True
) -> Dict:
    """
    Analyze canopy height distribution at forestry inventory location.

    This function orchestrates the complete workflow:
    1. Validate inputs
    2. Create buffered analysis geometry
    3. Download or load elevation rasters
    4. Derive normalized height model (nDOM)
    5. Clip raster to analysis area
    6. Check height threshold
    7. Compute histogram (if threshold met)
    8. Generate plot and summary

    Parameters
    ----------
    coords : list or tuple
        Either one (x, y) coordinate pair or two [(x1, y1), (x2, y2)] pairs
    radius_m : float
        Buffer radius in meters
    classes : list of float
        Height class breaks in ascending order (e.g., [0, 15, 25, 35, 50])
    threshold_height_m : float, default 15.0
        Height threshold in meters
    min_prop_above_threshold : float, default 0.25
        Minimum proportion of cells above threshold required for histogram
    transect_mode : str, default "buffer_line"
        For two coords: "buffer_line" or "midpoint_circle"
    input_crs : str, default "EPSG:4326"
        CRS of input coordinates
    target_resolution_m : float, default 0.2
        Target resolution for analysis (0.2m for DOM native, 1.0m for faster)
    analysis_raster : str, optional
        Path to pre-normalized height raster (skips download/derivation)
    dom_raster : str, optional
        Path to DOM raster (requires dgm_raster)
    dgm_raster : str, optional
        Path to DGM raster (requires dom_raster)
    user : str, optional
        LDBV username (or set LDBV_USER env var)
    password : str, optional
        LDBV password (or set LDBV_PASS env var)
    output_plot_path : str, optional
        Path to save histogram plot
    output_clipped_raster_path : str, optional
        Path to save clipped raster
    temp_dir : str, default "temp"
        Directory for temporary files
    verbose : bool, default True
        Print progress messages

    Returns
    -------
    dict
        Results dictionary with keys:
        - geometry: Buffered geometry, extent, area
        - raster: Clipped array, metadata, statistics
        - analysis: Threshold check, histogram (if computed), summary text
        - outputs: Paths to saved files
        - download_info: Information about data source

    Raises
    ------
    Various exceptions for invalid inputs or processing errors

    Examples
    --------
    Single point analysis with WCS download:

    >>> results = canopy_histogram_ldbv(
    ...     coords=[(11.5234, 48.1372)],
    ...     radius_m=50,
    ...     classes=[0, 15, 25, 35, 50],
    ...     output_plot_path="histogram.png"
    ... )

    Transect analysis with local files:

    >>> results = canopy_histogram_ldbv(
    ...     coords=[(11.5234, 48.1372), (11.5298, 48.1401)],
    ...     radius_m=25,
    ...     classes=[0, 10, 20, 30, 40],
    ...     transect_mode="buffer_line",
    ...     dom_raster="path/to/DOM.tif",
    ...     dgm_raster="path/to/DGM.tif"
    ... )
    """
    # ========================================================================
    # STEP 1: VALIDATE INPUTS
    # ========================================================================
    if verbose:
        print("\n" + "="*70)
        print("FORESTRY CANOPY HEIGHT ANALYSIS")
        print("="*70)
        print("[1/11] Validating inputs...")

    validated = validation.validate_input_parameters(
        coords=coords,
        radius_m=radius_m,
        classes=classes,
        threshold_height_m=threshold_height_m,
        min_prop_above_threshold=min_prop_above_threshold,
        transect_mode=transect_mode,
        input_crs=input_crs,
        target_resolution_m=target_resolution_m,
        analysis_raster=analysis_raster,
        dom_raster=dom_raster,
        dgm_raster=dgm_raster,
        user=user,
        password=password
    )

    coords_validated = validated['coords']
    input_crs_validated = validated['input_crs']
    raster_mode = validated['raster_mode']

    # ========================================================================
    # STEP 2: CREATE ANALYSIS GEOMETRY
    # ========================================================================
    if verbose:
        n_coords = len(coords_validated)
        coord_str = f"{n_coords} point(s)" if n_coords == 1 else f"transect ({transect_mode})"
        print(f"[2/11] Creating analysis geometry ({coord_str}, {radius_m}m buffer)...")

    buffer_gdf = geometry.create_analysis_geometry(
        coords=coords_validated,
        radius_m=radius_m,
        transect_mode=transect_mode,
        input_crs=input_crs_validated
    )

    area_m2 = buffer_gdf.area[0]
    area_ha = area_m2 / 10000

    if verbose:
        print(f"       Analysis area: {area_ha:.3f} ha ({area_m2:.1f} m²)")
        print(f"       CRS: {buffer_gdf.crs}")

    # ========================================================================
    # STEP 3: COMPUTE EXTENT FOR DOWNLOAD
    # ========================================================================
    if verbose:
        print("[3/11] Computing extent...")

    extent_25832 = geometry.compute_extent_25832(buffer_gdf)
    extent_4326 = geometry.compute_geographic_extent(buffer_gdf)

    if verbose:
        print(f"       EPSG:25832: {extent_25832}")
        print(f"       EPSG:4326: ({extent_4326['xmin']:.6f}, {extent_4326['ymin']:.6f}) to "
              f"({extent_4326['xmax']:.6f}, {extent_4326['ymax']:.6f})")

    # ========================================================================
    # STEP 4-5: LOAD OR DOWNLOAD RASTERS, DERIVE nDOM
    # ========================================================================
    ndom_array = None
    ndom_meta = None
    download_info = {'mode': raster_mode, 'files': {}}

    if raster_mode == "analysis_raster":
        # Use pre-normalized raster directly
        if verbose:
            print("[4/11] Loading pre-normalized raster...")
        ndom_array, ndom_meta = raster.load_raster(analysis_raster)
        download_info['files']['ndom'] = analysis_raster

        if verbose:
            print(f"[5/11] Skipping nDOM derivation (already normalized)")

    elif raster_mode == "dom_dgm_files":
        # Load DOM and DGM from disk
        if verbose:
            print("[4/11] Loading DOM and DGM from disk...")

        dom_array, dom_meta = raster.load_raster(dom_raster)
        dgm_array, dgm_meta = raster.load_raster(dgm_raster)

        download_info['files']['dom'] = dom_raster
        download_info['files']['dgm'] = dgm_raster

        if verbose:
            print(f"[5/11] Deriving nDOM from DOM - DGM...")

        os.makedirs(temp_dir, exist_ok=True)

        # Check if alignment is needed (different resolution or grid)
        try:
            raster.validate_raster_alignment(dom_meta, dgm_meta)
            # Already aligned: compute nDOM directly
            ndom_temp_path = os.path.join(temp_dir, "ndom_from_files.tif")
            raster.compute_ndom(dom_raster, dgm_raster, ndom_temp_path)
        except ValueError:
            # Not aligned: align DGM to DOM grid first
            if verbose:
                print(f"       DOM ({dom_meta['res'][0]}m) and DGM ({dgm_meta['res'][0]}m) "
                      f"grids differ, aligning DGM to DOM...")
            dgm_aligned_path = os.path.join(temp_dir, "dgm_aligned_to_dom.tif")
            raster.align_raster_to_reference(dgm_raster, dom_raster, dgm_aligned_path, resampling="bilinear")
            ndom_temp_path = os.path.join(temp_dir, "ndom_from_files.tif")
            raster.compute_ndom(dom_raster, dgm_aligned_path, ndom_temp_path)

        ndom_array, ndom_meta = raster.load_raster(ndom_temp_path)
        download_info['files']['ndom'] = ndom_temp_path

    else:  # raster_mode == "wcs_download"
        # Download from LDBV (DOM20 tiles + DGM1 WCS)
        if verbose:
            print("[4/11] Downloading DOM20 tiles + DGM1 WCS...")

        # Get credentials
        user_cred, password_cred = ldbv_download.get_credentials(user, password, allow_prompt=True)

        # Download and derive nDOM
        dom_path, dgm_path, ndom_path = ldbv_download.download_and_derive_ndom(
            minx=extent_25832[0],
            miny=extent_25832[1],
            maxx=extent_25832[2],
            maxy=extent_25832[3],
            user=user_cred,
            password=password_cred,
            target_resolution_m=target_resolution_m,
            temp_dir=temp_dir,
            verbose=verbose
        )

        # Load nDOM
        if verbose:
            print(f"[5/11] Loading derived nDOM...")
        ndom_array, ndom_meta = raster.load_raster(ndom_path)

        download_info['files']['dom'] = dom_path
        download_info['files']['dgm'] = dgm_path
        download_info['files']['ndom'] = ndom_path

    # ========================================================================
    # STEP 6: CLIP RASTER TO GEOMETRY
    # ========================================================================
    if verbose:
        print("[6/11] Clipping raster to analysis geometry...")

    clipped_array, clipped_meta = raster.clip_raster_to_geometry(
        raster_array=ndom_array,
        raster_meta=ndom_meta,
        geometry_gdf=buffer_gdf
    )

    if verbose:
        print(f"       Clipped size: {clipped_array.shape[0]} x {clipped_array.shape[1]} pixels")

    # ========================================================================
    # STEP 7: SAVE CLIPPED RASTER (OPTIONAL)
    # ========================================================================
    if output_clipped_raster_path:
        if verbose:
            print(f"[7/11] Saving clipped raster to {output_clipped_raster_path}...")
        raster.save_raster(clipped_array, clipped_meta, output_clipped_raster_path)
    else:
        if verbose:
            print("[7/11] Skipping clipped raster save (no output path)")

    # ========================================================================
    # STEP 8: CHECK HEIGHT THRESHOLD
    # ========================================================================
    if verbose:
        print(f"[8/11] Checking height threshold ({threshold_height_m}m, minimum {min_prop_above_threshold:.0%})...")

    threshold_met, threshold_stats = analysis.check_height_threshold(
        raster_array=clipped_array,
        nodata_value=clipped_meta['nodata'],
        threshold_height_m=threshold_height_m,
        min_prop_above_threshold=min_prop_above_threshold
    )

    if verbose:
        print(f"       Valid cells: {threshold_stats['total_valid_cells']:,}")
        print(f"       Above threshold: {threshold_stats['cells_above_threshold']:,} "
              f"({threshold_stats['proportion_above_threshold']:.1%})")
        print(f"       Threshold {'MET ✓' if threshold_met else 'NOT MET ✗'}")

    # ========================================================================
    # STEP 9: COMPUTE HISTOGRAM (CONDITIONAL)
    # ========================================================================
    histogram_results = None

    if threshold_met:
        if verbose:
            print("[9/11] Computing height histogram...")

        histogram_results = analysis.classify_height_data(
            raster_array=clipped_array,
            nodata_value=clipped_meta['nodata'],
            classes=classes
        )

        if verbose:
            print(f"       Classes: {len(histogram_results['class_labels'])}")
    else:
        if verbose:
            print("[9/11] Skipping histogram (threshold not met)")

    # ========================================================================
    # STEP 10: GENERATE PLOT (CONDITIONAL)
    # ========================================================================
    plot_saved_path = None

    if threshold_met:
        if verbose:
            print("[10/11] Generating histogram plot...")

        fig = plotting.plot_height_histogram(
            class_labels=histogram_results['class_labels'],
            class_counts=histogram_results['class_counts'],
            threshold_height_m=threshold_height_m,
            output_path=output_plot_path,
            title=f"Canopy Height Distribution (n={threshold_stats['total_valid_cells']:,} pixels)"
        )

        plot_saved_path = output_plot_path

        if verbose and output_plot_path:
            print(f"       Plot saved: {output_plot_path}")
        elif verbose:
            print(f"       Plot generated (not saved, use output_plot_path to save)")

    else:
        if verbose:
            print("[10/11] Skipping plot (threshold not met)")

    # ========================================================================
    # STEP 11: GENERATE SUMMARY
    # ========================================================================
    if verbose:
        print("[11/11] Generating summary...")

    summary_text = analysis.generate_summary_text(
        geometry_gdf=buffer_gdf,
        threshold_stats=threshold_stats,
        histogram=histogram_results,
        threshold_height_m=threshold_height_m,
        resolution_m=target_resolution_m
    )

    if verbose:
        print("\n" + summary_text)

    # ========================================================================
    # RETURN STRUCTURED RESULTS
    # ========================================================================
    results = {
        'geometry': {
            'buffer_geometry': buffer_gdf,
            'center_coords': coords_validated,
            'area_m2': area_m2,
            'area_ha': area_ha,
            'crs_metric': str(buffer_gdf.crs),
            'extent_25832': extent_25832,
            'extent_4326': extent_4326
        },
        'raster': {
            'clipped_array': clipped_array,
            'metadata': clipped_meta,
            'stats': raster.get_raster_stats(clipped_array, clipped_meta['nodata']),
            'resolution_m': target_resolution_m,
            'saved_path': output_clipped_raster_path
        },
        'analysis': {
            'threshold_met': threshold_met,
            'threshold_height_m': threshold_height_m,
            'min_prop_above_threshold': min_prop_above_threshold,
            'threshold_stats': threshold_stats,
            'histogram': histogram_results,
            'summary_text': summary_text
        },
        'outputs': {
            'plot_path': plot_saved_path,
            'raster_path': output_clipped_raster_path
        },
        'download_info': download_info
    }

    if verbose:
        print("="*70)
        print("ANALYSIS COMPLETE")
        print("="*70 + "\n")

    return results


if __name__ == "__main__":
    # Simple command-line test
    print("Forestry Canopy Height Analysis")
    print("Run from Python or Jupyter notebook, not as script")
    print("\nExample usage:")
    print("""
    from canopy_histogram import canopy_histogram_ldbv

    results = canopy_histogram_ldbv(
        coords=[(11.5234, 48.1372)],
        radius_m=50,
        classes=[0, 15, 25, 35, 50]
    )
    """)
