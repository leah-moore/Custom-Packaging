from pathlib import Path
import argparse
import tempfile
import sys

import cadquery as cq
import trimesh


def scene_to_mesh(scene: trimesh.Scene) -> trimesh.Trimesh:
    """Flatten a trimesh.Scene into a single Trimesh."""
    meshes = []

    for geom in scene.geometry.values():
        if isinstance(geom, trimesh.Trimesh):
            meshes.append(geom)

    if not meshes:
        raise ValueError("Scene did not contain any mesh geometry.")

    if len(meshes) == 1:
        return meshes[0]

    return trimesh.util.concatenate(meshes)


def load_mesh_any(path: Path) -> trimesh.Trimesh:
    """Load STL/OBJ and normalize Scene -> Trimesh."""
    mesh = trimesh.load_mesh(path, process=False)

    if isinstance(mesh, trimesh.Scene):
        mesh = scene_to_mesh(mesh)

    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(f"Loaded object is not a Trimesh: {type(mesh)}")

    return mesh


def convert_step_to_stl_or_obj(
    input_path: Path,
    output_path: Path,
    linear_tolerance: float = 0.1,
    angular_tolerance: float = 0.1,
) -> None:
    """
    Convert STEP -> STL or OBJ.

    Strategy:
    1. Import STEP with CadQuery
    2. Export temporary STL from CAD geometry
    3. If final output is STL, move/copy that result
    4. If final output is OBJ, load temp STL with trimesh and export OBJ
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if input_path.suffix.lower() not in {".stp", ".step"}:
        raise ValueError("Input file must be .stp or .step")

    out_ext = output_path.suffix.lower()
    if out_ext not in {".stl", ".obj"}:
        raise ValueError("Output file must end in .stl or .obj")

    print(f"Importing STEP: {input_path}")
    model = cq.importers.importStep(str(input_path))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_stl = Path(tmpdir) / f"{input_path.stem}.stl"

        print("Tessellating CAD and exporting temporary STL...")
        cq.exporters.export(
            model,
            str(tmp_stl),
            exportType="STL",
            tolerance=linear_tolerance,
            angularTolerance=angular_tolerance,
        )

        if out_ext == ".stl":
            output_path.write_bytes(tmp_stl.read_bytes())
            print(f"Saved STL: {output_path}")
            return

        print("Loading temporary STL and exporting OBJ...")
        mesh = load_mesh_any(tmp_stl)
        mesh.export(output_path)
        print(f"Saved OBJ: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert STEP/STP files to STL or OBJ."
    )
    parser.add_argument("input", help="Path to input .step or .stp file")
    parser.add_argument("output", help="Path to output .stl or .obj file")
    parser.add_argument(
        "--tol",
        type=float,
        default=0.1,
        help="Linear tessellation tolerance (smaller = finer mesh, default: 0.1)",
    )
    parser.add_argument(
        "--ang",
        type=float,
        default=0.1,
        help="Angular tessellation tolerance (default: 0.1)",
    )

    args = parser.parse_args()

    try:
        convert_step_to_stl_or_obj(
            input_path=Path(args.input),
            output_path=Path(args.output),
            linear_tolerance=args.tol,
            angular_tolerance=args.ang,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()