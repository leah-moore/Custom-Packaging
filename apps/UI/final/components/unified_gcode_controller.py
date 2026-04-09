import queue
import threading
import time
from typing import List, Optional

import serial


class UnifiedGCodeController:
    """Single controller for manual commands, status polling, and job streaming."""

    def __init__(self, port: str = "/dev/ttyACM0", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None

        self.response_queue: "queue.Queue[str]" = queue.Queue(maxsize=500)
        self.status_queue: "queue.Queue[str]" = queue.Queue(maxsize=500)
        self.log_queue: "queue.Queue[str]" = queue.Queue(maxsize=1000)

        self.read_thread: Optional[threading.Thread] = None
        self.read_running = False
        self.lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def connect(self) -> None:
        """Connect to controller and initialize."""
        self.disconnect()

        print(f"[CTRL] Connecting to {self.port}...")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
        time.sleep(2.0)

        self.read_running = True
        self.read_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.read_thread.start()

        time.sleep(0.5)
        self.write_raw("\r\n\r\n")
        time.sleep(0.5)
        self.send_realtime(b"\x18")
        time.sleep(0.3)

        self.flush_input()
        self.clear_all_queues()

        print("[CTRL] Connected")

    def disconnect(self) -> None:
        """Disconnect cleanly and fully reset controller-side state."""
        self.read_running = False

        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=0.5)

        self.read_thread = None

        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass

        self.ser = None
        self.clear_all_queues()

        print("[CTRL] Disconnected")

    def write_raw(self, text: str) -> None:
        """Write raw text without newline."""
        if not self.is_connected or self.ser is None:
            return

        with self.lock:
            try:
                self.ser.write(text.encode("ascii", errors="ignore"))
            except Exception as exc:
                print(f"[ERROR] Write failed: {exc}")

    def send_realtime(self, cmd: bytes) -> None:
        """Send realtime command such as ?, !, ~, Ctrl-X."""
        if not self.is_connected or self.ser is None:
            return

        with self.lock:
            try:
                self.ser.write(cmd)
                print(f"[REALTIME] {cmd.hex()}")
            except Exception as exc:
                print(f"[ERROR] Realtime send failed: {exc}")

    def send_status_request(self) -> None:
        self.send_realtime(b"?")

    def send_line(self, line: str, timeout: float = 5.0) -> str:
        """Send one G-code line and wait for ok/error/alarm."""
        if not self.is_connected or self.ser is None:
            raise RuntimeError("Not connected")

        if not line.endswith("\n"):
            line += "\n"

        with self.lock:
            try:
                self.ser.write(line.encode("ascii", errors="ignore"))
                print(f"[SEND] {line.strip()}")
            except Exception as exc:
                raise RuntimeError(f"Send failed: {exc}") from exc

        return self.wait_for_response(timeout=timeout)

    def stream(self, lines: List[str], timeout: float = 5.0) -> None:
        """Simple line-at-a-time streaming."""
        for i, line in enumerate(lines, start=1):
            if not line.strip():
                continue

            response = self.send_line(line, timeout=timeout)
            low = response.strip().lower()

            if low.startswith("error"):
                raise RuntimeError(f"Line {i} error: {response}")
            if low.startswith("alarm"):
                raise RuntimeError(f"Line {i} alarm: {response}")

    def wait_for_response(self, timeout: float = 5.0) -> str:
        """Wait only for terminal command responses."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            try:
                line = self.response_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue

            low = line.strip().lower()
            if low == "ok" or low.startswith("error") or low.startswith("alarm"):
                return line

        raise TimeoutError(f"No response after {timeout}s")

    def get_status_lines(self) -> List[str]:
        """Non-blocking fetch of status/async messages for the UI."""
        lines: List[str] = []

        while True:
            try:
                lines.append(self.status_queue.get_nowait())
            except queue.Empty:
                break

        return lines

    def get_log_lines(self) -> List[str]:
        """Optional: fetch all raw received lines for diagnostics/console."""
        lines: List[str] = []

        while True:
            try:
                lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break

        return lines

    def flush_input(self) -> None:
        if self.is_connected and self.ser is not None:
            with self.lock:
                try:
                    self.ser.reset_input_buffer()
                except Exception:
                    pass

    def clear_all_queues(self) -> None:
        self._clear_queue(self.response_queue)
        self._clear_queue(self.status_queue)
        self._clear_queue(self.log_queue)

    @staticmethod
    def _clear_queue(q: "queue.Queue[str]") -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break

    def _reader_loop(self) -> None:
        """Background serial reader."""
        while self.read_running and self.is_connected and self.ser is not None:
            try:
                raw = self.ser.readline()
                if not raw:
                    continue

                text = raw.decode(errors="replace").strip()
                if not text:
                    continue

                print(f"[RX] {text}")

                self._safe_put(self.log_queue, text)

                low = text.lower()

                if low == "ok" or low.startswith("error") or low.startswith("alarm"):
                    self._safe_put(self.response_queue, text)
                elif (
                    low.startswith("<")
                    or low.startswith("[")
                    or "grbl" in low
                    or low.startswith("$")
                ):
                    self._safe_put(self.status_queue, text)
                else:
                    # Unknown chatter: send to status queue so UI can still see it.
                    self._safe_put(self.status_queue, text)

            except Exception as exc:
                print(f"[READER ERROR] {exc}")
                break

    @staticmethod
    def _safe_put(q: "queue.Queue[str]", item: str) -> None:
        try:
            q.put_nowait(item)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(item)
            except queue.Full:
                pass