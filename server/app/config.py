import os
from dataclasses import dataclass
from pathlib import Path

from .auth import password_hash_is_valid


@dataclass(frozen=True)
class Settings:
    stream_health_url: str
    stream_upstream: str
    stream_path: str
    public_stream_url: str
    allowed_hosts: tuple[str, ...]
    auth_password_hash: str
    serve_web: bool = True
    detection_enabled: bool = False
    detection_source: str = "rtsp://127.0.0.1:8554/roomcam-detection"
    detection_model: Path = Path("/app/models/ssd_mobilenet_v2_int8.tflite")
    detection_confidence: float = 0.6
    detection_threads: int = 1


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _required_list_env(name: str) -> tuple[str, ...]:
    values = tuple(value.strip() for value in _required_env(name).split(",") if value.strip())
    if not values:
        raise RuntimeError(f"Environment variable must contain at least one value: {name}")
    return values


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    if value.lower() in {"1", "true", "yes"}:
        return True
    if value.lower() in {"0", "false", "no"}:
        return False
    raise RuntimeError(f"Environment variable must be a boolean: {name}")


def _required_bool_env(name: str) -> bool:
    value = _required_env(name)
    if value.lower() in {"1", "true", "yes"}:
        return True
    if value.lower() in {"0", "false", "no"}:
        return False
    raise RuntimeError(f"Environment variable must be a boolean: {name}")


def _required_int_env(name: str, minimum: int) -> int:
    try:
        value = int(_required_env(name))
    except ValueError as exc:
        raise RuntimeError(f"Environment variable must be an integer: {name}") from exc
    if value < minimum:
        raise RuntimeError(f"Environment variable is below its minimum: {name}")
    return value


def _required_float_env(name: str, minimum: float, maximum: float) -> float:
    try:
        value = float(_required_env(name))
    except ValueError as exc:
        raise RuntimeError(f"Environment variable must be a number: {name}") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"Environment variable is outside its allowed range: {name}")
    return value


def load_settings() -> Settings:
    auth_password_hash = _required_env("ROOMCAM_AUTH_PASSWORD_HASH")
    if not password_hash_is_valid(auth_password_hash):
        raise RuntimeError("ROOMCAM_AUTH_PASSWORD_HASH is invalid")

    detection_enabled = _required_bool_env("ROOMCAM_DETECTION_ENABLED")
    detection_source = ""
    detection_model = Path()
    detection_confidence = 0.0
    detection_threads = 1
    if detection_enabled:
        detection_source = _required_env("ROOMCAM_DETECTION_SOURCE")
        detection_model = Path(_required_env("ROOMCAM_DETECTION_MODEL"))
        detection_confidence = _required_float_env(
            "ROOMCAM_DETECTION_CONFIDENCE",
            minimum=0,
            maximum=1,
        )
        detection_threads = _required_int_env("ROOMCAM_DETECTION_THREADS", minimum=1)

    return Settings(
        stream_health_url=_required_env("ROOMCAM_STREAM_HEALTH_URL"),
        stream_upstream=_required_env("ROOMCAM_STREAM_UPSTREAM").rstrip("/"),
        stream_path="/" + _required_env("ROOMCAM_STREAM_PATH").strip("/") + "/",
        public_stream_url="/" + _required_env("ROOMCAM_PUBLIC_STREAM_URL").strip("/") + "/",
        allowed_hosts=_required_list_env("ROOMCAM_ALLOWED_HOSTS"),
        auth_password_hash=auth_password_hash,
        serve_web=_bool_env("ROOMCAM_SERVE_WEB", default=True),
        detection_enabled=detection_enabled,
        detection_source=detection_source,
        detection_model=detection_model,
        detection_confidence=detection_confidence,
        detection_threads=detection_threads,
    )
