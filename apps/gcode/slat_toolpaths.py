"""
Slat toolpath extraction layer.

Converts nested slat geometry (Shapely polygons laid out on sheets)
into knife-only toolpaths suitable for the existing CAM pipeline.

This is GEOMETRY ONLY:
- No feeds
- No Z
- No machine sequencing
"""

from __future__ import annotations
from typing import List, Dict, Tuple
from shapely.geometry import Polygon, MultiPolygon
from apps.gcode.extract_toolpaths import chain_segments,add_leads
Point = Tuple[float, float]


# -------------------------------------------------
# Polygon → knife paths
# -------------------------------------------------

def polygon_to_knife_segments(poly: Polygon) -> List[Tuple[Point, Point]]:
    segs = []

    if poly.is_empty:
        return segs

    def ring_to_segs(coords):
        pts = list(coords)
        for i in range(len(pts) - 1):
            p = (float(pts[i][0]), float(pts[i][1]))
            q = (float(pts[i+1][0]), float(pts[i+1][1]))
            if p != q:
                segs.append((p, q))

    ring_to_segs(poly.exterior.coords)

    for hole in poly.interiors:
        ring_to_segs(hole.coords)

    return segs

def geometry_to_knife_segments(geom) -> List[Tuple[Point, Point]]:
    segs = []

    if geom is None or geom.is_empty:
        return segs

    if isinstance(geom, Polygon):
        segs.extend(polygon_to_knife_segments(geom))

    elif isinstance(geom, MultiPolygon):
        for p in geom.geoms:
            segs.extend(polygon_to_knife_segments(p))

    else:
        try:
            for g in geom.geoms:
                segs.extend(geometry_to_knife_segments(g))
        except Exception:
            pass

    return segs


# -------------------------------------------------
# Sheet → toolpaths (THIS is the entry point)
# -------------------------------------------------
def sheet_layout_to_toolpaths(sheet_layout):
    knife_segs = []

    for part in sheet_layout.parts:
        geom = getattr(part, "placed", None)
        if geom is None:
            continue
        knife_segs.extend(geometry_to_knife_segments(geom))

    # Chain ONLY — no leads for slats
    knife_paths = chain_segments(knife_segs)

    return {
        "knife": knife_paths,
        "crease": [],
    }

import matplotlib.pyplot as plt

# -------------------------------------------------
# Visualization
# -------------------------------------------------

def plot_slat_toolpaths(sheet_layout, title="Slat toolpaths preview"):
    """
    Visualize slat geometry + extracted knife paths for ONE sheet.
    """

    toolpaths = sheet_layout_to_toolpaths(sheet_layout)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")

    # --- draw sheet boundary ---
    W = sheet_layout.sheet_w
    H = sheet_layout.sheet_h
    ax.plot([0, W, W, 0, 0], [0, 0, H, H, 0], "k-", lw=2)

    # --- draw placed slat geometry (light gray) ---
    for part in sheet_layout.parts:
        g = part.placed
        if g.is_empty:
            continue

        x, y = g.exterior.xy
        ax.fill(x, y, color="#dddddd", alpha=0.6, zorder=1)

        for hole in g.interiors:
            hx, hy = hole.xy
            ax.fill(hx, hy, color="white", zorder=2)

    # --- draw knife paths (red) ---
    for path in toolpaths["knife"]:
        xs = [p[0] for p in path]
        ys = [p[1] for p in path]
        ax.plot(xs, ys, "r-", lw=1.8, zorder=3)

    ax.invert_yaxis()   # matches CAM + nesting view
    ax.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.show()


# ---------------------------------------------
# WORLD geometry → knife toolpaths (no sheets)
# ---------------------------------------------

def geometry_to_knife_paths(geom):
    """
    Convert a single shapely geometry into knife toolpaths.
    This mirrors the internal logic used by sheet_layout_to_toolpaths,
    but without nesting or sheets.
    """
    from shapely.geometry import Polygon, MultiPolygon

    paths = []

    if isinstance(geom, Polygon):
        paths.append(list(geom.exterior.coords))

    elif isinstance(geom, MultiPolygon):
        for g in geom.geoms:
            paths.append(list(g.exterior.coords))

    return paths
