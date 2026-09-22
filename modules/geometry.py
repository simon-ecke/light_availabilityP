"""
geometry.py
===========

Geometry operations: buffering, CRS handling, extent computation.
All metric operations use EPSG:25832 (ETRS89 / UTM zone 32N),
the official coordinate reference system for Bavaria / LDBV products.
"""

from typing import List, Tuple, Dict
import geopandas as gpd
from shapely.geometry import Point, LineString
import pyproj

# Official CRS for Bavaria and all LDBV products
BAVARIA_CRS = "EPSG:25832"


def create_point_buffer(coord: Tuple[float, float],
                        radius_m: float,
                        input_crs: pyproj.CRS) -> gpd.GeoDataFrame:
    """
    Create circular buffer around a single point.

    Parameters
    ----------
    coord : tuple
        (x, y) coordinate pair
    radius_m : float
        Buffer radius in meters
    input_crs : pyproj.CRS
        CRS of input coordinates

    Returns
    -------
    gpd.GeoDataFrame
        Buffered geometry in EPSG:25832
    """
    # Create point geometry
    point = Point(coord)
    gdf = gpd.GeoDataFrame({'geometry': [point]}, crs=input_crs)

    # Reproject to EPSG:25832 if input is geographic
    if input_crs.is_geographic:
        gdf_metric = gdf.to_crs(BAVARIA_CRS)
    else:
        gdf_metric = gdf

    # Apply buffer
    gdf_metric['geometry'] = gdf_metric.geometry.buffer(radius_m)

    return gdf_metric


def create_line_buffer(coord1: Tuple[float, float],
                      coord2: Tuple[float, float],
                      radius_m: float,
                      input_crs: pyproj.CRS) -> gpd.GeoDataFrame:
    """
    Create buffer corridor along line between two points.

    Parameters
    ----------
    coord1 : tuple
        (x, y) for start point
    coord2 : tuple
        (x, y) for end point
    radius_m : float
        Buffer radius in meters
    input_crs : pyproj.CRS
        CRS of input coordinates

    Returns
    -------
    gpd.GeoDataFrame
        Buffered line geometry in EPSG:25832
    """
    # Create line geometry
    line = LineString([coord1, coord2])
    gdf = gpd.GeoDataFrame({'geometry': [line]}, crs=input_crs)

    # Reproject to EPSG:25832 if input is geographic
    if input_crs.is_geographic:
        gdf_metric = gdf.to_crs(BAVARIA_CRS)
    else:
        gdf_metric = gdf

    # Apply buffer
    gdf_metric['geometry'] = gdf_metric.geometry.buffer(radius_m)

    return gdf_metric


def create_midpoint_buffer(coord1: Tuple[float, float],
                           coord2: Tuple[float, float],
                           radius_m: float,
                           input_crs: pyproj.CRS) -> gpd.GeoDataFrame:
    """
    Create circular buffer at midpoint between two points.

    Parameters
    ----------
    coord1 : tuple
        (x, y) for first point
    coord2 : tuple
        (x, y) for second point
    radius_m : float
        Buffer radius in meters
    input_crs : pyproj.CRS
        CRS of input coordinates

    Returns
    -------
    gpd.GeoDataFrame
        Buffered geometry in EPSG:25832
    """
    # Calculate midpoint
    midpoint = ((coord1[0] + coord2[0]) / 2, (coord1[1] + coord2[1]) / 2)

    # Create buffer around midpoint
    return create_point_buffer(midpoint, radius_m, input_crs)


def create_analysis_geometry(
    coords: List[Tuple[float, float]],
    radius_m: float,
    transect_mode: str,
    input_crs: pyproj.CRS
) -> gpd.GeoDataFrame:
    """
    Create analysis geometry based on input coordinates and mode.

    Parameters
    ----------
    coords : list of tuples
        1 or 2 (x, y) coordinate pairs
    radius_m : float
        Buffer radius in meters
    transect_mode : str
        "buffer_line" or "midpoint_circle"
    input_crs : pyproj.CRS
        CRS of input coordinates

    Returns
    -------
    gpd.GeoDataFrame
        Buffered analysis geometry in EPSG:25832
    """
    if len(coords) == 1:
        # Single point: circular buffer
        return create_point_buffer(coords[0], radius_m, input_crs)

    elif len(coords) == 2:
        # Two points: depends on mode
        if transect_mode == "buffer_line":
            return create_line_buffer(coords[0], coords[1], radius_m, input_crs)
        else:  # midpoint_circle
            return create_midpoint_buffer(coords[0], coords[1], radius_m, input_crs)

    else:
        raise ValueError(f"Expected 1 or 2 coordinates, got {len(coords)}")


def compute_extent_25832(geometry_gdf: gpd.GeoDataFrame) -> Tuple[float, float, float, float]:
    """
    Compute bounding box in EPSG:25832 for LDBV WCS download.

    Parameters
    ----------
    geometry_gdf : gpd.GeoDataFrame
        Geometry in any CRS

    Returns
    -------
    tuple
        (minx, miny, maxx, maxy) in EPSG:25832
    """
    # Reproject to EPSG:25832 (LDBV native CRS)
    gdf_25832 = geometry_gdf.to_crs("EPSG:25832")

    # Get bounds
    bounds = gdf_25832.total_bounds  # (minx, miny, maxx, maxy)

    return tuple(bounds)


def compute_geographic_extent(geometry_gdf: gpd.GeoDataFrame) -> Dict:
    """
    Compute bounding box in EPSG:4326 for display/export.

    Parameters
    ----------
    geometry_gdf : gpd.GeoDataFrame
        Geometry in any CRS

    Returns
    -------
    dict
        Extent dictionary with xmin, ymin, xmax, ymax, crs
    """
    # Reproject to EPSG:4326
    gdf_4326 = geometry_gdf.to_crs("EPSG:4326")

    # Get bounds
    minx, miny, maxx, maxy = gdf_4326.total_bounds

    return {
        'xmin': minx,
        'ymin': miny,
        'xmax': maxx,
        'ymax': maxy,
        'crs': 'EPSG:4326'
    }
