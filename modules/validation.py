"""
validation.py
=============

Input validation and error checking for forestry inventory workflow.
"""

from typing import List, Tuple, Optional, Union
from pathlib import Path
import pyproj


# Custom Exceptions
class InvalidCoordinatesError(ValueError):
    """Raised when coordinate input is invalid."""
    pass


class InvalidCRSError(ValueError):
    """Raised when CRS input is invalid."""
    pass


class RasterInputError(ValueError):
    """Raised when raster input configuration is invalid."""
    pass


def validate_coordinates(coords: Union[List, Tuple]) -> List[Tuple[float, float]]:
    """
    Validate coordinate input format.

    Parameters
    ----------
    coords : list or tuple
        Either one (x, y) pair or two [(x1, y1), (x2, y2)] pairs

    Returns
    -------
    list of tuples
        Validated coordinate pairs

    Raises
    ------
    InvalidCoordinatesError
        If coords format is invalid
    """
    # Convert to list if needed
    if not isinstance(coords, (list, tuple)):
        raise InvalidCoordinatesError(
            f"coords must be a list or tuple, got {type(coords).__name__}"
        )

    # Handle single coordinate pair
    if len(coords) == 2 and isinstance(coords[0], (int, float)):
        # This is a single (x, y) pair
        try:
            x, y = float(coords[0]), float(coords[1])
            return [(x, y)]
        except (TypeError, ValueError) as e:
            raise InvalidCoordinatesError(f"Invalid coordinate values: {e}")

    # Handle list of coordinate pairs
    if len(coords) == 0:
        raise InvalidCoordinatesError("coords cannot be empty")

    if len(coords) > 2:
        raise InvalidCoordinatesError(
            f"coords must contain 1 or 2 coordinate pairs, got {len(coords)}"
        )

    # Validate each pair
    validated = []
    for i, pair in enumerate(coords):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise InvalidCoordinatesError(
                f"Coordinate pair {i} must be a (x, y) tuple, got {pair}"
            )
        try:
            x, y = float(pair[0]), float(pair[1])
            validated.append((x, y))
        except (TypeError, ValueError) as e:
            raise InvalidCoordinatesError(
                f"Invalid values in coordinate pair {i}: {e}"
            )

    return validated


def validate_crs(crs_input: Union[str, int, pyproj.CRS]) -> pyproj.CRS:
    """
    Validate and normalize CRS input.

    Parameters
    ----------
    crs_input : str, int, or pyproj.CRS
        CRS specification (e.g., "EPSG:4326", 4326, or CRS object)

    Returns
    -------
    pyproj.CRS
        Validated CRS object

    Raises
    ------
    InvalidCRSError
        If CRS cannot be parsed or is invalid
    """
    try:
        if isinstance(crs_input, pyproj.CRS):
            return crs_input
        return pyproj.CRS(crs_input)
    except pyproj.exceptions.CRSError as e:
        raise InvalidCRSError(f"Invalid CRS '{crs_input}': {e}")


def check_file_exists(file_path: Optional[Union[str, Path]],
                     file_description: str) -> None:
    """
    Check if a file exists.

    Parameters
    ----------
    file_path : str, Path, or None
        Path to check (None is allowed)
    file_description : str
        Description for error message

    Raises
    ------
    FileNotFoundError
        If file_path is provided but file doesn't exist
    """
    if file_path is not None:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(
                f"{file_description} not found: {file_path}"
            )
        if not path.is_file():
            raise FileNotFoundError(
                f"{file_description} is not a file: {file_path}"
            )


def validate_input_parameters(
    coords,
    radius_m: float,
    classes: List[float],
    threshold_height_m: float,
    min_prop_above_threshold: float,
    transect_mode: str,
    input_crs,
    target_resolution_m: float,
    analysis_raster: Optional[str],
    dom_raster: Optional[str],
    dgm_raster: Optional[str],
    user: Optional[str],
    password: Optional[str]
) -> dict:
    """
    Comprehensive validation of all input parameters.

    Returns
    -------
    dict
        Dictionary with validated parameters

    Raises
    ------
    Various exceptions
        For invalid parameters with descriptive messages
    """
    # Validate coordinates
    validated_coords = validate_coordinates(coords)

    # Validate buffer radius
    if radius_m <= 0:
        raise ValueError(f"radius_m must be positive, got {radius_m}")

    # Validate classes
    if not isinstance(classes, (list, tuple)) or len(classes) < 2:
        raise ValueError(
            f"classes must be a list with at least 2 values, got {classes}"
        )
    classes_sorted = sorted(classes)
    if classes_sorted != list(classes):
        raise ValueError(
            f"classes must be in increasing order, got {classes}"
        )

    # Validate threshold parameters
    if threshold_height_m <= 0:
        raise ValueError(
            f"threshold_height_m must be positive, got {threshold_height_m}"
        )

    if not (0 <= min_prop_above_threshold <= 1):
        raise ValueError(
            f"min_prop_above_threshold must be between 0 and 1, got {min_prop_above_threshold}"
        )

    # Validate transect mode
    valid_modes = ["buffer_line", "midpoint_circle"]
    if transect_mode not in valid_modes:
        raise ValueError(
            f"transect_mode must be one of {valid_modes}, got '{transect_mode}'"
        )

    # Validate CRS
    validated_crs = validate_crs(input_crs)

    # Validate target resolution
    if target_resolution_m <= 0:
        raise ValueError(
            f"target_resolution_m must be positive, got {target_resolution_m}"
        )

    # Validate raster inputs
    # Three valid scenarios:
    # 1. analysis_raster provided (pre-normalized)
    # 2. dom_raster AND dgm_raster provided (will derive nDOM)
    # 3. Neither provided (will download via WCS - requires credentials)

    if analysis_raster is not None:
        # Scenario 1: Pre-normalized raster
        check_file_exists(analysis_raster, "analysis_raster")
        raster_mode = "analysis_raster"
    elif dom_raster is not None and dgm_raster is not None:
        # Scenario 2: DOM and DGM provided
        check_file_exists(dom_raster, "dom_raster")
        check_file_exists(dgm_raster, "dgm_raster")
        raster_mode = "dom_dgm_files"
    elif dom_raster is not None or dgm_raster is not None:
        # Only one of DOM/DGM provided - error
        raise RasterInputError(
            "If providing DOM/DGM, both dom_raster AND dgm_raster must be specified"
        )
    else:
        # Scenario 3: Download via WCS
        # Credentials will be checked later by ldbv_download module
        raster_mode = "wcs_download"

    return {
        "coords": validated_coords,
        "radius_m": radius_m,
        "classes": list(classes),
        "threshold_height_m": threshold_height_m,
        "min_prop_above_threshold": min_prop_above_threshold,
        "transect_mode": transect_mode,
        "input_crs": validated_crs,
        "target_resolution_m": target_resolution_m,
        "raster_mode": raster_mode
    }
