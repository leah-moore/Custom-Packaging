from dataclasses import dataclass
from typing import List, Tuple, Literal

# --- TYPE DEFINITIONS ---
Point = Tuple[float, float]

# Tool identifiers (LOGICAL only — not tied to axis letters here)
#
# Actual machine mapping (handled in emitter):
# - "crease" -> Axis A (creaser angle)
# - "knife"  -> Axis B (blade angle)
# - Z        -> shared see-saw actuator (selects which tool engages)
#
# IMPORTANT:
# Do NOT encode axis letters in this file — keep it logical.
ToolType = Literal["knife", "crease"]


@dataclass
class Operation:
    """Base class for all machine operations."""
    pass


@dataclass
class RapidMove(Operation):
    """
    Rapid XY move with tools disengaged.

    Requires Z to be in safe (neutral) position.
    """
    to: Point


@dataclass
class ToolDown(Operation):
    """
    Engage the specified tool via the shared see-saw Z actuator.

    - tool="knife"  -> blade down, creaser lifted
    - tool="crease" -> creaser down, blade lifted
    """
    tool: ToolType


@dataclass
class ToolUp(Operation):
    """
    Return Z to neutral so neither tool is engaged.
    """
    pass


@dataclass
class CutPath(Operation):
    """
    Sequence of XY points to follow with the active tool.

    The emitter is responsible for:
    - converting to machine coordinates
    - applying tool offsets
    - generating pivot axis motion (A/B)
    - managing Z state transitions
    """
    path: List[Point]


@dataclass
class FeedAdvance(Operation):
    """
    Advance cardboard using the roller system.

    NOTE:
    This is NOT a G-code axis move.
    It is executed by the RollerController (separate hardware).
    """
    distance: float


@dataclass
class PivotAction(Operation):
    """
    Rotate the tangential axis while tool is lifted.

    Logical mapping:
    - tool="crease" -> Axis A
    - tool="knife"  -> Axis B

    The emitter translates this into actual G-code.
    """
    tool: ToolType
    angle: float


@dataclass
class SetLights(Operation):
    """
    Control gantry lights (or flood coolant output).

    True  -> M8
    False -> M9
    """
    state: bool