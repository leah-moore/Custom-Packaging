import numpy as np
import trimesh
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from pathlib import Path


# ---------------- USER SETTINGS ----------------
INPUT_STL = Path("data/stl/input/Asymmetrical/StanleyCup.stl")
OUTPUT_STL = Path("data/stl/prepared/StanleyCup_aligned.stl")
SAVE_ALIGNED = True

SYMMETRY_MODE = "none"   # "none", "plane", "axis"
SHOW_SYMMETRY_PLANE = (SYMMETRY_MODE == "plane")
# ----------------------------------------------


# ============================================================
# Orientation utilities
# ============================================================

def align_long_axis_to_z(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """
    Rotate mesh so its principal (long) axis aligns with +Z.
    PCA-based; sign is arbitrary, so later steps set 'up/down'.
    """
    mesh = mesh.copy()
    V = mesh.vertices

    cov = np.cov(V.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    main_axis = eigvecs[:, np.argmax(eigvals)]

    # align main axis to +Z (sign ambiguity handled later too)
    if main_axis[2] < 0:
        main_axis = -main_axis

    R = trimesh.geometry.align_vectors(main_axis, [0.0, 0.0, 1.0])
    mesh.apply_transform(R)
    return mesh


def orient_by_largest_horizontal_hull_face(mesh: trimesh.Trimesh,
                                          normal_tol=0.9,
                                          prefer_down=True) -> trimesh.Trimesh:
    """
    Pick the base using the convex hull:
      - Compute convex hull
      - Find horizontal-ish faces on the hull (|nz| >= normal_tol)
      - Choose the largest projected area (area * |nz|)
      - Flip mesh if that hull face normal points the wrong way (so base faces downward)

    This is much harder for lids/straws to "win" because they are usually not a clean,
    uninterrupted hull plane, while the base almost always is.
    """
    mesh = mesh.copy()

    hull = mesh.convex_hull
    N = hull.face_normals
    A = hull.area_faces

    horiz = np.abs(N[:, 2]) >= normal_tol
    if not np.any(horiz):
        # fall back: do nothing
        return mesh

    proj_area = A * np.abs(N[:, 2])
    best = np.argmax(np.where(horiz, proj_area, 0.0))

    # We want the "support" face to face DOWN (negative Z normal)
    # If prefer_down=True and hull face points up, flip 180° about X.
    if prefer_down and N[best, 2] > 0:
        Rx = trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0])
        mesh.apply_transform(Rx)

    # If prefer_down=False and hull face points down, flip.
    if (not prefer_down) and N[best, 2] < 0:
        Rx = trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0])
        mesh.apply_transform(Rx)

    return mesh


def snap_support_plane_to_z0(mesh: trimesh.Trimesh,
                             normal_tol=0.9) -> trimesh.Trimesh:
    """
    Snap the detected support plane (largest horizontal hull face) to Z=0.

    IMPORTANT: This avoids being fooled by tiny nubs/feet that set min(Z).
    """
    mesh = mesh.copy()

    hull = mesh.convex_hull
    N = hull.face_normals
    A = hull.area_faces
    Vh = hull.vertices
    Fh = hull.faces

    horiz = np.abs(N[:, 2]) >= normal_tol
    if not np.any(horiz):
        # fallback to min(z)
        zmin = mesh.vertices[:, 2].min()
        mesh.apply_translation([0.0, 0.0, -zmin])
        return mesh

    proj_area = A * np.abs(N[:, 2])
    best = np.argmax(np.where(horiz, proj_area, 0.0))

    # plane height = mean z of that face on the hull
    support_z = Vh[Fh[best]][:, 2].mean()

    # translate so that plane sits at z=0
    mesh.apply_translation([0.0, 0.0, -support_z])

    # safety: ensure no negative Z due to numerical noise
    zmin = mesh.vertices[:, 2].min()
    if zmin < -1e-6:
        mesh.apply_translation([0.0, 0.0, -zmin])

    return mesh


# ============================================================
# World-grid preparation (your existing logic, unchanged)
# ============================================================

