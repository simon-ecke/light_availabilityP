"""
batch.py
========

Batch processing helpers for comparing field-based canopy closure estimates
(Überschurmung_geschätzt) against DSM/DTM-derived canopy metrics across many
inventory points loaded from a single CSV export.
"""

from typing import List, Tuple
import numpy as np
import pandas as pd
import pyproj

from .geometry import BAVARIA_CRS


def load_light_points_csv(csv_path: str) -> pd.DataFrame:
    """
    Load and clean a Lichtverprobung CSV export.

    Drops fully-empty trailing rows and builds a human-readable `point_id`
    (Title + Versuchsfläche) and a filesystem-safe `point_slug` for filenames.

    Parameters
    ----------
    csv_path : str
        Path to the semicolon-separated CSV export.

    Returns
    -------
    pd.DataFrame
    """
    df = pd.read_csv(csv_path, sep=';', encoding='utf-8-sig')
    df = df.dropna(subset=['Title']).reset_index(drop=True)

    df['point_id'] = df['Title'].astype(str) + ' (' + df['Versuchsfläche'].astype(str) + ')'
    df['point_slug'] = (
        df['Title'].astype(str) + '_' + df['Versuchsfläche'].astype(str)
    ).str.replace(r'[^A-Za-z0-9_.-]+', '_', regex=True)

    return df


def project_to_metric(lon: np.ndarray, lat: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Project WGS84 lon/lat arrays to EPSG:25832 (meters)."""
    transformer = pyproj.Transformer.from_crs("EPSG:4326", BAVARIA_CRS, always_xy=True)
    x, y = transformer.transform(np.asarray(lon), np.asarray(lat))
    return np.asarray(x), np.asarray(y)


def cluster_points_by_distance(
    lon: np.ndarray,
    lat: np.ndarray,
    max_distance_m: float = 800.0
) -> np.ndarray:
    """
    Group points into clusters by distance chaining (union-find): two points
    share a cluster if there is a chain of points between them each within
    `max_distance_m` of the next.

    This lets one bounding-box DSM/DTM download cover every point in a
    cluster, so nearby inventory points don't each trigger their own
    download of the same tiles.

    Returns
    -------
    np.ndarray of int
        Cluster label per input point (0-indexed).
    """
    x, y = project_to_metric(lon, lat)
    n = len(x)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            d = np.hypot(x[i] - x[j], y[i] - y[j])
            if d <= max_distance_m:
                union(i, j)

    roots = np.array([find(i) for i in range(n)])
    _, labels = np.unique(roots, return_inverse=True)
    return labels


def cluster_bbox_25832(
    lon: np.ndarray,
    lat: np.ndarray,
    point_radius_m: float,
    margin_m: float = 50.0
) -> Tuple[float, float, float, float]:
    """
    Bounding box in EPSG:25832 covering all given points, each point's
    analysis buffer, and an extra margin.
    """
    x, y = project_to_metric(lon, lat)
    pad = point_radius_m + margin_m
    return (float(x.min() - pad), float(y.min() - pad),
            float(x.max() + pad), float(y.max() + pad))


def summarize_clusters(df: pd.DataFrame, cluster_col: str = 'cluster') -> pd.DataFrame:
    """One row per cluster: point count, Versuchsfläche(n), lon/lat extent."""
    rows = []
    for cid, sub in df.groupby(cluster_col):
        rows.append({
            'cluster': cid,
            'n_points': len(sub),
            'versuchsflaechen': ', '.join(sorted(sub['Versuchsfläche'].unique())),
            'lon_min': sub['Longitude'].min(),
            'lon_max': sub['Longitude'].max(),
            'lat_min': sub['Latitude'].min(),
            'lat_max': sub['Latitude'].max(),
        })
    return pd.DataFrame(rows).sort_values('cluster').reset_index(drop=True)
