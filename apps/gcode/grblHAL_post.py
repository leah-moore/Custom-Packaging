from typing import List
from dataclasses import dataclass

from gcode.machine_ops_types import (
    Operation,
    RapidMove,
    ToolDown,
    ToolUp,
    CutPath,
    FeedAdvance,
)

from gcode.machine_validator import validate_operations


# =================================================
# Machine configuration
# =================================================

@dataclass(frozen=True)
class MachineConfig:
    # ------------------------------
    # Z positions (if using Z plunge)
    # ------------------------------
    z_safe: float
    z_knife: float
    z_crease: float

    # ------------------------------
    # Feed rates
    # ------------------------------
    feed_xy: float
    feed_tool: float
    feed_roller: float

    # ------------------------------
    # Optional actuator commands
    # (leave "" if unused)
    # ------------------------------
    knife_on_cmd: str = ""
    knife_off_cmd: str = ""

    crease_on_cmd: str = ""
    crease_off_cmd: str = ""

    # ------------------------------
    # Roller advance command
    # ------------------------------
    def roller_advance_cmd(self, distance: float) -> str:
        # CHANGE this once real machine command is known
        # Example formats:
        # return f"M70 P{distance:.3f}"
        # return f"G1 B{distance:.3f} F{self.feed_roller}"
        return f"M70 P{distance:.3f}"


# =================================================
# GRBL-HAL Post Processor
# =================================================

class GRBLHALPostProcessor:

    def __init__(self, config: MachineConfig):
        self.cfg = config

    # =================================================
    # Main entry
    # =================================================

    def emit(self, ops: List[Operation]) -> str:
        validate_operations(ops)

        lines = []

        # ------------------------------
        # Program start / GRBL setup
        # ------------------------------
        lines += [
            "%",
            "G21",      # millimeters
            "G90",      # absolute positioning
            "G94",      # feed per minute
            "G17",      # XY plane
            "G54",      # work coordinate system
            "$H",       # home machine
            f"G0 Z{self.cfg.z_safe:.3f}",
        ]

        # ------------------------------
        # Emit operations
        # ------------------------------
        for op in ops:

            # ---------------------------------
            # Rapid move
            # ---------------------------------
            if isinstance(op, RapidMove):
                x, y = op.to
                lines.append(f"G0 X{x:.3f} Y{y:.3f}")

            # ---------------------------------
            # Tool down
            # ---------------------------------
            elif isinstance(op, ToolDown):

                if op.tool == "knife":
                    if self.cfg.knife_on_cmd:
                        lines.append(self.cfg.knife_on_cmd)
                    z = self.cfg.z_knife

                else:
                    if self.cfg.crease_on_cmd:
                        lines.append(self.cfg.crease_on_cmd)
                    z = self.cfg.z_crease

                lines.append(f"G1 Z{z:.3f} F{self.cfg.feed_tool:.1f}")

            # ---------------------------------
            # Tool up
            # ---------------------------------
            elif isinstance(op, ToolUp):
                lines.append(f"G1 Z{self.cfg.z_safe:.3f} F{self.cfg.feed_tool:.1f}")

                # stop actuators if defined
                if self.cfg.knife_off_cmd:
                    lines.append(self.cfg.knife_off_cmd)
                if self.cfg.crease_off_cmd:
                    lines.append(self.cfg.crease_off_cmd)

            # ---------------------------------
            # Cutting path
            # ---------------------------------
            elif isinstance(op, CutPath):
                for x, y in op.path:
                    lines.append(f"G1 X{x:.3f} Y{y:.3f} F{self.cfg.feed_xy:.1f}")

            # ---------------------------------
            # Roll feed advance
            # ---------------------------------
            elif isinstance(op, FeedAdvance):
                lines.append(self.cfg.roller_advance_cmd(op.distance))

        # ------------------------------
        # Program end
        # ------------------------------
        lines += [
            f"G0 Z{self.cfg.z_safe:.3f}",
            "M30",
        ]

        return "\n".join(lines) + "\n"
