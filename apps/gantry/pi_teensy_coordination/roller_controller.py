import threading
import time

from .hardware import running_on_raspberry_pi
from .config import (
    ROLLER_STEP_PIN,
    ROLLER_DIR_PIN,
    ROLLER_ENABLE_PIN,
    ROLLER_STEPS_PER_MM,
    DEFAULT_ROLLER_SPEED_MM_S,
)

class BaseRollerDriver:
    def feed_distance(self, distance_mm, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        raise NotImplementedError

    def start_continuous(self, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def cleanup(self):
        pass


class SimulatedRollerDriver(BaseRollerDriver):
    def __init__(self):
        self._stop_requested = False
        self._continuous_thread = None

    def feed_distance(self, distance_mm, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        if speed_mm_s <= 0:
            raise ValueError("speed_mm_s must be > 0")

        self._stop_requested = False
        total_time = abs(distance_mm) / speed_mm_s
        start = time.time()

        direction = "forward" if forward else "reverse"
        print(f"[SIM ROLLERS] feed {distance_mm:.3f} mm @ {speed_mm_s:.3f} mm/s ({direction})")

        while (time.time() - start) < total_time:
            if self._stop_requested:
                print("[SIM ROLLERS] stop requested")
                break
            time.sleep(0.01)

    def start_continuous(self, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        if speed_mm_s <= 0:
            raise ValueError("speed_mm_s must be > 0")

        self.stop()
        self._stop_requested = False

        def worker():
            direction = "forward" if forward else "reverse"
            print(f"[SIM ROLLERS] continuous @ {speed_mm_s:.3f} mm/s ({direction})")
            while not self._stop_requested:
                time.sleep(0.01)

        self._continuous_thread = threading.Thread(target=worker, daemon=True)
        self._continuous_thread.start()

    def stop(self):
        self._stop_requested = True
        print("[SIM ROLLERS] stop rollers")


class LGPIOStepperDriver(BaseRollerDriver):
    def __init__(self, step_pin, dir_pin, enable_pin, steps_per_mm):

        import lgpio

        self.lgpio = lgpio
        self.h = lgpio.gpiochip_open(0)

        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.enable_pin = enable_pin
        self.steps_per_mm = steps_per_mm

        self._stop_requested = False
        self._continuous_thread = None

        self.lgpio.gpio_claim_output(self.h, self.step_pin)
        self.lgpio.gpio_claim_output(self.h, self.dir_pin)
        self.lgpio.gpio_claim_output(self.h, self.enable_pin)

        self.disable()

    def enable(self):
        # TMC2209 EN assumed active-low
        self.lgpio.gpio_write(self.h, self.enable_pin, 0)

    def disable(self):
        self.lgpio.gpio_write(self.h, self.enable_pin, 1)

    def set_direction(self, forward=True):
        self.lgpio.gpio_write(self.h, self.dir_pin, 0 if forward else 1)

    def _step_once(self, half_delay_s: float):
        self.lgpio.gpio_write(self.h, self.step_pin, 1)
        time.sleep(half_delay_s)
        self.lgpio.gpio_write(self.h, self.step_pin, 0)
        time.sleep(half_delay_s)

    def _validate_motion(self, speed_mm_s):
        if speed_mm_s <= 0:
            raise ValueError("speed_mm_s must be > 0")
        if self.steps_per_mm <= 0:
            raise ValueError("steps_per_mm must be > 0")

    def feed_distance(self, distance_mm, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        self._validate_motion(speed_mm_s)

        steps = int(round(abs(distance_mm) * self.steps_per_mm))
        if steps == 0:
            print(f"[LGPIO ROLLERS] zero steps for distance_mm={distance_mm}")
            return

        step_rate = self.steps_per_mm * speed_mm_s
        half_delay_s = max(0.5 / step_rate, 0.0002)

        direction = "forward" if forward else "reverse"
        print(
            f"[LGPIO ROLLERS] feed {distance_mm:.3f} mm ({steps} steps) "
            f"@ {speed_mm_s:.3f} mm/s ({direction})"
        )

        self.stop()
        self._stop_requested = False
        self.enable()
        self.set_direction(forward)

        try:
            for step_idx in range(steps):
                if self._stop_requested:
                    print(f"[LGPIO ROLLERS] stop requested at step {step_idx}/{steps}")
                    break
                self._step_once(half_delay_s)
        finally:
            self.disable()

    def start_continuous(self, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        self._validate_motion(speed_mm_s)

        step_rate = self.steps_per_mm * speed_mm_s
        half_delay_s = max(0.5 / step_rate, 0.0002)

        self.stop()
        self._stop_requested = False

        def worker():
            direction = "forward" if forward else "reverse"
            print(
                f"[LGPIO ROLLERS] continuous start "
                f"@ {speed_mm_s:.3f} mm/s ({direction})"
            )

            self.enable()
            self.set_direction(forward)

            try:
                while not self._stop_requested:
                    self._step_once(half_delay_s)
            finally:
                self.disable()
                print("[LGPIO ROLLERS] continuous stop")

        self._continuous_thread = threading.Thread(target=worker, daemon=True)
        self._continuous_thread.start()

    def stop(self):
        self._stop_requested = True

    def cleanup(self):
        try:
            self.stop()
            time.sleep(0.02)
            self.disable()
        finally:
            self.lgpio.gpiochip_close(self.h)


class RollerController:
    def __init__(
        self,
        step_pin=ROLLER_STEP_PIN,
        dir_pin=ROLLER_DIR_PIN,
        enable_pin=ROLLER_ENABLE_PIN,
        steps_per_mm=ROLLER_STEPS_PER_MM,
    ):
        if running_on_raspberry_pi():
            print("[ROLLER CTRL] Using LGPIOStepperDriver")
            self.driver = LGPIOStepperDriver(
                step_pin=step_pin,
                dir_pin=dir_pin,
                enable_pin=enable_pin,
                steps_per_mm=steps_per_mm,
            )
        else:
            print("[ROLLER CTRL] Using SimulatedRollerDriver")
            self.driver = SimulatedRollerDriver()

    def feed_distance(self, distance_mm, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        self.driver.feed_distance(distance_mm, speed_mm_s, forward)

    def start_continuous(self, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        self.driver.start_continuous(speed_mm_s, forward)

    def stop(self):
        self.driver.stop()

    def cleanup(self):
        self.driver.cleanup()