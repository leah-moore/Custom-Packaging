import time
from .hardware import running_on_raspberry_pi


# ------------------------
# Base Interface
# ------------------------
class BaseRollerDriver:
    def feed_distance(self, distance_mm, speed_mm_s=10.0, forward=True):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


# ------------------------
# Simulation (Mac)
# ------------------------
class SimulatedRollerDriver(BaseRollerDriver):
    def feed_distance(self, distance_mm, speed_mm_s=10.0, forward=True):
        print(f"[SIM] feed {distance_mm} mm @ {speed_mm_s} mm/s")
        time.sleep(abs(distance_mm) / speed_mm_s)

    def stop(self):
        print("[SIM] stop rollers")


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

        lgpio.gpio_claim_output(self.h, self.step_pin)
        lgpio.gpio_claim_output(self.h, self.dir_pin)
        lgpio.gpio_claim_output(self.h, self.enable_pin)

        self.disable()

    def enable(self):
        self.lgpio.gpio_write(self.h, self.enable_pin, 0)

    def disable(self):
        self.lgpio.gpio_write(self.h, self.enable_pin, 1)

    def feed_distance(self, distance_mm, speed_mm_s=10.0, forward=True):
        steps = int(abs(distance_mm) * self.steps_per_mm)
        delay = 0.5 / (self.steps_per_mm * speed_mm_s)

        self.enable()
        self.lgpio.gpio_write(self.h, self.dir_pin, 1 if forward else 0)

        for _ in range(steps):
            self.lgpio.gpio_write(self.h, self.step_pin, 1)
            time.sleep(delay)
            self.lgpio.gpio_write(self.h, self.step_pin, 0)
            time.sleep(delay)

    def stop(self):
        self.disable()


# ------------------------
# Public Controller
# ------------------------
class RollerController:
    def __init__(self, step_pin=17, dir_pin=27, enable_pin=22, steps_per_mm=10):
        if running_on_raspberry_pi():
            self.driver = PiStepperDriver(step_pin, dir_pin, enable_pin, steps_per_mm)
        else:
            self.driver = SimulatedRollerDriver()

    def feed_distance(self, distance_mm, speed_mm_s=10.0, forward=True):
        self.driver.feed_distance(distance_mm, speed_mm_s, forward)

    def stop(self):
        self.driver.stop()