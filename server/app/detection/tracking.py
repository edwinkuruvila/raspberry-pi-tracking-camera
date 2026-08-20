"""Person association, target selection, and movement guidance."""

from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

TRACK_HOLD_SECONDS = 0.8
TARGET_REACQUIRE_SECONDS = 1.0
TRACK_CONFIRMATION_HITS = 3
MIN_ASSOCIATION_IOU = 0.1
MAX_ASSOCIATION_DISTANCE = 0.35
# SSD boxes fluctuate slightly even around a stationary person. Use stronger
# filtering for tiny changes, then become progressively more responsive as the
# measured movement becomes unmistakable.
STATIONARY_CENTER_DEADBAND = 0.006
FULL_MOVEMENT_DISTANCE = 0.04
STATIONARY_POSITION_ALPHA = 0.2
MOVING_POSITION_ALPHA = 0.85
STATIONARY_SIZE_ALPHA = 0.15
MOVING_SIZE_ALPHA = 0.5
# A full-person detector's geometric center is around the torso. Aim within the
# upper part of the box to keep the person's head near the center of the frame.
TARGET_HEIGHT_RATIO = 0.35


@dataclass(frozen=True, slots=True)
class Detection:
    """One normalized person detection returned by the model."""

    confidence: float
    left: float
    top: float
    width: float
    height: float


class PersonPayload(TypedDict):
    """Browser-safe representation of a tracked person."""

    track_id: int
    confidence: float
    left: float
    top: float
    width: float
    height: float
    observed: bool
    confirmed: bool
    selected: NotRequired[bool]


class GuidancePayload(TypedDict):
    """Normalized target position and the movement it requires."""

    track_id: int
    center_x: float
    center_y: float
    error_x: float
    error_y: float
    pan: Literal["left", "right", "hold"]
    tilt: Literal["up", "down", "hold"]


