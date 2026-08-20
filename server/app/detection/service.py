"""Background person detection and automatic-following service."""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from ..servo_controller import ServoController, ServoUnavailableError
from .following import FollowingController, SentryState
from .tracking import GuidancePayload, PersonPayload, PersonTracker, movement_guidance

if TYPE_CHECKING:
    import numpy as np

    from .inference import ModelRuntime

CONTINUATION_CONFIDENCE = 0.45
CAMERA_SETTLE_SECONDS = 0.1
INITIAL_FRAME_GRACE_SECONDS = 2.0
DetectionStatus = Literal[
    "disabled",
    "idle",
    "loading_model",
    "connecting_camera",
    "detecting",
    "online",
    "camera_unavailable",
    "error",
]
logger = logging.getLogger("uvicorn.error.roomcam.detection")


class DetectionPayload(TypedDict):
    status: DetectionStatus
    people: list[PersonPayload]
    target_id: int | None
    guidance: GuidancePayload | None
    camera_moving: bool
    sentry_mode: bool
    inference_ms: int
    updated_at: float
    follow_enabled: bool
    error: str | None


class DetectionService:
    """Detect and follow a person only while automatic mode is active."""

    def __init__(
        self,
        *,
        enabled: bool,
        source: str,
        model_path: Path,
        confidence: float,
        threads: int,
        servo_controller: ServoController,
    ) -> None:
        self._enabled = enabled
        self._source = source
        self._model_path = model_path
        self._confidence = confidence
        self._threads = threads
        self._servo_controller = servo_controller
        self._following = FollowingController(servo_controller)
        self._condition = threading.Condition()
        self._revision = 0
        self._stop = threading.Event()
        self._capture: Any = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self._follow_enabled = False
        self._activation = 0
        self._model_ready = False
        self._camera_ready = False
        self._settling_until = 0.0
        self._payload = self._initial_payload()

    def start(self) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("Detection service is closed")
            if not self._enabled or self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run,
                name="person-detection",
                daemon=True,
            )
            self._thread.start()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._stop.set()
            self._activation += 1
            self._follow_enabled = False
            self._condition.notify_all()
        capture = self._capture
        if capture is not None:
            capture.close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.error("Detection worker did not stop within the shutdown timeout")
            else:
                self._thread = None

    def snapshot(self) -> DetectionPayload:
        with self._condition:
            return copy.deepcopy(self._payload)

    def events(self) -> Iterator[bytes]:
        revision = -1
        while not self._stop.is_set():
            with self._condition:
                changed = self._condition.wait_for(
                    lambda revision=revision: self._revision > revision or self._stop.is_set(),
                    timeout=10,
                )
                if self._stop.is_set():
                    return
                if not changed:
                    message = b": keepalive\n\n"
                else:
                    revision = self._revision
                    payload = json.dumps(
                        self._payload,
                        separators=(",", ":"),
                    ).encode()
                    message = b"data: " + payload + b"\n\n"
            yield message

    def set_follow(self, enabled: bool) -> DetectionPayload:
        if enabled and not self._enabled:
            raise RuntimeError("Person detection is disabled")
        with self._condition:
            self._activation += 1
            self._follow_enabled = enabled
            if enabled:
                self._camera_ready = False
            self._publish_reset_locked(
                status=self._activation_status_locked() if enabled else "idle",
                follow_enabled=enabled,
                error=None,
            )
            return dict(self._payload)

    def disable_follow(self) -> None:
        with self._condition:
            if not self._follow_enabled:
                if self._payload["status"] == "error":
                    self._publish_reset_locked(status="idle", follow_enabled=False)
                return
            self._activation += 1
            self._follow_enabled = False
            self._publish_reset_locked(status="idle", follow_enabled=False, error=None)

    def _run(self) -> None:
        try:
            runtime = self._load_model()
            while (activation := self._wait_for_activation()) is not None:
                self._run_tracking_session(runtime, activation)
        except Exception as exc:
            logger.exception("Detection service stopped")
            self._disable_after_error(str(exc))
        finally:
            capture = self._capture
            if capture is not None:
                capture.close()
                self._capture = None

    def _load_model(self) -> ModelRuntime:
        from .inference import load_model

        started = time.monotonic()
        runtime = load_model(self._model_path, self._threads)

        with self._condition:
            self._model_ready = True
            if self._follow_enabled:
                self._publish_locked(
                    {
                        **self._payload,
                        "status": "connecting_camera",
                        "updated_at": time.time(),
                    }
                )
        logger.info("Detection model loaded in %.0f ms", (time.monotonic() - started) * 1000)
        return runtime

    def _wait_for_activation(self) -> int | None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._follow_enabled or self._stop.is_set(),
            )
            return None if self._stop.is_set() else self._activation

    def _run_tracking_session(self, runtime: ModelRuntime, activation: int) -> None:
        from .capture import LatestFrameCapture

        capture = LatestFrameCapture(self._source)
        self._capture = capture
        capture.start()
        sequence = 0
        tracker = PersonTracker(self._confidence)
        activation_started = time.monotonic()
        sentry = SentryState(last_person_seen=activation_started)
        waiting_for_first_frame = True

        try:
            while self._is_following(activation) and not self._stop.is_set():
                latest = capture.wait_for_frame(sequence, timeout=1.0)
                if latest is None:
                    self._handle_missing_frame(waiting_for_first_frame, activation_started, activation)
                    continue

                sequence, frame = latest
                if not self._is_following(activation) or time.monotonic() < self._settling_until:
                    continue

                try:
                    first_inference = waiting_for_first_frame
                    if first_inference:
                        if not self._mark_first_frame_ready(activation, activation_started):
                            continue
                        waiting_for_first_frame = False
                    self._process_frame(runtime, frame, tracker, sentry, activation, first_inference)
                except Exception as exc:
                    logger.exception("Detection frame failed")
                    self._disable_after_error(str(exc))
                    time.sleep(0.25)
        finally:
            capture.close()
            self._capture = None
            with self._condition:
                self._camera_ready = False

    def _handle_missing_frame(
        self,
        waiting_for_first_frame: bool,
        activation_started: float,
        activation: int,
    ) -> None:
        grace_expired = (
            not waiting_for_first_frame or time.monotonic() - activation_started >= INITIAL_FRAME_GRACE_SECONDS
        )
        if grace_expired and self._is_following(activation) and not self._stop.is_set():
            with self._condition:
                self._camera_ready = False
            self._publish_status("camera_unavailable", activation=activation)

    def _mark_first_frame_ready(self, activation: int, activation_started: float) -> bool:
        with self._condition:
            self._camera_ready = True
            if not self._is_following_locked(activation):
                return False
            self._publish_locked(
                {
                    **self._payload,
                    "status": "detecting",
                    "updated_at": time.time(),
                }
            )
        logger.info(
            "Detection frame available %.0f ms after activation",
            (time.monotonic() - activation_started) * 1000,
        )
        return True

    def _process_frame(
        self,
        runtime: ModelRuntime,
        frame: np.ndarray,
        tracker: PersonTracker,
        sentry: SentryState,
        activation: int,
        first_inference: bool,
    ) -> None:
        from .inference import find_people

        started = time.monotonic()
        detections = find_people(
            runtime.interpreter,
            runtime.input_detail,
            runtime.output_details,
            frame,
            CONTINUATION_CONFIDENCE,
        )
        inference_ms = (time.monotonic() - started) * 1000
        if first_inference:
            logger.info("First detection inference completed in %.0f ms", inference_ms)

        now = time.monotonic()
        if first_inference:
            sentry.observe_person(now)
        people, target_id = tracker.update(detections, now)
        guidance = movement_guidance(people, target_id)
        camera_moving = self._apply_following(people, target_id, guidance, activation)
        if any(person["observed"] for person in people):
            sentry.observe_person(now)
            sentry_mode = False
        else:
            sentry_mode, sentry_moving = self._apply_sentry(sentry, now, activation)
            camera_moving = camera_moving or sentry_moving

        with self._condition:
            if not self._is_following_locked(activation):
                return
            self._publish_locked(
                {
                    **self._payload,
                    "status": "online",
                    "people": people,
                    "target_id": target_id,
                    "guidance": guidance,
                    "camera_moving": camera_moving,
                    "sentry_mode": sentry_mode,
                    "inference_ms": round(inference_ms),
                    "updated_at": time.time(),
                    "error": None,
                }
            )

    def _apply_following(
        self,
        people: list[PersonPayload],
        target_id: int | None,
        guidance: GuidancePayload | None,
        activation: int,
    ) -> bool:
        with self._condition:
            if not self._is_following_locked(activation):
                return False
            try:
                moved = self._following.follow(people, target_id, guidance)
            except ServoUnavailableError as exc:
                self._disable_after_error_locked(str(exc))
                return False

        if moved:
            self._settling_until = time.monotonic() + CAMERA_SETTLE_SECONDS
        return moved

    def _apply_sentry(self, sentry: SentryState, now: float, activation: int) -> tuple[bool, bool]:
        if not self._is_following(activation):
            return False, False
        with self._condition:
            if not self._is_following_locked(activation):
                return False, False
            try:
                active, moved = self._following.sentry(sentry, now)
            except ServoUnavailableError as exc:
                self._disable_after_error_locked(str(exc))
                return False, False

        if moved:
            self._settling_until = time.monotonic() + CAMERA_SETTLE_SECONDS
        return active, moved

    def _initial_payload(self) -> DetectionPayload:
        return {
            "status": "disabled" if not self._enabled else "idle",
            "people": [],
            "target_id": None,
            "guidance": None,
            "camera_moving": False,
            "sentry_mode": False,
            "inference_ms": 0,
            "updated_at": 0,
            "follow_enabled": False,
            "error": None,
        }

    def _is_following(self, activation: int) -> bool:
        with self._condition:
            return self._is_following_locked(activation)

    def _is_following_locked(self, activation: int) -> bool:
        return self._follow_enabled and self._activation == activation

    def _activation_status_locked(self) -> str:
        if not self._model_ready:
            return "loading_model"
        if not self._camera_ready:
            return "connecting_camera"
        return "detecting"

    def _publish_status(
        self,
        status: DetectionStatus,
        error: str | None = None,
        *,
        activation: int | None = None,
    ) -> None:
        with self._condition:
            if activation is not None and not self._is_following_locked(activation):
                return
            self._publish_reset_locked(status=status, error=error)

    def _disable_after_error(self, error: str) -> None:
        with self._condition:
            self._disable_after_error_locked(error)

    def _disable_after_error_locked(self, error: str) -> None:
        self._activation += 1
        self._follow_enabled = False
        self._publish_reset_locked(status="error", follow_enabled=False, error=error)

    def _publish_reset_locked(
        self,
        *,
        status: DetectionStatus,
        follow_enabled: bool | None = None,
        error: str | None = None,
    ) -> None:
        self._publish_locked(
            {
                **self._payload,
                "status": status,
                "people": [],
                "target_id": None,
                "guidance": None,
                "camera_moving": False,
                "sentry_mode": False,
                "inference_ms": 0,
                "updated_at": time.time(),
                "follow_enabled": self._follow_enabled if follow_enabled is None else follow_enabled,
                "error": error,
            }
        )

    def _publish_locked(self, payload: DetectionPayload) -> None:
        self._payload = payload
        self._revision += 1
        self._condition.notify_all()
