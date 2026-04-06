from typing import Dict, List, Tuple

from .models import GCodeSegment


class GCodeParser:
    """Fast G-code parser"""

    @staticmethod
    def parse_lines(lines: List[str]) -> Tuple[List[GCodeSegment], Dict]:
        segments = []
        state = {
            "x": 0.0, "y": 0.0, "z": 0.0,
            "a": 0.0, "b": 0.0, "c": 0.0,
            "absolute": True,
            "motion": "G1",
        }
        bounds = {"min": [float("inf")] * 6, "max": [float("-inf")] * 6}

        for line_num, raw in enumerate(lines, 1):
            line = raw.upper().strip()

            if "(" in line:
                line = line[:line.find("(")]
            if ";" in line:
                line = line[:line.find(";")]

            line = line.strip()
            if not line:
                continue

            words = line.split()
            old_state = state.copy()

            for w in words:
                if w == "G90":
                    state["absolute"] = True
                elif w == "G91":
                    state["absolute"] = False
                elif w in ("G0", "G00"):
                    state["motion"] = "G0"
                elif w in ("G1", "G01"):
                    state["motion"] = "G1"
                elif w in ("G2", "G02"):
                    state["motion"] = "G2"
                elif w in ("G3", "G03"):
                    state["motion"] = "G3"

            coords = {}
            for w in words:
                if len(w) < 2:
                    continue
                axis = w[0]
                if axis not in "XYZABC":
                    continue
                try:
                    coords[axis] = float(w[1:])
                except ValueError:
                    continue

            if coords:
                for axis in "XYZABC":
                    if axis in coords:
                        if state["absolute"]:
                            state[axis.lower()] = coords[axis]
                        else:
                            state[axis.lower()] += coords[axis]

                start = tuple(old_state[a] for a in "xyzabc")
                end = tuple(state[a] for a in "xyzabc")

                segments.append(
                    GCodeSegment(
                        start=start,
                        end=end,
                        motion_type=state["motion"],
                        line_num=line_num,
                    )
                )

                for i, (v_start, v_end) in enumerate(zip(start, end)):
                    bounds["min"][i] = min(bounds["min"][i], v_start, v_end)
                    bounds["max"][i] = max(bounds["max"][i], v_start, v_end)

        return segments, bounds