@dataclass(slots=True)
class PersonTrack:
    """Mutable state for one person across consecutive detector frames."""

    track_id: int
    confidence: float
    left: float
    top: float
    width: float
    height: float
    last_seen: float
    observed: bool = True
    hits: int = 1

    @property
    def area(self) -> float:
        return self.width * self.height

    def observe(self, detection: Detection, now: float) -> None:
        """Refresh this track from a spatially associated detection."""

        current_center_x = self.left + self.width / 2
        current_center_y = self.top + self.height / 2
        detected_center_x = detection.left + detection.width / 2
        detected_center_y = detection.top + detection.height / 2
        center_change = max(
            abs(detected_center_x - current_center_x),
            abs(detected_center_y - current_center_y),
        )
        movement = min(
            1.0,
            max(0.0, center_change - STATIONARY_CENTER_DEADBAND)
            / (FULL_MOVEMENT_DISTANCE - STATIONARY_CENTER_DEADBAND),
        )
        position_alpha = _interpolate(
            STATIONARY_POSITION_ALPHA,
            MOVING_POSITION_ALPHA,
            movement,
        )
        size_alpha = _interpolate(
            STATIONARY_SIZE_ALPHA,
            MOVING_SIZE_ALPHA,
            movement,
        )

        center_x = _interpolate(
            current_center_x,
            detected_center_x,
            position_alpha,
        )
        center_y = _interpolate(
            current_center_y,
            detected_center_y,
            position_alpha,
        )
        width = _interpolate(self.width, detection.width, size_alpha)
        height = _interpolate(self.height, detection.height, size_alpha)

        self.confidence = detection.confidence
        self.width = width
        self.height = height
        self.left = min(1.0 - width, max(0.0, center_x - width / 2))
        self.top = min(1.0 - height, max(0.0, center_y - height / 2))
        self.last_seen = now
        self.observed = True
        self.hits += 1

    def as_dict(self, now: float) -> PersonPayload:
        age = max(0.0, now - self.last_seen)
        confidence = self.confidence * max(0.0, 1.0 - age / TRACK_HOLD_SECONDS)
        return {
            "track_id": self.track_id,
            "confidence": round(confidence, 3),
            "left": round(self.left, 4),
            "top": round(self.top, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
            "observed": self.observed,
            "confirmed": self.hits >= TRACK_CONFIRMATION_HITS,
        }


class PersonTracker:
    """Associates detections over time and maintains one stable target."""

    def __init__(self, creation_confidence: float) -> None:
        self._creation_confidence = creation_confidence
        self._next_track_id = 1
        self._tracks: list[PersonTrack] = []
        self._target_id: int | None = None
        self._target_lost_at: float | None = None

    def update(
        self,
        detections: list[Detection],
        now: float,
    ) -> tuple[list[PersonPayload], int | None]:
        """Match detections, expire stale tracks, and return browser-safe data."""

        unmatched = set(range(len(detections)))
        for track in self._tracks:
            match = self._best_match(track, detections, unmatched)
            if match is None:
                track.observed = False
                continue

            detection = detections[match]
            unmatched.remove(match)
            track.observe(detection, now)

        self._tracks = [track for track in self._tracks if now - track.last_seen <= TRACK_HOLD_SECONDS]
        for index in unmatched:
            detection = detections[index]
            if detection.confidence < self._creation_confidence:
                continue
            self._tracks.append(
                PersonTrack(
                    track_id=self._next_track_id,
                    confidence=detection.confidence,
                    left=detection.left,
                    top=detection.top,
                    width=detection.width,
                    height=detection.height,
                    last_seen=now,
                )
            )
            self._next_track_id += 1

        self._select_target(now)
        people = [track.as_dict(now) for track in self._tracks]
        for person in people:
            person["selected"] = person["track_id"] == self._target_id
        return people, self._target_id

    def _select_target(self, now: float) -> None:
        if self._target_id is not None:
            if any(track.track_id == self._target_id for track in self._tracks):
                self._target_lost_at = None
                return
            self._target_id = None
            self._target_lost_at = now

        confirmed = [track for track in self._tracks if track.hits >= TRACK_CONFIRMATION_HITS and track.observed]
        if not confirmed:
            return
        if self._target_lost_at is not None and now - self._target_lost_at < TARGET_REACQUIRE_SECONDS:
            return

        target = max(confirmed, key=lambda track: track.area)
        self._target_id = target.track_id
        self._target_lost_at = None

    @staticmethod
    def _best_match(
        track: PersonTrack,
        detections: list[Detection],
        candidates: set[int],
    ) -> int | None:
        best_index = None
        best_score = float("-inf")
        for index in candidates:
            detection = detections[index]
            overlap = box_iou(track, detection)
            distance = center_distance(track, detection)
            if overlap < MIN_ASSOCIATION_IOU and distance > MAX_ASSOCIATION_DISTANCE:
                continue
            score = overlap - distance * 0.25
            if score > best_score:
                best_index = index
                best_score = score
        return best_index


def box_iou(track: PersonTrack, detection: Detection) -> float:
    """Return intersection-over-union for spatial track association."""

    left = max(track.left, detection.left)
    top = max(track.top, detection.top)
    right = min(track.left + track.width, detection.left + detection.width)
    bottom = min(track.top + track.height, detection.top + detection.height)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = track.area + detection.width * detection.height - intersection
    return intersection / union if union > 0 else 0.0


def center_distance(track: PersonTrack, detection: Detection) -> float:
    """Return normalized distance between two box centers."""

    track_x = track.left + track.width / 2
    track_y = track.top + track.height / 2
    detection_x = detection.left + detection.width / 2
    detection_y = detection.top + detection.height / 2
    return ((track_x - detection_x) ** 2 + (track_y - detection_y) ** 2) ** 0.5


def _interpolate(start: float, end: float, amount: float) -> float:
    return start + (end - start) * amount


def movement_guidance(
    people: list[PersonPayload],
    target_id: int | None,
) -> GuidancePayload | None:
    """Calculate what servo control would do without issuing any movement."""

    target = next((person for person in people if person["track_id"] == target_id), None)
    if target is None:
        return None

    center_x = target["left"] + target["width"] / 2
    center_y = target["top"] + target["height"] * TARGET_HEIGHT_RATIO
    error_x = center_x - 0.5
    error_y = center_y - 0.5
    pan = "hold" if abs(error_x) <= 0.12 else ("right" if error_x > 0 else "left")
    tilt = "hold" if abs(error_y) <= 0.15 else ("down" if error_y > 0 else "up")
    return {
        "track_id": target["track_id"],
        "center_x": round(center_x, 4),
        "center_y": round(center_y, 4),
        "error_x": round(error_x, 4),
        "error_y": round(error_y, 4),
        "pan": pan,
        "tilt": tilt,
    }
