import serial
import time
from .config import TEENSY_PORT, TEENSY_BAUD


class TeensyController:
    def __init__(self, port=TEENSY_PORT, baudrate=TEENSY_BAUD):
        self.port = port
        self.baudrate = baudrate
        self.ser = None

    def connect(self):
        print("[TEENSY] Connecting...")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
        time.sleep(2)
        self.ser.write(b"\r\n\r\n")
        time.sleep(2)
        self.ser.reset_input_buffer()

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[TEENSY] Disconnected")

    def send_line(self, line: str):
        print(f"[SEND] {line}")
        self.ser.write((line + "\n").encode())
        self._wait_ok()

    def stream(self, lines):
        for line in lines:
            self.send_line(line)

    def _wait_ok(self):
        while True:
            response = self.ser.readline().decode().strip()
            if response:
                print(f"[RECV] {response}")
            if "ok" in response.lower():
                return
            if "error" in response.lower():
                raise RuntimeError(response)