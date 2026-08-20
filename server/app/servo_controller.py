import importlib
import threading
import time
from dataclasses import dataclass
from typing import Literal, Protocol

PAN_GPIO = 18
TILT_GPIO = 13
PAN_CENTER_PULSE_US = 1500
TILT_CENTER_PULSE_US = 1100
PAN_MIN_PULSE_US = 900
PAN_MAX_PULSE_US = 2100
TILT_MIN_PULSE_US = 960
TILT_MAX_PULSE_US = 1300
COMMAND_STEP_US = 100
MAX_FOLLOW_STEP_US = 120
RAMP_STEP_US = 30
CONTROL_PERIOD_SECONDS = 0.01
PWM_OFF = 0
SERVO_PULSES_INACTIVE_ERROR = "GPIO is not in use for servo pulses"

ServoCommand = Literal["left", "right", "up", "down", "center"]


class PigpioClient(Protocol):
    connected: bool

    def get_servo_pulsewidth(self, gpio: int) -> int: ...

    def set_servo_pulsewidth(self, gpio: int, pulse_width_us: int) -> int: ...

    def stop(self) -> None: ...


class ServoUnavailableError(RuntimeError):
    pass


@dataclass
class ServoAxis:
    gpio: int
    minimum_us: int
    maximum_us: int
    center_us: int
    position_us: int
    target_us: int

    def as_dict(self) -> dict[str, int]:
        return {
            "position_us": self.position_us,
            "target_us": self.target_us,
            "minimum_us": self.minimum_us,
            "maximum_us": self.maximum_us,
            "center_us": self.center_us,
        }


def connect_pigpio() -> PigpioClient:
    pigpio = importlib.import_module("pigpio")
    return pigpio.pi("127.0.0.1")


class ServoController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._client: PigpioClient | None = None
        self._closed = False
        self._pan = ServoAxis(
            PAN_GPIO,
            PAN_MIN_PULSE_US,
            PAN_MAX_PULSE_US,
            PAN_CENTER_PULSE_US,
            PAN_CENTER_PULSE_US,
            PAN_CENTER_PULSE_US,
        )
        self._tilt = ServoAxis(
            TILT_GPIO,
            TILT_MIN_PULSE_US,
            TILT_MAX_PULSE_US,
            TILT_CENTER_PULSE_US,
            TILT_CENTER_PULSE_US,
            TILT_CENTER_PULSE_US,
        )
        self._worker = threading.Thread(target=self._move_worker, name="roomcam-servo", daemon=True)
        self._worker.start()

    def status(self) -> dict[str, object]:
        with self._condition:
            self._ensure_client()
            return self._status()

    def command(self, command: ServoCommand) -> dict[str, object]:
        with self._condition:
            self._ensure_client()
            if command == "left":
                self._adjust_target(self._pan, COMMAND_STEP_US)
            elif command == "right":
                self._adjust_target(self._pan, -COMMAND_STEP_US)
            elif command == "up":
                self._adjust_target(self._tilt, -COMMAND_STEP_US)
            elif command == "down":
                self._adjust_target(self._tilt, COMMAND_STEP_US)
            else:
                self._pan.target_us = self._pan.center_us
                self._tilt.target_us = self._tilt.center_us

            self._condition.notify()
            return self._status()

    def adjust(self, pan_delta_us: int, tilt_delta_us: int) -> dict[str, object]:
        """Apply one bounded automatic-following adjustment."""

        if abs(pan_delta_us) > MAX_FOLLOW_STEP_US or abs(tilt_delta_us) > MAX_FOLLOW_STEP_US:
            raise ValueError(f"Servo adjustment exceeds {MAX_FOLLOW_STEP_US} microseconds")

        with self._condition:
            self._ensure_client()
            self._adjust_target(self._pan, pan_delta_us)
            self._adjust_target(self._tilt, tilt_delta_us)
            self._condition.notify()
            return self._status()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify()
        self._worker.join()

        with self._condition:
            if self._client is None:
                return
            self._client.set_servo_pulsewidth(self._pan.gpio, PWM_OFF)
            self._client.set_servo_pulsewidth(self._tilt.gpio, PWM_OFF)
            self._client.stop()
            self._client = None

    def _ensure_client(self) -> PigpioClient:
        if self._closed:
            raise ServoUnavailableError("Servo controller is closed")
        if self._client is None:
            try:
                client = connect_pigpio()
            except (ImportError, OSError) as exc:
                raise ServoUnavailableError("Servo controller unavailable") from exc
            if not client.connected:
                client.stop()
                raise ServoUnavailableError("Servo controller unavailable")
            self._client = client
            self._synchronize_axis(client, self._pan)
            self._synchronize_axis(client, self._tilt)
        return self._client

    def _move_worker(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._closed
                    or self._pan.position_us != self._pan.target_us
                    or self._tilt.position_us != self._tilt.target_us
                )
                if self._closed:
                    return
                client = self._client

            if client is None:
                continue

            started_at = time.monotonic()
            with self._condition:
                try:
                    self._update_axis(client, self._pan)
                    self._update_axis(client, self._tilt)
                except ServoUnavailableError:
                    client.stop()
                    self._client = None
                    self._pan.target_us = self._pan.position_us
                    self._tilt.target_us = self._tilt.position_us

            remaining_seconds = CONTROL_PERIOD_SECONDS - (time.monotonic() - started_at)
            if remaining_seconds > 0:
                time.sleep(remaining_seconds)

    @staticmethod
    def _adjust_target(axis: ServoAxis, change_us: int) -> None:
        axis.target_us = min(axis.maximum_us, max(axis.minimum_us, axis.target_us + change_us))

    @staticmethod
    def _update_axis(client: PigpioClient, axis: ServoAxis) -> None:
        if axis.position_us < axis.target_us:
            next_position_us = min(axis.position_us + RAMP_STEP_US, axis.target_us)
        elif axis.position_us > axis.target_us:
            next_position_us = max(axis.position_us - RAMP_STEP_US, axis.target_us)
        else:
            return

        result = client.set_servo_pulsewidth(axis.gpio, next_position_us)
        if result < 0:
            raise ServoUnavailableError("Servo controller rejected movement")
        axis.position_us = next_position_us

    @staticmethod
    def _synchronize_axis(client: PigpioClient, axis: ServoAxis) -> None:
        try:
            pulse_width_us = client.get_servo_pulsewidth(axis.gpio)
        except Exception as exc:
            # pigpio raises this error when the daemon is connected but the GPIO
            # has not generated servo pulses yet. Treat it like the documented
            # inactive value of zero so a fresh daemon starts at center.
            if SERVO_PULSES_INACTIVE_ERROR not in str(exc):
                raise
            pulse_width_us = PWM_OFF
        if axis.minimum_us <= pulse_width_us <= axis.maximum_us:
            axis.position_us = pulse_width_us
            axis.target_us = pulse_width_us
            return

        result = client.set_servo_pulsewidth(axis.gpio, axis.center_us)
        if result < 0:
            raise ServoUnavailableError("Servo controller rejected center position")
        axis.position_us = axis.center_us
        axis.target_us = axis.center_us

    def _status(self) -> dict[str, object]:
        return {
            "pan": self._pan.as_dict(),
            "tilt": self._tilt.as_dict(),
        }
