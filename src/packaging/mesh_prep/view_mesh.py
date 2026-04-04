import os
import open3d as o3d

# 👇 PUT YOUR FILE NAME OR PATH HERE
path = "data/stl/input/Asymmetrical/mouse.stl"

# ----------------------------

if not os.path.isfile(path):
    raise SystemExit(f"File not found: {path}")

ext = os.path.splitext(path)[1].lower()
if ext not in [".stl", ".obj"]:
    raise SystemExit("Only .stl and .obj files are supported")

# Load mesh
mesh = o3d.io.read_triangle_mesh(path)
if mesh.is_empty():
    raise SystemExit("Failed to load mesh")

# Improve appearance
mesh.compute_vertex_normals()
mesh.translate(-mesh.get_center())

# Coordinate axes (Open3D standard colors)
axes = o3d.geometry.TriangleMesh.create_coordinate_frame(
    size=2,   # make axes clearly visible
    origin=[0, 0, 0]
)

# ---- Console legend ----
print("\nAxis Legend:")
print("  X axis → RED")
print("  Y axis → GREEN")
print("  Z axis → BLUE\n")

o3d.visualization.draw_geometries(
    [mesh, axes],
    window_name=f"3D Viewer - {os.path.basename(path)}",
    width=1000,
    height=800,
    mesh_show_back_face=True
)
