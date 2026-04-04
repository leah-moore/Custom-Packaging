from pathlib import Path
import trimesh
import numpy as np

# ---------------- USER SETTINGS ----------------

# Input STL (matches your tree)
INPUT_STL = Path("data/stl/prepared/widePot_aligned.stl")

# Output STL
OUTPUT_STL = Path("data/stl/prepared/widePot_scaled.stl")

# Target size
TARGET_MAX_DIM_MM = 150.0  # mm

# ------------------------------------------------


def main():
    if not INPUT_STL.exists():
        raise FileNotFoundError(f"Input STL not found: {INPUT_STL}")

    mesh = trimesh.load(INPUT_STL, force="mesh")

    bounds = mesh.bounds
    size = bounds[1] - bounds[0]
    current_max = size.max()

    if current_max <= 0:
        raise ValueError("Invalid STL dimensions")

    scale_factor = TARGET_MAX_DIM_MM / current_max

    print(f"Input STL       : {INPUT_STL}")
    print(f"Current size    : {size}")
    print(f"Max dimension   : {current_max:.3f} mm")
    print(f"Scale factor    : {scale_factor:.6f}")

    mesh.apply_scale(scale_factor)

    OUTPUT_STL.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(OUTPUT_STL)

    print(f"Scaled STL saved to: {OUTPUT_STL}")


if __name__ == "__main__":
    main()
