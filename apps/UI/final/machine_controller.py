import queue
import threading
import time
from typing import List, Optional

import serial


class GrblHALController:
    """Thread-safe GRBL/grblHAL serial controller with line-response waiting."""

    def __init__(self) -> None:
        self.ser: Optional[serial.Serial] = None
        self.read_thread: Optional[threading.Thread] = None
        self.read_running = False
        self.rx_queue: "queue.Queue[str]" = queue.Queue(maxsize=500)
        self.lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def connect(self, port: str, baudrate: int = 115200, timeout: float = 0.1) -> None:
        self.disconnect()
        self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        time.sleep(2.0)

        self.read_running = True
        self.read_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.read_thread.start()

        time.sleep(0.5)
        self.write_raw("\r\n\r\n")
        time.sleep(0.5)
        self.send_realtime(b"\x18")  # soft reset
        time.sleep(0.3)
        self.flush_input()
        self.clear_rx_queue()

    def disconnect(self) -> None:
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
        self.clear_rx_queue()

    def flush_input(self) -> None:
        if self.is_connected and self.ser is not None:
            with self.lock:
                self.ser.reset_input_buffer()

    def clear_rx_queue(self) -> None:
        while True:
            try:
                self.rx_queue.get_nowait()
            except queue.Empty:
                break

    def write_line(self, line: str) -> None:
        if not self.is_connected or self.ser is None:
            print(f"[ERROR] Not connected - dropped: {line.strip()}")
            return

        if not line.endswith("\n"):
            line += "\n"

        with self.lock:
            try:
                self.ser.write(line.encode("ascii", errors="ignore"))
                print(f"[SENT] {line.strip()}")
            except Exception as e:
                print(f"[ERROR] Send failed: {e}")

    def write_raw(self, text: str) -> None:
        if not self.is_connected or self.ser is None:
            return

        with self.lock:
            try:
                self.ser.write(text.encode("ascii", errors="ignore"))
            except Exception:
                pass

    def send_realtime(self, cmd: bytes) -> None:
        if not self.is_connected or self.ser is None:
            return

        with self.lock:
            try:
                self.ser.write(cmd)
            except Exception:
                pass

    def get_rx_lines(self) -> List[str]:
        lines: List[str] = []

        while True:
            try:
                lines.append(self.rx_queue.get_nowait())
            except queue.Empty:
                break

        return lines

    def wait_for_response(self, timeout: float = 5.0) -> str:
        """
        Wait for a controller response relevant to a streamed G-code line.

        Returns the first terminal response:
        - "ok"
        - "error:..."
        - "alarm:..."

        Non-terminal messages like status reports or startup chatter are ignored.
        """
        deadline = time.time() + timeout

        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            try:
                line = self.rx_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue

            low = line.strip().lower()

            if low == "ok":
                return line

            if low.startswith("error") or low.startswith("alarm"):
                return line

            # Ignore async chatter that should not ack a line:
            # status reports, settings dumps, startup text, etc.
            if (
                low.startswith("<")
                or low.startswith("[")
                or "grbl" in low
                or "grblhal" in low
                or low.startswith("$")
            ):
                continue

            # For anything unknown, keep waiting rather than falsely acking.
            continue

        raise TimeoutError("Timed out waiting for controller response")

    def send_line_and_wait_ok(self, line: str, timeout: float = 5.0) -> str:
        """
        Send one G-code line and wait for its terminal response.

        Returns:
            "ok" or the returned error/alarm line.

        Raises:
            RuntimeError if not connected
            TimeoutError if no terminal response arrives
        """
        if not self.is_connected or self.ser is None:
            raise RuntimeError("Controller not connected")

        self.write_line(line)
        return self.wait_for_response(timeout=timeout)

    def _reader_loop(self) -> None:
        while self.read_running and self.is_connected and self.ser is not None:
            try:
                line = self.ser.readline()
                if line:
                    text = line.decode(errors="replace").strip()
                    if text:
                        print(f"[RX] {text}")
                        try:
                            self.rx_queue.put_nowait(text)
                        except queue.Full:
                            print(f"[WARNING] Queue full, dropped: {text}")
            except Exception as e:
                print(f"[READER ERROR] {e}")
                break