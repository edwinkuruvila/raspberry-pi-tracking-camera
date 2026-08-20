"""Servo movement policy for target following and sentry sweeps."""

from dataclasses import dataclass

from ..servo_controller import ServoController
from .tracking import GuidancePayload, PersonPayload

SENTRY_DELAY_SECONDS = 5.0
SENTRY_PAN_RATE_US_PER_SECOND = 120
SENTRY_MAX_STEP_US = 120


@dataclass(slots=True)
class SentryState:
    last_person_seen: float
    direction: int = 1
    last_step_at: float | None = None

    def observe_person(self, now: float) -> None:
        self.last_person_seen = now
        self.last_step_at = None


class FollowingController:
    """Translate detection guidance and sentry timing into servo adjustments."""

    def __init__(self, servos: ServoController) -> None:
        self._servos = servos

    def follow(
        self,
        people: list[PersonPayload],
        target_id: int | None,
        guidance: GuidancePayload | None,
    ) -> bool:
        if guidance is None or not _target_is_observed(people, target_id):
            return False

        pan_step = _axis_step(guidance["error_x"])
        tilt_step = _axis_step(guidance["error_y"])
        pan_delta = _pan_delta(guidance["pan"], pan_step)
        tilt_delta = _tilt_delta(guidance["tilt"], tilt_step)
        if pan_delta == 0 and tilt_delta == 0:
            return False

        self._servos.adjust(pan_delta, tilt_delta)
        return True

    def sentry(self, state: SentryState, now: float) -> tuple[bool, bool]:
        if now - state.last_person_seen < SENTRY_DELAY_SECONDS:
            state.last_step_at = None
            return False, False
        if state.last_step_at is None:
            state.last_step_at = now
            return True, False

        elapsed = now - state.last_step_at
        step_us = min(SENTRY_MAX_STEP_US, round(elapsed * SENTRY_PAN_RATE_US_PER_SECOND))
        if step_us <= 0:
            return True, False

        status = self._servos.adjust(state.direction * step_us, 0)
        pan = status["pan"]
        if not isinstance(pan, dict):
            raise RuntimeError("Unexpected pan servo status")
        target_us = int(pan["target_us"])
        if target_us >= int(pan["maximum_us"]):
            state.direction = -1
        elif target_us <= int(pan["minimum_us"]):
            state.direction = 1

        state.last_step_at = now
        return True, True


def _target_is_observed(people: list[PersonPayload], target_id: int | None) -> bool:
    return any(person["track_id"] == target_id and person["confirmed"] and person["observed"] for person in people)


def _axis_step(error: float) -> int:
    return round(25 + min(1.0, abs(error) / 0.5) * 95)


def _pan_delta(direction: str, step: int) -> int:
    if direction == "left":
        return step
    if direction == "right":
        return -step
    return 0


def _tilt_delta(direction: str, step: int) -> int:
    if direction == "up":
        return -step
    if direction == "down":
        return step
    return 0
