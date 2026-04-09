from apps.gcode.machine_ops_types import FeedAdvance
from apps.gcode.emit_gcode import emit_gcode
import time

class JobRunner:
    def __init__(
        self,
        controller,  # Now using UnifiedGCodeController
        rollers,
        roller_speed_mm_s=10.0,
        log_fn=None,
        progress_fn=None,
    ):
        self.controller = controller
        self.rollers = rollers
        self.roller_speed_mm_s = roller_speed_mm_s
        self.log_fn = log_fn
        self.progress_fn = progress_fn
        self.stop_requested = False
        self.paused = False

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

    def request_pause(self):
        """Pause job (feed hold)."""
        self._log("[JOB] Pause requested")
        self.controller.send_realtime(b"!")  # Feed hold
        self.paused = True

    def request_resume(self):
        """Resume paused job."""
        self._log("[JOB] Resume requested")
        self.controller.send_realtime(b"~")  # Resume
        self.paused = False

    def run(self, ops, should_stop=None, should_pause=None, job_timeout_s=None):
        """Run job with integrated roller control + UI control + timeout."""
        self.stop_requested = False
        self.paused = False
        gcode_buffer = []
        total_ops = len(ops)
        start_time = time.time()

        def stop_now():
            return self.stop_requested or (callable(should_stop) and should_stop())

        def pause_now():
            return self.paused or (callable(should_pause) and should_pause())

        def abort_job(reason: str):
            self._log(reason)
            self.stop_requested = True
            try:
                self.controller.send_realtime(b"!")      # hold
                self.controller.send_realtime(b"\x18")   # reset
            except Exception:
                pass

        def check_timeout():
            if job_timeout_s is None:
                return
            elapsed = time.time() - start_time
            if elapsed > job_timeout_s:
                abort_job(f"[JOB] Timeout after {elapsed:.1f}s")
                raise TimeoutError("Job timeout")

        def flush_gcode():
            nonlocal gcode_buffer

            if stop_now():
                return

            if not gcode_buffer:
                return

            check_timeout()

            try:
                gcode = emit_gcode(gcode_buffer)
                lines = [line.strip() for line in gcode.splitlines() if line.strip()]

                if not lines:
                    gcode_buffer = []
                    return

                self._log(f"[JOB] Streaming {len(lines)} G-code lines")
                self.controller.stream(lines, timeout=10.0)

                gcode_buffer = []

            except RuntimeError as e:
                self._log(f"[JOB] Error: {e}")
                abort_job("[JOB] Stream failure")
                raise

        try:
            for i, op in enumerate(ops, start=1):

                if stop_now():
                    abort_job("[JOB] Stop requested, aborting")
                    break

                while pause_now() and not stop_now():
                    self._log("[JOB] Paused...")
                    time.sleep(0.1)

                check_timeout()

                self._progress(i, total_ops, type(op).__name__)

                if isinstance(op, FeedAdvance):
                    flush_gcode()

                    forward = getattr(op, "forward", True)
                    distance = getattr(op, "distance", 0.0)

                    direction = "forward" if forward else "reverse"
                    self._log(f"[JOB] Feeding rollers: {distance:.1f} mm ({direction})")

                    self.rollers.feed_distance(
                        distance_mm=distance,
                        speed_mm_s=self.roller_speed_mm_s,
                        forward=forward,
                    )
                else:
                    gcode_buffer.append(op)

            flush_gcode()

            if not stop_now():
                self._log("[JOB] Completed successfully")

        except Exception as e:
            self._log(f"[JOB] Fatal error: {e}")
            self.stop_requested = True
            raise