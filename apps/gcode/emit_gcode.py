import math
from dataclasses import is_dataclass
from apps.gcode.machine_ops_types import (
    RapidMove, ToolDown, ToolUp, CutPath, FeedAdvance, PivotAction
)

# -------------------------------------------------
# Config
# -------------------------------------------------

SAFE_Z   = 10.0      # Neutral: both tools retracted
Z_KNIFE  = 0.0       # Knife side down
Z_CREASE = 3.0       # Crease side down

FEED_Z         = 1000
FEED_XY_KNIFE  = 3000   # XY cutting feed for knife moves
FEED_B_KNIFE   = 2000   # B-axis pivot/angle feed for knife moves
FEED_CREASE    = 300
FEED_ROLLERS   = 200
OSC_SPEED      = 2000

# Lift and rotate in air if segment-to-segment turn exceeds this.
# Keep this nonzero for real jobs so curves do not constantly lift.
LIFT_TURN_THRESHOLD = 10.0

# -------------------------------------------------
# Swivel Axis Calibration
# -------------------------------------------------

KNIFE_ANGLE_OFFSET = 0.0
CREASE_ANGLE_OFFSET = 0.0

KNIFE_SIGN = -1.0
CREASE_SIGN = 1.0

# Explicit startup assumption:
# 0.0   = tool faces +X
# 180.0 = tool faces -X
INITIAL_KNIFE_HEADING_DEG = 0.0
INITIAL_CREASE_HEADING_DEG = 0.0

# -------------------------------------------------
# Knife Geometry Compensation
# -------------------------------------------------
# Tool-local tip position relative to the swivel/pivot center when
# heading = 0 deg and the blade faces +X.
#
# For your current case:
# - tip trails pivot by ~1 mm
# - no lateral offset
#
# So the local vector from pivot -> tip is (-1, 0).
KNIFE_TIP_LOCAL_X = 0.0
KNIFE_TIP_LOCAL_Y = 0.0

# Disable entry slit while calibrating the real geometric correction.
KNIFE_ENTRY_SLIT_MM = 0.0


def knife_angle_to_axis(angle_deg):
    return (angle_deg + KNIFE_ANGLE_OFFSET) * KNIFE_SIGN


def crease_angle_to_axis(angle_deg):
    return (angle_deg + CREASE_ANGLE_OFFSET) * CREASE_SIGN


# -------------------------------------------------
# Geometry helpers
# -------------------------------------------------

def get_angle(p1, p2):
    """Path heading in degrees."""
    return math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))


def angle_diff_deg(a, b):
    """Smallest signed difference a-b in degrees, normalized to [-180, 180]."""
    diff = a - b
    while diff > 180.0:
        diff -= 360.0
    while diff < -180.0:
        diff += 360.0
    return diff


def unwrap_angle_deg(angle, prev_unwrapped):
    """Keep angle continuous relative to previous emitted angle."""
    if prev_unwrapped is None:
        return angle

    while angle - prev_unwrapped > 180.0:
        angle -= 360.0
    while angle - prev_unwrapped < -180.0:
        angle += 360.0

    return angle


def segment_length(p1, p2):
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def move_along_heading(x, y, angle_deg, distance_mm):
    """Move a world-space point along the current heading by distance_mm."""
    a = math.radians(angle_deg)
    return (
        x + distance_mm * math.cos(a),
        y + distance_mm * math.sin(a),
    )


def offset_tip_to_pivot(x_tip, y_tip, angle_deg, tip_local_x, tip_local_y):
    """
    Convert desired knife-tip XY to swivel-center XY using a tool-local offset.

    tip_local_x, tip_local_y:
      vector from pivot center -> knife tip
      in tool coordinates when angle_deg = 0 and blade faces +X.
    """
    a = math.radians(angle_deg)
    ca = math.cos(a)
    sa = math.sin(a)

    # Rotate local pivot->tip vector into world space
    dx = tip_local_x * ca - tip_local_y * sa
    dy = tip_local_x * sa + tip_local_y * ca

    # Machine commands the pivot center, not the tip
    x_pivot = x_tip - dx
    y_pivot = y_tip - dy
    return x_pivot, y_pivot


def machine_xy_for_tool(x, y, angle_deg, tool):
    """
    Convert desired tool-contact XY to commanded machine XY.

    For knife cuts, op.path is treated as the desired knife-tip path.
    The emitted XY is the swivel-center position required to place the
    blade tip at that path point for the given heading.
    """
    if tool == "knife":
        return offset_tip_to_pivot(
            x, y, angle_deg,
            KNIFE_TIP_LOCAL_X,
            KNIFE_TIP_LOCAL_Y
        )
    return x, y


