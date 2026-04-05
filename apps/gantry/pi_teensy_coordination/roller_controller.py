import time

from .hardware import running_on_raspberry_pi
from .config import (
    ROLLER_STEP_PIN,
    ROLLER_DIR_PIN,
    ROLLER_ENABLE_PIN,
    ROLLER_STEPS_PER_MM,
    DEFAULT_ROLLER_SPEED_MM_S,
)


# ------------------------
# Base Interface
# ------------------------
class BaseRollerDriver:
    def feed_distance(self, distance_mm, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def cleanup(self):
        pass


# ------------------------
# Simulation (Mac / non-Pi)
# ------------------------
class SimulatedRollerDriver(BaseRollerDriver):
    def __init__(self):
        self._stop_requested = False

    def feed_distance(self, distance_mm, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        if speed_mm_s <= 0:
            raise ValueError("speed_mm_s must be > 0")

        direction = "forward" if forward else "reverse"
        print(f"[SIM ROLLERS] feed {distance_mm} mm @ {speed_mm_s} mm/s ({direction})")

        self._stop_requested = False
        total_time = abs(distance_mm) / speed_mm_s if speed_mm_s > 0 else 0.0
        start = time.time()

        while (time.time() - start) < total_time:
            if self._stop_requested:
                print("[SIM ROLLERS] stop requested")
                break
            time.sleep(0.01)

    def stop(self):
        self._stop_requested = True
        print("[SIM ROLLERS] stop rollers")


# ------------------------
# Real Pi Driver (lgpio)
# ------------------------
class PiStepperDriver(BaseRollerDriver):
    def __init__(self, step_pin, dir_pin, enable_pin, steps_per_mm):
        import lgpio

        self.lgpio = lgpio
        self.h = lgpio.gpiochip_open(0)

        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.enable_pin = enable_pin
        self.steps_per_mm = steps_per_mm
        self._stop_requested = False

        self.lgpio.gpio_claim_output(self.h, self.step_pin)
        self.lgpio.gpio_claim_output(self.h, self.dir_pin)
        self.lgpio.gpio_claim_output(self.h, self.enable_pin)

        self.disable()

    def enable(self):
        # Assumes active-low enable on the stepper driver
        self.lgpio.gpio_write(self.h, self.enable_pin, 0)

    def disable(self):
        self.lgpio.gpio_write(self.h, self.enable_pin, 1)

    def set_direction(self, forward=True):
        self.lgpio.gpio_write(self.h, self.dir_pin, 1 if forward else 0)

    def feed_distance(self, distance_mm, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        if speed_mm_s <= 0:
            raise ValueError("speed_mm_s must be > 0")
        if self.steps_per_mm <= 0:
            raise ValueError("steps_per_mm must be > 0")

        steps = int(abs(distance_mm) * self.steps_per_mm)
        if steps == 0:
            print(f"[PI ROLLERS] zero steps for distance_mm={distance_mm}")
            return

        delay = 0.5 / (self.steps_per_mm * speed_mm_s)
        direction = "forward" if forward else "reverse"

        print(f"[PI ROLLERS] feed {distance_mm} mm @ {speed_mm_s} mm/s ({direction})")
        print(f"[PI ROLLERS] steps={steps}, delay={delay:.6f}s")

        self._stop_requested = False
        self.enable()
        self.set_direction(forward)

        try:
            for step_idx in range(steps):
                if self._stop_requested:
                    print(f"[PI ROLLERS] stop requested at step {step_idx}/{steps}")
                    break

                self.lgpio.gpio_write(self.h, self.step_pin, 1)
                time.sleep(delay)
                self.lgpio.gpio_write(self.h, self.step_pin, 0)
                time.sleep(delay)
        finally:
            self.disable()

    def stop(self):
        self._stop_requested = True
        self.disable()
        print("[PI ROLLERS] stop rollers")

    def cleanup(self):
        try:
            self._stop_requested = True
            self.disable()
        finally:
            self.lgpio.gpiochip_close(self.h)


# ------------------------
# Public Controller
# ------------------------
class RollerController:
    def __init__(
        self,
        step_pin=ROLLER_STEP_PIN,
        dir_pin=ROLLER_DIR_PIN,
        enable_pin=ROLLER_ENABLE_PIN,
        steps_per_mm=ROLLER_STEPS_PER_MM,
    ):
        if running_on_raspberry_pi():
            print("[ROLLER CTRL] Using PiStepperDriver")
            self.driver = PiStepperDriver(
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

    def stop(self):
        self.driver.stop()

    def cleanup(self):
        self.driver.cleanup()