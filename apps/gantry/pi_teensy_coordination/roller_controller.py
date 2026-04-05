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

    def feed_distance(self, distance_mm, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        if speed_mm_s <= 0:
            raise ValueError("speed_mm_s must be > 0")

        self._stop_requested = False
        total_time = abs(distance_mm) / speed_mm_s
        start = time.time()
        while (time.time() - start) < total_time:
            if self._stop_requested:
                break
            time.sleep(0.01)

    def start_continuous(self, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        self._stop_requested = False
        print(f"[SIM ROLLERS] continuous @ {speed_mm_s} mm/s, forward={forward}")

    def stop(self):
        self._stop_requested = True
        print("[SIM ROLLERS] stop rollers")


class PiStepperDriver(BaseRollerDriver):
    def __init__(self, step_pin, dir_pin, enable_pin, steps_per_mm):
        import pigpio

        self.pigpio = pigpio
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("pigpio daemon not running")

        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.enable_pin = enable_pin
        self.steps_per_mm = steps_per_mm

        self.pi.set_mode(self.step_pin, pigpio.OUTPUT)
        self.pi.set_mode(self.dir_pin, pigpio.OUTPUT)
        self.pi.set_mode(self.enable_pin, pigpio.OUTPUT)

        self._running = False
        self._wave_id = None
        self.disable()

    def enable(self):
        self.pi.write(self.enable_pin, 0)  # active low

    def disable(self):
        self.pi.write(self.enable_pin, 1)

    def set_direction(self, forward=True):
        self.pi.write(self.dir_pin, 1 if forward else 0)

    def _clear_wave(self):
        try:
            self.pi.wave_tx_stop()
        except Exception:
            pass

        if self._wave_id is not None:
            try:
                self.pi.wave_delete(self._wave_id)
            except Exception:
                pass
            self._wave_id = None

        try:
            self.pi.wave_clear()
        except Exception:
            pass

    def _start_wave(self, speed_mm_s, forward):
        if speed_mm_s <= 0:
            raise ValueError("speed_mm_s must be > 0")
        if self.steps_per_mm <= 0:
            raise ValueError("steps_per_mm must be > 0")

        step_rate = self.steps_per_mm * speed_mm_s  # steps/sec
        half_period_us = int(500000 / step_rate)    # high or low time
        half_period_us = max(half_period_us, 20)    # sane lower bound

        self._clear_wave()
        self.enable()
        self.set_direction(forward)

        pulses = [
            self.pigpio.pulse(1 << self.step_pin, 0, half_period_us),
            self.pigpio.pulse(0, 1 << self.step_pin, half_period_us),
        ]

        self.pi.wave_add_generic(pulses)
        self._wave_id = self.pi.wave_create()
        if self._wave_id < 0:
            raise RuntimeError("Failed to create pigpio wave")

        self.pi.wave_send_repeat(self._wave_id)
        self._running = True

        print(
            f"[PI ROLLERS] continuous start speed={speed_mm_s:.3f} mm/s "
            f"step_rate={step_rate:.1f} steps/s half_period_us={half_period_us}"
        )

    def start_continuous(self, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        self._start_wave(speed_mm_s=speed_mm_s, forward=forward)

    def feed_distance(self, distance_mm, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        steps = int(abs(distance_mm) * self.steps_per_mm)
        if steps == 0:
            return

        self._start_wave(speed_mm_s=speed_mm_s, forward=forward)

        try:
            step_rate = self.steps_per_mm * speed_mm_s
            duration_s = steps / step_rate
            time.sleep(duration_s)
        finally:
            self.stop()

    def stop(self):
        self._running = False
        self._clear_wave()
        self.disable()
        print("[PI ROLLERS] stop rollers")

    def cleanup(self):
        try:
            self.stop()
        finally:
            self.pi.stop()


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

    def start_continuous(self, speed_mm_s=DEFAULT_ROLLER_SPEED_MM_S, forward=True):
        self.driver.start_continuous(speed_mm_s, forward)

    def stop(self):
        self.driver.stop()

    def cleanup(self):
        self.driver.cleanup()