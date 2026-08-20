from datetime import UTC, datetime

from fastapi import APIRouter

from ..config import Settings
from ..pi_client import get_pi_health


def build_system_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "roomcam-api",
            "time": datetime.now(UTC).isoformat(),
        }

    @router.get("/pi/health")
    def pi_health() -> dict[str, object]:
        return get_pi_health(settings)

    @router.get("/config")
    def public_config() -> dict[str, str]:
        return {"public_stream_url": settings.public_stream_url}

    return router
