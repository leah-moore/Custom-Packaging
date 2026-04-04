# src/packaging/mesh_prep/seal.py

import numpy as np
import trimesh


def seal_endpoints(
    mesh: trimesh.Trimesh,
    *,
    top_frac: float = 0.30,
    z_tol: float = 1e-3
) -> trimesh.Trimesh:
    """
    Visually seal the TOP opening of a mesh by capping near max-Z.

    - DOES NOT rely on boundary edges
    - DOES NOT care about watertightness
    - Uses existing rim vertices only
    - Ignores all interior geometry
    - MATLAB-equivalent behavior

    Parameters
    ----------
    top_frac : float
        Fraction of total height to search for rim vertices near the top.
        Increase (0.3–0.5) for pitchers / teapots with spouts.
    z_tol : float
        Absolute tolerance added on top of the band (safety).

    Returns
    -------
    trimesh.Trimesh
        Mesh with a flat cap added at the top.
    """

    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError("seal_endpoints expects a trimesh.Trimesh")

    mesh = mesh.copy()
    V = mesh.vertices
    F = mesh.faces

    z_min = V[:, 2].min()
    z_max = V[:, 2].max()
    z_band = z_max - top_frac * (z_max - z_min)

    # --------------------------------------------------
    # 1) Collect rim vertices near the top
    # --------------------------------------------------
    rim_mask = V[:, 2] >= (z_band - z_tol)
    rim = V[rim_mask]

    if rim.shape[0] < 3:
        print("[seal] No rim vertices found — skipping cap")
        return mesh

    # --------------------------------------------------
    # 2) Project rim to XY and order by angle
    # --------------------------------------------------
    rim_xy = rim[:, :2]
    center_xy = rim_xy.mean(axis=0)

    angles = np.arctan2(
        rim_xy[:, 1] - center_xy[1],
        rim_xy[:, 0] - center_xy[0],
    )
    order = np.argsort(angles)
    rim_xy = rim_xy[order]

    # --------------------------------------------------
    # 3) Build cap vertices
    # --------------------------------------------------
    z_cap = z_max
    cap_center = np.array([center_xy[0], center_xy[1], z_cap])
    cap_ring = np.column_stack([
        rim_xy,
        np.full(len(rim_xy), z_cap),
    ])

    cap_vertices = np.vstack([cap_center, cap_ring])
    center_idx = len(V)
    ring_idx = np.arange(len(rim_xy)) + center_idx + 1

    # --------------------------------------------------
    # 4) Fan triangulation
    # --------------------------------------------------
    faces = []
    for i in range(len(ring_idx)):
        i0 = ring_idx[i]
        i1 = ring_idx[(i + 1) % len(ring_idx)]
        faces.append([center_idx, i0, i1])

    faces = np.asarray(faces, dtype=np.int64)

    # --------------------------------------------------
    # 5) Merge and return
    # --------------------------------------------------
    V_new = np.vstack([V, cap_vertices])
    F_new = np.vstack([F, faces])

    sealed = trimesh.Trimesh(
        vertices=V_new,
        faces=F_new,
        process=False,
    )

    return sealed
