from typing import Dict, List, Tuple
import math

from .models import GCodeSegment


class GCodeParser:
    """Feed-aware G-code parser for preview playback."""

    RAPID_FEED_MM_MIN = 3000.0  # preview-only assumption for G0 timing

    @staticmethod
    def _strip_comments(line: str) -> str:
        line = line.upper().strip()

        if "(" in line:
            line = line[:line.find("(")]
        if ";" in line:
            line = line[:line.find(";")]

        return line.strip()

    @staticmethod
    def _parse_words(line: str) -> List[str]:
        return [w for w in line.split() if w]

    @staticmethod
    def _safe_float(text: str):
        try:
            return float(text)
        except Exception:
            return None

    @staticmethod
    def _update_bounds(bounds: Dict, start: Tuple[float, ...], end: Tuple[float, ...]) -> None:
        for i, (v_start, v_end) in enumerate(zip(start, end)):
            bounds["min"][i] = min(bounds["min"][i], v_start, v_end)
            bounds["max"][i] = max(bounds["max"][i], v_start, v_end)

    @staticmethod
    def _linear_distance_xyz(start: Tuple[float, ...], end: Tuple[float, ...]) -> float:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dz = end[2] - start[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    @staticmethod
    def _arc_center_from_ij(start_x: float, start_y: float, i_val: float, j_val: float) -> Tuple[float, float]:
        return start_x + i_val, start_y + j_val

    @staticmethod
    def _arc_sweep(start_ang: float, end_ang: float, motion: str) -> float:
        if motion == "G2":  # CW
            sweep = start_ang - end_ang
            if sweep <= 0:
                sweep += 2.0 * math.pi
        else:  # G3 / CCW
            sweep = end_ang - start_ang
            if sweep <= 0:
                sweep += 2.0 * math.pi
        return sweep

    @staticmethod
    def _arc_length_xy(
        start: Tuple[float, ...],
        end: Tuple[float, ...],
        motion: str,
        i_val: float,
        j_val: float,
    ) -> float:
        sx, sy = start[0], start[1]
        ex, ey = end[0], end[1]

        cx, cy = GCodeParser._arc_center_from_ij(sx, sy, i_val, j_val)

        rs = math.hypot(sx - cx, sy - cy)
        re = math.hypot(ex - cx, ey - cy)
        radius = (rs + re) / 2.0

        if radius <= 1e-9:
            return 0.0

        start_ang = math.atan2(sy - cy, sx - cx)
        end_ang = math.atan2(ey - cy, ex - cx)
        sweep = GCodeParser._arc_sweep(start_ang, end_ang, motion)

        arc_len_xy = radius * sweep
        dz = end[2] - start[2]

        # Helical approximation
        return math.sqrt(arc_len_xy * arc_len_xy + dz * dz)

    @staticmethod
    def _duration_from_distance(distance_mm: float, feed_mm_min: float) -> float:
        if distance_mm <= 0:
            return 0.0
        effective_feed = max(feed_mm_min, 0.001)
        return (distance_mm / effective_feed) * 60.0

    @staticmethod
    def parse_lines(lines: List[str]) -> Tuple[List[GCodeSegment], Dict]:
        segments: List[GCodeSegment] = []

        state = {
            "x": 0.0, "y": 0.0, "z": 0.0,
            "a": 0.0, "b": 0.0, "c": 0.0,
            "absolute": True,
            "motion": "G1",
            "feed": 1000.0,
            "spindle_on": False,
            "spindle_speed": 0.0,
        }

        bounds = {"min": [float("inf")] * 6, "max": [float("-inf")] * 6}
        total_time_s = 0.0

        for line_num, raw in enumerate(lines, 1):
            line = GCodeParser._strip_comments(raw)
            if not line:
                continue

            words = GCodeParser._parse_words(line)
            if not words:
                continue

            old_state = state.copy()

            # Modal updates
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
                elif w.startswith("F"):
                    val = GCodeParser._safe_float(w[1:])
                    if val is not None:
                        state["feed"] = max(val, 0.001)
                elif w.startswith("S"):
                    val = GCodeParser._safe_float(w[1:])
                    if val is not None:
                        state["spindle_speed"] = val
                elif w in ("M3", "M03", "M4", "M04"):
                    state["spindle_on"] = True
                elif w in ("M5", "M05"):
                    state["spindle_on"] = False

            # Dwell: G4 P(seconds) or G4 X(seconds)
            if any(w in ("G4", "G04") for w in words):
                dwell_s = 0.0
                for w in words:
                    if len(w) < 2:
                        continue
                    if w[0] in ("P", "X"):
                        val = GCodeParser._safe_float(w[1:])
                        if val is not None:
                            dwell_s = max(val, 0.0)
                            break

                start = tuple(old_state[a] for a in "xyzabc")
                end = start

                segments.append(
                    GCodeSegment(
                        start=start,
                        end=end,
                        motion_type="G4",
                        line_num=line_num,
                        feed_rate=state["feed"],
                        spindle_on=state["spindle_on"],
                        spindle_speed=state["spindle_speed"],
                        distance_mm=0.0,
                        duration_s=dwell_s,
                        start_time_s=total_time_s,
                        end_time_s=total_time_s + dwell_s,
                        is_dwell=True,
                        dwell_s=dwell_s,
                    )
                )

                total_time_s += dwell_s
                GCodeParser._update_bounds(bounds, start, end)
                continue

            # Parse axis words
            coords = {}
            ijk = {}
            for w in words:
                if len(w) < 2:
                    continue
                letter = w[0]
                val = GCodeParser._safe_float(w[1:])
                if val is None:
                    continue

                if letter in "XYZABC":
                    coords[letter] = val
                elif letter in "IJK":
                    ijk[letter] = val

            if not coords:
                continue

            # Apply coordinates
            for axis in "XYZABC":
                if axis in coords:
                    if state["absolute"]:
                        state[axis.lower()] = coords[axis]
                    else:
                        state[axis.lower()] += coords[axis]

            start = tuple(old_state[a] for a in "xyzabc")
            end = tuple(state[a] for a in "xyzabc")

            motion = state["motion"]
            feed_rate = max(state["feed"], 0.001)

            if motion in ("G2", "G3") and ("I" in ijk or "J" in ijk):
                distance_mm = GCodeParser._arc_length_xy(
                    start=start,
                    end=end,
                    motion=motion,
                    i_val=ijk.get("I", 0.0),
                    j_val=ijk.get("J", 0.0),
                )
            else:
                distance_mm = GCodeParser._linear_distance_xyz(start, end)

            if motion == "G0":
                duration_s = GCodeParser._duration_from_distance(
                    distance_mm, GCodeParser.RAPID_FEED_MM_MIN
                )
                effective_feed = GCodeParser.RAPID_FEED_MM_MIN
            else:
                duration_s = GCodeParser._duration_from_distance(distance_mm, feed_rate)
                effective_feed = feed_rate

            segments.append(
                GCodeSegment(
                    start=start,
                    end=end,
                    motion_type=motion,
                    line_num=line_num,
                    feed_rate=effective_feed,
                    spindle_on=state["spindle_on"],
                    spindle_speed=state["spindle_speed"],
                    distance_mm=distance_mm,
                    duration_s=duration_s,
                    start_time_s=total_time_s,
                    end_time_s=total_time_s + duration_s,
                    is_dwell=False,
                    dwell_s=0.0,
                )
            )

            total_time_s += duration_s
            GCodeParser._update_bounds(bounds, start, end)

        if not segments:
            bounds = {"min": [0.0] * 6, "max": [0.0] * 6}

        bounds["total_time_s"] = total_time_s
        return segments, bounds