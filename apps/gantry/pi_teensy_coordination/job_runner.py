from apps.gcode.machine_ops_types import FeedAdvance
from apps.gcode.emit_gcode import emit_gcode


class JobRunner:
    def __init__(
        self,
        teensy,
        rollers,
        roller_speed_mm_s=10.0,
        log_fn=None,
        progress_fn=None,
    ):
        self.teensy = teensy
        self.rollers = rollers
        self.roller_speed_mm_s = roller_speed_mm_s
        self.log_fn = log_fn
        self.progress_fn = progress_fn

        self.stop_requested = False

    def _log(self, msg: str):
        if self.log_fn is not None:
            self.log_fn(msg)
        else:
            print(msg)

    def _progress(self, current: int, total: int, label: str = ""):
        if self.progress_fn is not None:
            self.progress_fn(current, total, label)

    def request_stop(self):
        self.stop_requested = True

    def run(self, ops):
        self.stop_requested = False
        gcode_buffer = []
        total_ops = len(ops)

        def flush_gcode():
            nonlocal gcode_buffer

            if self.stop_requested:
                return

            if not gcode_buffer:
                return

            gcode = emit_gcode(gcode_buffer)
            lines = [line.strip() for line in gcode.splitlines() if line.strip()]

            if not lines:
                gcode_buffer = []
                return

            self._log(f"[JOB] Streaming {len(lines)} G-code lines")
            self.teensy.stream(lines)
            gcode_buffer = []

        for i, op in enumerate(ops, start=1):
            if self.stop_requested:
                self._log("[JOB] Stop requested")
                break

            self._progress(i, total_ops, type(op).__name__)

            if isinstance(op, FeedAdvance):
                flush_gcode()

                forward = getattr(op, "forward", True)
                distance = getattr(op, "distance", 0.0)

                self._log(
                    f"[JOB] Feeding rollers: {distance} mm "
                    f"({'forward' if forward else 'reverse'})"
                )

                self.rollers.feed_distance(
                    distance_mm=distance,
                    speed_mm_s=self.roller_speed_mm_s,
                    forward=forward,
                )
            else:
                gcode_buffer.append(op)

        flush_gcode()
        self._log("[JOB] Done")