import queue
import threading
import time
from typing import List, Optional

import serial


class GrblHALController:
    """Thread-safe GRBL/grblHAL serial controller."""

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

    def flush_input(self) -> None:
        if self.is_connected and self.ser is not None:
            with self.lock:
                self.ser.reset_input_buffer()

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