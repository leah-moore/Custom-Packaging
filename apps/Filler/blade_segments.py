"""
Blade segmentation utilities.

Convert smooth Shapely geometry into straight segments with
bounded geometric error (Douglas–Peucker simplification).
"""

from shapely.geometry import Polygon, MultiPolygon, GeometryCollection


def blade_segmentize(geom, tol=0.3):
    """
    Convert curved polygon boundaries into straight blade segments.

    Parameters
    ----------
    geom : Shapely geometry
        Polygon / MultiPolygon / etc.
    tol : float
        Maximum deviation from original curve (same units as geometry, e.g. mm)

    Returns
    -------
    Shapely geometry (same type)
    """
    if geom is None or geom.is_empty:
        return geom

    try:
        return geom.simplify(float(tol), preserve_topology=True)
    except Exception:
        return geom


def segmentize_list(geoms, tol=0.3):
    """
    Apply blade segmentation to a list of geometries.
    """
    if geoms is None:
        return None
    return [blade_segmentize(g, tol) for g in geoms]