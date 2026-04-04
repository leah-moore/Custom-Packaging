
# Corrugated cardboard visualization helpers
# Purely visual — does NOT modify geometry

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union


# ---------------- Visual parameters ----------------

DEFAULT_COLOR = "#c49a6c"   # kraft cardboard
EDGE_COLOR    = "#7a4a1e"

DEFAULT_ALPHA = 0.65
CORE_ALPHA    = 0.45

DEFAULT_WAVE_LEN_FACTOR = 2.0   # wavelength = factor * thickness
DEFAULT_WAVE_AMP_FACTOR = 0.35  # amplitude = factor * thickness

SURFACE_RES = 36


# ---------------- Utilities ----------------

def _poly_mask_grid(poly: Polygon, X, Y):
    """Boolean mask for points inside polygon."""
    mask = np.zeros_like(X, dtype=bool)
    for i in range(X.shape[0]):
        for j in range(X.shape[1]):
            mask[i, j] = poly.contains(
                Polygon([
                    (X[i, j], Y[i, j]),
                    (X[i, j] + 1e-6, Y[i, j]),
                    (X[i, j], Y[i, j] + 1e-6),
                ])
            )
    return mask


# ---------------- Main renderer ----------------

def plot_corrugated_board(
    ax,
    poly: Polygon,
    fixed_value: float,
    mode: str,
    thickness: float,
    color: str = DEFAULT_COLOR,
    alpha: float = DEFAULT_ALPHA,
    wave_len_factor: float = DEFAULT_WAVE_LEN_FACTOR,
    wave_amp_factor: float = DEFAULT_WAVE_AMP_FACTOR,
):
    """
    Render a corrugated cardboard board as:
      - top liner
      - bottom liner
      - sinusoidal corrugated core

    mode:
      - "xy": board lies in XY, thickness along Z
      - "xz": board lies in XZ, thickness along Y
    """

    if poly is None or poly.is_empty:
        return

    minx, miny, maxx, maxy = poly.bounds

    nx = ny = SURFACE_RES
    X = np.linspace(minx, maxx, nx)
    Y = np.linspace(miny, maxy, ny)
    XX, YY = np.meshgrid(X, Y)

    mask = _poly_mask_grid(poly, XX, YY)

    top = +0.5 * thickness
    bot = -0.5 * thickness

    wave_len = wave_len_factor * thickness
    wave_amp = wave_amp_factor * thickness

    core = wave_amp * np.sin(2 * np.pi * XX / wave_len)

    def masked(Z):
        Zarr = np.asarray(Z)
        if Zarr.shape == ():  # scalar → broadcast
            Zarr = np.full_like(XX, Zarr, dtype=float)
        Zm = Zarr.copy()
        Zm[~mask] = np.nan
        return Zm


    if mode == "xy":
        ax.plot_surface(
            XX, YY, masked(fixed_value + top),
            color=color, alpha=alpha, linewidth=0
        )
        ax.plot_surface(
            XX, YY, masked(fixed_value + bot),
            color=color, alpha=alpha, linewidth=0
        )
        ax.plot_surface(
            XX, YY, masked(fixed_value + core),
            color=color, alpha=CORE_ALPHA, linewidth=0
        )

    elif mode == "xz":
        ax.plot_surface(
            XX, masked(np.full_like(XX, fixed_value + top)), YY,
            color=color, alpha=alpha, linewidth=0
        )
        ax.plot_surface(
            XX, masked(np.full_like(XX, fixed_value + bot)), YY,
            color=color, alpha=alpha, linewidth=0
        )
        ax.plot_surface(
            XX, masked(np.full_like(XX, fixed_value + core)), YY,
            color=color, alpha=CORE_ALPHA, linewidth=0
        )