def emit_entry_slit_if_needed(lines, current_tool, axis, axis_val, feed, y_offset,
                              angle, start_tip_pt, end_tip_pt):
    """
    For knife restarts, after plunge, optionally emit a short entry move
    along the current heading.

    Disabled for calibration when KNIFE_ENTRY_SLIT_MM = 0.0.
    """
    if current_tool != "knife":
        return start_tip_pt

    seg_len = segment_length(start_tip_pt, end_tip_pt)
    if seg_len <= 1e-9:
        return start_tip_pt

    entry_len = min(KNIFE_ENTRY_SLIT_MM, seg_len)
    if entry_len <= 1e-9:
        return start_tip_pt

    entry_tip_x, entry_tip_y = move_along_heading(
        start_tip_pt[0], start_tip_pt[1], angle, entry_len
    )
    entry_x, entry_y = machine_xy_for_tool(
        entry_tip_x, entry_tip_y, angle, current_tool
    )

    lines.append(
        f"G1 X{entry_x:.3f} "
        f"Y{entry_y - y_offset:.3f} "
        f"{axis}{axis_val:.2f} F{feed}"
    )

    return (entry_tip_x, entry_tip_y)


# -------------------------------------------------
# Main emitter
# -------------------------------------------------

def emit_gcode(ops, feed_window_y=200.0):
    if not ops:
        raise RuntimeError("emit_gcode() called with empty ops list")

    if not all(is_dataclass(op) for op in ops):
        raise TypeError("emit_gcode() expects a list of Operation objects")

    lines = []

    # --- header ---
    lines.append("(Generated by custom-packaging - grblHAL Multi-Axis)")
    lines.append("M8 (Lights ON)\n")
    lines.append("G21  (mm)")
    lines.append("G90  (absolute)")

    current_tool = None
    y_offset = 0.0
    osc_on = False
    last_emitted_angle = None  # continuous logical knife/crease angle

    # Only initialize swivel axes that are actually used in this job
    uses_knife = any(getattr(op, "tool", None) == "knife" for op in ops)
    uses_crease = any(getattr(op, "tool", None) == "crease" for op in ops)

    lines.append(f"G1 Z{SAFE_Z:.3f} F{FEED_Z}")

    if uses_knife:
        init_knife_axis = knife_angle_to_axis(INITIAL_KNIFE_HEADING_DEG)
        lines.append(f"G1 B{init_knife_axis:.2f} F{FEED_B_KNIFE}")

    if uses_crease:
        init_crease_axis = crease_angle_to_axis(INITIAL_CREASE_HEADING_DEG)
        lines.append(f"G1 C{init_crease_axis:.2f} F{FEED_CREASE}")

    for op in ops:

        # ------------------
        # RAPID MOVE
        # Always lift before any XY travel
        # ------------------
        if isinstance(op, RapidMove):
            lines.append(f"G1 Z{SAFE_Z:.3f} F{FEED_Z}")
            x, y = op.to
            ym = y - y_offset
            lines.append(f"G0 X{x:.3f} Y{ym:.3f}")

        # ------------------
        # FEED ADVANCE
        # ------------------
        elif isinstance(op, FeedAdvance):
            raise RuntimeError(
                "FeedAdvance must be executed by RollerController, not emitted as G-code"
            )

        # ------------------
        # PIVOT IN AIR
        # ------------------
        elif isinstance(op, PivotAction):
            unwrapped = unwrap_angle_deg(op.angle, last_emitted_angle)
            last_emitted_angle = unwrapped

            if op.tool == "knife":
                axis_val = knife_angle_to_axis(unwrapped)
                lines.append(f"G1 Z{SAFE_Z:.3f} F{FEED_Z}")
                lines.append(f"G1 B{axis_val:.2f} F{FEED_B_KNIFE}")
            elif op.tool == "crease":
                axis_val = crease_angle_to_axis(unwrapped)
                lines.append(f"G1 Z{SAFE_Z:.3f} F{FEED_Z}")
                lines.append(f"G1 C{axis_val:.2f} F{FEED_CREASE}")
            else:
                raise RuntimeError(f"Unknown tool type: {op.tool}")

        # ------------------
        # TOOL DOWN
        # Arm the tool only. Do not plunge here.
        # CutPath owns: pre-rotate -> XY set -> plunge -> cut.
        # ------------------
        elif isinstance(op, ToolDown):
            current_tool = op.tool

            if current_tool == "knife":
                if not osc_on:
                    lines.append(f"M3 S{OSC_SPEED} (Start Oscillation)")
                    osc_on = True

            elif current_tool == "crease":
                if osc_on:
                    lines.append("M5 (Stop Oscillation)")
                    osc_on = False

            else:
                raise RuntimeError(f"Unknown tool type: {current_tool}")

        # ------------------
        # CUT PATH
        # ------------------
        elif isinstance(op, CutPath):
            if current_tool is None:
                raise RuntimeError("CutPath encountered with no active tool")

            if len(op.path) < 2:
                raise RuntimeError("CutPath must contain at least 2 points")

            feed = FEED_XY_KNIFE if current_tool == "knife" else FEED_CREASE
            axis = "B" if current_tool == "knife" else "C"
            cut_z = Z_KNIFE if current_tool == "knife" else Z_CREASE
            axis_feed = FEED_B_KNIFE if current_tool == "knife" else FEED_CREASE

            # --- PRE-ROTATE TO FIRST SEGMENT HEADING BEFORE CUTTING ---
            first_raw_angle = get_angle(op.path[0], op.path[1])
            first_angle = unwrap_angle_deg(first_raw_angle, last_emitted_angle)

            if current_tool == "knife":
                first_axis_val = knife_angle_to_axis(first_angle)
            else:
                first_axis_val = crease_angle_to_axis(first_angle)

            start_x, start_y = machine_xy_for_tool(
                op.path[0][0],
                op.path[0][1],
                first_angle,
                current_tool
            )

            # Rotate in air, move XY to compensated start, then plunge
            lines.append(f"G1 Z{SAFE_Z:.3f} F{FEED_Z}")
            lines.append(f"G1 {axis}{first_axis_val:.2f} F{axis_feed}")
            lines.append(f"G0 X{start_x:.3f} Y{start_y - y_offset:.3f}")
            lines.append(f"G1 Z{cut_z:.3f} F{FEED_Z}")

            # Optional initial entry slit for knife
            start_tip_pt = (op.path[0][0], op.path[0][1])
            first_end_tip_pt = (op.path[1][0], op.path[1][1])
            current_tip_pt = emit_entry_slit_if_needed(
                lines=lines,
                current_tool=current_tool,
                axis=axis,
                axis_val=first_axis_val,
                feed=feed,
                y_offset=y_offset,
                angle=first_angle,
                start_tip_pt=start_tip_pt,
                end_tip_pt=first_end_tip_pt,
            )

            last_segment_angle = None
            last_emitted_angle = first_angle

            for i in range(len(op.path) - 1):
                p1, p2 = op.path[i], op.path[i + 1]
                raw_angle = get_angle(p1, p2)
                angle = unwrap_angle_deg(raw_angle, last_emitted_angle)

                if current_tool == "knife":
                    axis_val = knife_angle_to_axis(angle)
                else:
                    axis_val = crease_angle_to_axis(angle)

                seg_start_tip = p1

                # For the first segment, continue from any optional entry move
                if i == 0:
                    seg_start_tip = current_tip_pt

                # Lift-to-turn for sharp corners only
                if last_segment_angle is not None:
                    turn = angle_diff_deg(raw_angle, last_segment_angle)
                    if abs(turn) > LIFT_TURN_THRESHOLD:
                        # Ensure previous segment ended exactly at its endpoint
                        prev_angle = last_emitted_angle
                        if current_tool == "knife":
                            prev_axis_val = knife_angle_to_axis(prev_angle)
                        else:
                            prev_axis_val = crease_angle_to_axis(prev_angle)

                        end_prev_x, end_prev_y = machine_xy_for_tool(
                            p1[0], p1[1], prev_angle, current_tool
                        )
                        lines.append(
                            f"G1 X{end_prev_x:.3f} "
                            f"Y{end_prev_y - y_offset:.3f} "
                            f"{axis}{prev_axis_val:.2f} F{feed}"
                        )

                        # Lift, rotate, reposition to the same desired tip point
                        # using the NEW heading compensation, then plunge.
                        lines.append(f"G1 Z{SAFE_Z:.3f} F{FEED_Z}")
                        lines.append(f"G1 {axis}{axis_val:.2f} F{axis_feed}")

                        corner_x, corner_y = machine_xy_for_tool(
                            p1[0], p1[1], angle, current_tool
                        )
                        lines.append(f"G0 X{corner_x:.3f} Y{corner_y - y_offset:.3f}")
                        lines.append(f"G1 Z{cut_z:.3f} F{FEED_Z}")

                        seg_start_tip = emit_entry_slit_if_needed(
                            lines=lines,
                            current_tool=current_tool,
                            axis=axis,
                            axis_val=axis_val,
                            feed=feed,
                            y_offset=y_offset,
                            angle=angle,
                            start_tip_pt=p1,
                            end_tip_pt=p2,
                        )

                # Final move for this segment
                if segment_length(seg_start_tip, p2) > 1e-9:
                    x_cmd, y_cmd = machine_xy_for_tool(
                        p2[0], p2[1], angle, current_tool
                    )
                    ym = y_cmd - y_offset

                    lines.append(
                        f"G1 X{x_cmd:.3f} "
                        f"Y{ym:.3f} "
                        f"{axis}{axis_val:.2f} F{feed}"
                    )

                last_segment_angle = raw_angle
                last_emitted_angle = angle

        # ------------------
        # TOOL UP
        # ------------------
        elif isinstance(op, ToolUp):
            lines.append(f"G1 Z{SAFE_Z:.3f} F{FEED_Z}")
            current_tool = None

        else:
            raise RuntimeError(f"Unknown operation type: {type(op)}")

    # --- footer ---
    if osc_on:
        lines.append("M5 (Stop Oscillation)")

    lines.append("M9 (Lights OFF)\n")
    lines.append("M2")

    return "\n".join(lines)