def prepare_mesh_for_worldgrid_insertion(mesh: trimesh.Trimesh,
                                         symmetry_mode="none") -> trimesh.Trimesh:
    mesh = mesh.copy()

    # Center Y
    centroid = mesh.centroid
    mesh.apply_translation([0.0, -centroid[1], 0.0])

    # Optional symmetry alignment
    if symmetry_mode == "plane":
        V = mesh.vertices.copy()
        V[:, 2] = 0.0

        cov = np.cov(V[:, :2].T)
        eigvals, eigvecs = np.linalg.eigh(cov)

        sym_dir = eigvecs[:, np.argmin(eigvals)]
        angle = np.arctan2(sym_dir[1], sym_dir[0])

        Rz = trimesh.transformations.rotation_matrix(-angle, [0, 0, 1])
        mesh.apply_transform(Rz)

        centroid = mesh.centroid
        mesh.apply_translation([0.0, -centroid[1], 0.0])

    elif symmetry_mode not in ("none", "axis"):
        raise ValueError(f"Unknown symmetry_mode: {symmetry_mode}")

    # Center X by silhouette
    xmin, xmax = mesh.vertices[:, 0].min(), mesh.vertices[:, 0].max()
    mesh.apply_translation([-(xmin + xmax) * 0.5, 0.0, 0.0])

    return mesh


# ============================================================
# Plotting helpers
# ============================================================

def plot_mesh(ax, mesh, color=(0.4, 0.6, 0.9), alpha=0.6):
    poly = Poly3DCollection(mesh.vertices[mesh.faces], alpha=alpha)
    poly.set_facecolor(color)
    poly.set_edgecolor("k")
    ax.add_collection3d(poly)


def plot_yz_plane(ax, mesh, alpha=0.15):
    mins, maxs = mesh.bounds
    y = np.linspace(mins[1], maxs[1], 20)
    z = np.linspace(mins[2], maxs[2], 20)
    Y, Z = np.meshgrid(y, z)
    X = np.zeros_like(Y)
    ax.plot_surface(X, Y, Z, color="red", alpha=alpha, linewidth=0)


def set_axes_equal(ax, verts):
    mins, maxs = verts.min(axis=0), verts.max(axis=0)
    center = (mins + maxs) / 2
    span = (maxs - mins).max() / 2

    ax.set_xlim(center[0] - span, center[0] + span)
    ax.set_ylim(center[1] - span, center[1] + span)
    ax.set_zlim(center[2] - span, center[2] + span)

    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")


# ============================================================
# Main
# ============================================================

def main():
    mesh = trimesh.load(INPUT_STL, force="mesh")

    # 1. Align long axis → Z
    mesh = align_long_axis_to_z(mesh)

    # 2. Decide which side is the base using convex hull
    mesh = orient_by_largest_horizontal_hull_face(mesh, normal_tol=0.9, prefer_down=True)

    # 3. Snap the *support plane* to Z=0 (not just min(Z))
    mesh = snap_support_plane_to_z0(mesh, normal_tol=0.9)

    # 4. World-grid centering / symmetry
    mesh = prepare_mesh_for_worldgrid_insertion(
        mesh,
        symmetry_mode=SYMMETRY_MODE
    )

    if SAVE_ALIGNED:
        OUTPUT_STL.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(OUTPUT_STL)
        print(f"Saved aligned STL to: {OUTPUT_STL}")

    # ---- Preview ----
    fig = plt.figure(figsize=(9, 9))
    ax = fig.add_subplot(111, projection="3d")
    ax.set_title(f"Prepared STL (symmetry = {SYMMETRY_MODE})")

    plot_mesh(ax, mesh)

    if SHOW_SYMMETRY_PLANE:
        plot_yz_plane(ax, mesh)

    set_axes_equal(ax, mesh.vertices)
    ax.view_init(elev=25, azim=35)
    plt.tight_layout()
    plt.show()

    spans = mesh.vertices.max(axis=0) - mesh.vertices.min(axis=0)
    print("XYZ spans:", spans)


if __name__ == "__main__":
    main()
