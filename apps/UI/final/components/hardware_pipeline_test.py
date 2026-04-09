#!/usr/bin/env python3

from apps.gcode.machine_ops_types import *
from apps.gcode.emit_gcode import emit_gcode
from apps.gcode.machine_validator import validate_operations
from apps.gcode.visualize_ops import visualize_operations

from teensy_controller import TeensyController
from roller_controller import RollerController
from job_runner import JobRunner


def build_test_ops():
    ops = []

    # --- LIGHTS ON ---
    ops.append(SetLights(state=True))

    # --- SMALL KNIFE SQUARE ---
    square = [
        (0, 0),
        (40, 0),
        (40, 40),
        (0, 40),
        (0, 0),
    ]

    ops.append(RapidMove(to=square[0]))
    ops.append(PivotAction(tool="knife", angle=0))
    ops.append(ToolDown(tool="knife"))
    ops.append(CutPath(path=square))
    ops.append(ToolUp())

    # --- ROLLER FEED ---
    ops.append(FeedAdvance(distance=20.0))

    # --- CREASE LINE ---
    crease_line = [(0, 60), (40, 60)]

    ops.append(RapidMove(to=crease_line[0]))
    ops.append(PivotAction(tool="crease", angle=0))
    ops.append(ToolDown(tool="crease"))
    ops.append(CutPath(path=crease_line))
    ops.append(ToolUp())

    # --- DONE ---
    ops.append(SetLights(state=False))

    return ops


def main():
    print("\n=== BUILD OPS ===")
    ops = build_test_ops()

    print("Ops count:", len(ops))

    print("\n=== VALIDATE ===")
    validate_operations(ops)

    print("\n=== VISUALIZE ===")
    visualize_operations(ops)

    print("\n=== GENERATE GCODE ===")
    gcode = emit_gcode(ops)
    print(gcode[:500], "\n...")

    print("\n=== CONNECT HARDWARE ===")
    teensy = TeensyController(port="/dev/cu.debug-console", baudrate=115200)
    rollers = RollerController()

    teensy.connect()

    runner = JobRunner(
        teensy=teensy,
        rollers=rollers,
        roller_speed_mm_s=10.0,
    )

    print("\n=== RUN JOB ===")
    runner.run(ops)

    print("\n=== DONE ===")
    teensy.disconnect()
    rollers.cleanup()


if __name__ == "__main__":
    main()