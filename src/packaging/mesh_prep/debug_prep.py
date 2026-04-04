import trimesh
from pathlib import Path
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

from .orient import center_and_align
from .seal import seal_endpoints


def visualize_mesh(mesh, title="Mesh"):
    V = mesh.vertices
    F = mesh.faces

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection="3d")

    poly = Poly3DCollection(
        V[F],
        facecolor=(0.6, 0.8, 1.0),
        edgecolor="k",
        linewidths=0.05,
        alpha=0.5,   # translucent so interior visibility is obvious
    )
    ax.add_collection3d(poly)

    mins = V.min(axis=0)
    maxs = V.max(axis=0)
    center = 0.5 * (mins + maxs)
    radius = 0.5 * (maxs - mins).max()

    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(center[1] - radius, center[1] + radius)
    ax.set_zlim(center[2] - radius, center[2] + radius)

    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.set_title(title)

    plt.tight_layout()
    plt.show()


def run_debug_prep(input_path):
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    output_dir = Path("data/stl/prepared")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{input_path.stem}_capped.stl"

    # --------------------------------------------------
    # LOAD
    # --------------------------------------------------
    mesh = trimesh.load(input_path, force="mesh")
    zmax = mesh.vertices[:, 2].max()
    print(f"[LOAD] watertight={mesh.is_watertight}  z_max={zmax:.3f}")

    # --------------------------------------------------
    # ORIENT
    # --------------------------------------------------
    mesh = center_and_align(mesh)
    zmax = mesh.vertices[:, 2].max()
    print(f"[ORIENT] z_max={zmax:.3f}")

    # --------------------------------------------------
    # VISUALIZE BEFORE
    # --------------------------------------------------
    visualize_mesh(mesh, title="Before sealing (interior visible)")

    # --------------------------------------------------
    # SEAL TOP (THIS IS THE ONLY OPERATION THAT MATTERS)
    # --------------------------------------------------
    mesh = seal_endpoints(mesh, top_frac=0.35)

    zmax = mesh.vertices[:, 2].max()
    print(f"[SEALED] z_max={zmax:.3f}")

    # --------------------------------------------------
    # SAVE
    # --------------------------------------------------
    mesh.export(output_path)
    print(f"[SAVED] {output_path}")

    # --------------------------------------------------
    # VISUALIZE AFTER
    # --------------------------------------------------
    visualize_mesh(mesh, title="After sealing (top capped, interior hidden)")


if __name__ == "__main__":
    run_debug_prep("data/stl/input/Pitcher.stl")
