"""
Machine operation planning layer.
Updated for grblHAL 6-Axis:
X, Y = gantry
Z = shared see-saw tool actuator
A = rollers
B/C = tangential pivot axes (confirm final mapping elsewhere)
"""
import math
from typing import List
from apps.gcode.machine_ops_types import (
    Operation, RapidMove, ToolDown, ToolUp, CutPath,
    FeedAdvance, PivotAction, SetLights, Point
)

# --- Hardware Constants ---
# Replace with measured values once calibrated.
CREASE_OFFSET_X = 0.0   # mm, creaser center relative to knife center
CREASE_OFFSET_Y = 0.0   # confirmed zero for your machine

LIFT_THRESHOLD = 5.0    # degrees; trigger lift-to-pivot above this


def get_heading(p1: Point, p2: Point) -> float:
    """Calculate path heading in degrees for tangential pivoting."""
    return math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))


def apply_tool_offset(path: list[Point], tool_type: str) -> list[Point]:
    """
    Shift design-space path to the actual machine path for the chosen tool.

    Knife is the reference tool center.
    Crease gets the measured tool-center offset.
    """
    if tool_type == "crease":
        off_x = CREASE_OFFSET_X
        off_y = CREASE_OFFSET_Y
    else:
        off_x = 0.0
        off_y = 0.0

    return [(x + off_x, y + off_y) for x, y in path]


def build_machine_ops_for_section(
    section_toolpaths: dict,
    y_offset: float,
    start_at: Point | None = None,
) -> List[Operation]:
    ops: List[Operation] = []
    current_pos = start_at
    last_angle = 0.0

    # Process crease first, then knife
    for tool_type in ["crease", "knife"]:
        paths = section_toolpaths.get(tool_type, [])

        for path in paths:
            if len(path) < 2:
                continue

            machine_path = apply_tool_offset(path, tool_type)

            p1 = machine_path[0]
            p2 = machine_path[1]

            # 1. Heading / dry pivot check
            new_angle = get_heading(p1, p2)
            if abs(new_angle - last_angle) > LIFT_THRESHOLD:
                ops.append(RapidMove(to=p1))
                ops.append(ToolUp())
                ops.append(PivotAction(tool=tool_type, angle=new_angle))
                last_angle = new_angle

            # 2. Move to start and engage tool
            if current_pos != p1:
                ops.append(RapidMove(to=p1))
            ops.append(ToolDown(tool=tool_type))

            # 3. Cut / crease path
            ops.append(CutPath(path=machine_path))

            # 4. Retract
            ops.append(ToolUp())
            current_pos = machine_path[-1]

    return ops


def build_machine_ops(toolpaths, sections):
    """
    Build the master operation list including lights and roller feed moves.
    """
    all_ops: List[Operation] = []
    current_pos = None

    all_ops.append(SetLights(state=True))

    from extract_toolpaths import split_toolpaths_by_section
    per_section = split_toolpaths_by_section(toolpaths, sections)

    last_y_origin = 0.0

    for s in sections:
        # Feed only by the delta to this section, not the absolute origin each time.
        y_origin = s["y_min"]
        feed_delta = y_origin - last_y_origin
        if abs(feed_delta) > 1e-9:
            all_ops.append(FeedAdvance(distance=feed_delta))
        last_y_origin = y_origin

        section_ops = build_machine_ops_for_section(
            per_section[s["index"]],
            y_offset=y_origin,
            start_at=current_pos,
        )
        all_ops.extend(section_ops)

        for op in reversed(section_ops):
            if isinstance(op, CutPath):
                current_pos = op.path[-1]
                break

    all_ops.append(SetLights(state=False))
    return all_ops