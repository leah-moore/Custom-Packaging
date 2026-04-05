from gcode.machine_ops_types import FeedAdvance
from gcode.emit_gcode import emit_gcode


class JobRunner:
    def __init__(self, teensy, rollers, roller_speed_mm_s=10.0):
        self.teensy = teensy
        self.rollers = rollers
        self.roller_speed_mm_s = roller_speed_mm_s

    def run(self, ops):
        gcode_buffer = []

        def flush_gcode():
            nonlocal gcode_buffer
            if not gcode_buffer:
                return

            gcode = emit_gcode(gcode_buffer)
            lines = [line for line in gcode.splitlines() if line.strip()]
            self.teensy.stream(lines)
            gcode_buffer = []

        for op in ops:
            if isinstance(op, FeedAdvance):
                flush_gcode()
                print(f"[JOB] Feeding rollers: {op.distance} mm")
                self.rollers.feed_distance(
                    distance_mm=op.distance,
                    speed_mm_s=self.roller_speed_mm_s,
                    forward=True,
                )
            else:
                gcode_buffer.append(op)

        flush_gcode()