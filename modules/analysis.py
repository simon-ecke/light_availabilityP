"""
analysis.py
===========

Height analysis: threshold checking, histogram computation, summary generation.
"""

from typing import Dict, List, Tuple, Optional
import numpy as np


def check_height_threshold(
    raster_array: np.ndarray,
    nodata_value: Optional[float],
    threshold_height_m: float,
    min_prop_above_threshold: float
) -> Tuple[bool, Dict]:
    """
    Check if proportion of valid cells above height threshold meets minimum.

    Parameters
    ----------
    raster_array : np.ndarray
        Height raster data
    nodata_value : float or None
        Nodata value to exclude
    threshold_height_m : float
        Height threshold (e.g., 15m)
    min_prop_above_threshold : float
        Minimum proportion required (e.g., 0.25 for 25%)

    Returns
    -------
    tuple
        (threshold_met: bool, stats: dict)
    """
    # Create mask for valid data
    if nodata_value is not None:
        valid_mask = (
            (raster_array != nodata_value) &
            ~np.isnan(raster_array) &
            np.isfinite(raster_array)
        )
    else:
        valid_mask = ~np.isnan(raster_array) & np.isfinite(raster_array)

    valid_data = raster_array[valid_mask]

    if len(valid_data) == 0:
        return False, {
            'total_valid_cells': 0,
            'cells_above_threshold': 0,
            'proportion_above_threshold': 0.0,
            'max_height': None,
            'mean_height': None,
            'mean_height_above_threshold': None
        }

    # Count cells above threshold
    above_threshold_mask = valid_data > threshold_height_m
    cells_above = np.sum(above_threshold_mask)
    proportion_above = cells_above / len(valid_data)

    # Compute statistics
    above_threshold_data = valid_data[above_threshold_mask]
    mean_above = float(above_threshold_data.mean()) if len(above_threshold_data) > 0 else None

    stats = {
        'total_valid_cells': len(valid_data),
        'cells_above_threshold': int(cells_above),
        'proportion_above_threshold': float(proportion_above),
        'max_height': float(valid_data.max()),
        'mean_height': float(valid_data.mean()),
        'mean_height_above_threshold': mean_above
    }

    # Check if threshold is met
    threshold_met = proportion_above >= min_prop_above_threshold

    return threshold_met, stats


def classify_height_data(
    raster_array: np.ndarray,
    nodata_value: Optional[float],
    classes: List[float]
) -> Dict:
    """
    Classify height data into custom class breaks.

    Parameters
    ----------
    raster_array : np.ndarray
        Height raster data
    nodata_value : float or None
        Nodata value to exclude
    classes : list of float
        Class break values (e.g., [0, 15, 25, 35, 50])

    Returns
    -------
    dict
        Classification results with class_labels, class_counts, class_proportions
    """
    # Create mask for valid data
    if nodata_value is not None:
        valid_mask = (
            (raster_array != nodata_value) &
            ~np.isnan(raster_array) &
            np.isfinite(raster_array)
        )
    else:
        valid_mask = ~np.isnan(raster_array) & np.isfinite(raster_array)

    valid_data = raster_array[valid_mask]

    if len(valid_data) == 0:
        # Return empty results
        n_classes = len(classes) - 1
        return {
            'class_labels': [],
            'class_counts': [0] * n_classes,
            'class_proportions': [0.0] * n_classes
        }

    # Compute histogram with custom bins
    counts, bin_edges = np.histogram(valid_data, bins=classes)

    # Create class labels
    class_labels = []
    for i in range(len(classes) - 1):
        if i == len(classes) - 2:
            # Last class: ">X m"
            label = f">{classes[i]}m"
        else:
            # Regular class: "X-Y m"
            label = f"{classes[i]}-{classes[i+1]}m"
        class_labels.append(label)

    # Compute proportions
    total = len(valid_data)
    proportions = [count / total for count in counts]

    return {
        'class_labels': class_labels,
        'class_counts': counts.tolist(),
        'class_proportions': proportions,
        'bin_edges': bin_edges.tolist()
    }


def generate_summary_text(
    geometry_gdf,
    threshold_stats: Dict,
    histogram: Optional[Dict],
    threshold_height_m: float,
    resolution_m: float
) -> str:
    """
    Generate human-readable summary text.

    Parameters
    ----------
    geometry_gdf : gpd.GeoDataFrame
        Analysis geometry
    threshold_stats : dict
        Threshold check results
    histogram : dict or None
        Histogram results (None if threshold not met)
    threshold_height_m : float
        Height threshold used
    resolution_m : float
        Raster resolution

    Returns
    -------
    str
        Formatted summary text
    """
    # Calculate area
    area_m2 = geometry_gdf.area[0]
    area_ha = area_m2 / 10000

    # Build summary
    lines = []
    lines.append("=" * 60)
    lines.append("CANOPY HEIGHT ANALYSIS SUMMARY")
    lines.append("=" * 60)
    lines.append(f"Analysis Area: {area_ha:.3f} ha ({area_m2:.1f} m²)")
    lines.append(f"Resolution: {resolution_m} m")
    lines.append(f"CRS: {geometry_gdf.crs}")
    lines.append("")

    # Threshold statistics
    lines.append("HEIGHT THRESHOLD ANALYSIS")
    lines.append("-" * 60)
    lines.append(f"Threshold: {threshold_height_m} m")
    lines.append(f"Total valid pixels: {threshold_stats['total_valid_cells']:,}")

    if threshold_stats['total_valid_cells'] > 0:
        lines.append(f"Pixels above threshold: {threshold_stats['cells_above_threshold']:,} "
                    f"({threshold_stats['proportion_above_threshold']:.1%})")
        lines.append(f"Maximum height: {threshold_stats['max_height']:.2f} m")
        lines.append(f"Mean height (all): {threshold_stats['mean_height']:.2f} m")
        if threshold_stats['mean_height_above_threshold'] is not None:
            lines.append(f"Mean height (above threshold): "
                        f"{threshold_stats['mean_height_above_threshold']:.2f} m")
    else:
        lines.append("WARNING: No valid data in analysis area")

    lines.append("")

    # Histogram
    if histogram is not None:
        lines.append("HEIGHT DISTRIBUTION")
        lines.append("-" * 60)
        for label, count, prop in zip(
            histogram['class_labels'],
            histogram['class_counts'],
            histogram['class_proportions']
        ):
            lines.append(f"  {label:>12}: {count:>8,} pixels ({prop:>6.1%})")
    else:
        lines.append("HEIGHT DISTRIBUTION")
        lines.append("-" * 60)
        lines.append(f"  Histogram not computed (threshold not met)")
        lines.append(f"  Required: ≥{threshold_stats.get('min_prop_threshold', 0.25):.0%} above {threshold_height_m}m")

    lines.append("=" * 60)

    return "\n".join(lines)
