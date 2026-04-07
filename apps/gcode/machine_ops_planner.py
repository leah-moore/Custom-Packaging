"""
Machine operation planning layer.
Updated for grblHAL 6-Axis: X, Y, Z (See-saw), A (Rollers), B (Crease), C (Knife).
"""
import math
from typing import List, Dict
from apps.gcode.machine_ops_types import (
    Operation, RapidMove, ToolDown, ToolUp, CutPath, 
    FeedAdvance, PivotAction, SetLights, Point
)

# --- Hardware Constants ---
# These should ideally be imported from a central config.py
TOOL_Y_OFFSET = 45.0  # Distance between knife and wheel center
LIFT_THRESHOLD = 5.0  # Angle change (degrees) that triggers a Lift-to-Pivot

def get_heading(p1: Point, p2: Point) -> float:
    """Calculates angle in degrees for B/C pivot axes."""
    return math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))

def build_machine_ops_for_section(
    section_toolpaths: dict,
    y_offset: float,
    start_at: Point | None = None
) -> List[Operation]:
    ops: List[Operation] = []
    current_pos = start_at
    last_angle = 0.0

    # Process "crease" then "knife"
    for tool_type in ["crease", "knife"]:
        paths = section_toolpaths.get(tool_type, [])
        is_crease = (tool_type == "crease")
        
        # Tool-specific Y-offset correction
        off_y = TOOL_Y_OFFSET if is_crease else 0.0

        for path in paths:
            if not path: continue
            
            p1, p2 = path[0], path[1]
            p1_off = (p1[0], p1[1] + off_y)
            
            # 1. HEADING & PIVOT CHECK
            new_angle = get_heading(p1, p2)
            if abs(new_angle - last_angle) > LIFT_THRESHOLD:
                # Lift-to-Pivot Sequence
                ops.append(RapidMove(to=p1_off))
                ops.append(ToolUp())
                ops.append(PivotAction(tool=tool_type, angle=new_angle))
                last_angle = new_angle

            # 2. ENGAGE
            ops.append(RapidMove(to=p1_off))
            ops.append(ToolDown(tool=tool_type))
            
            # 3. APPLY OFFSET TO FULL PATH
            offset_path = [(pt[0], pt[1] + off_y) for pt in path]
            ops.append(CutPath(path=offset_path))
            
            # 4. RETRACT
            ops.append(ToolUp())
            current_pos = offset_path[-1]

    return ops

def build_machine_ops(toolpaths, sections):
    """
    Builds the master list of operations including Lights and Feed Roller moves.
    """
    all_ops: List[Operation] = []
    current_pos = None

    # 1. LIGHTS ON
    all_ops.append(SetLights(state=True))

    from extract_toolpaths import split_toolpaths_by_section
    per_section = split_toolpaths_by_section(toolpaths, sections)

    for s in sections:
        # 2. FEED ROLLERS (A-Axis)
        # s["y_min"] is where this section starts relative to the cardboard edge
        y_origin = s["y_min"]
        all_ops.append(FeedAdvance(distance=y_origin))

        section_ops = build_machine_ops_for_section(
            per_section[s["index"]],
            y_offset=y_origin,
            start_at=current_pos
        )
        
        all_ops.extend(section_ops)
        
        # Track last position to minimize travel moves
        if section_ops:
            for op in reversed(section_ops):
                if isinstance(op, CutPath):
                    current_pos = op.path[-1]
                    break

    # 3. LIGHTS OFF & PARK
    all_ops.append(SetLights(state=False))
    return all_ops