from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..auth import SessionStore
from ..detection.service import DetectionPayload, DetectionService
from ..servo_controller import ServoUnavailableError
from .auth import SESSION_COOKIE


class DetectionFollowRequest(BaseModel):
    enabled: bool


class DetectionRoutes:
    def __init__(self, service: DetectionService, sessions: SessionStore) -> None:
        self._service = service
        self._sessions = sessions
        self.router = APIRouter(prefix="/api/detection")
        self.router.add_api_route("", self.status, methods=["GET"])
        self.router.add_api_route("/events", self.events, methods=["GET"])
        self.router.add_api_route("/follow", self.follow, methods=["POST"])

    def status(self) -> DetectionPayload:
        return self._service.snapshot()

    def events(self, request: Request) -> StreamingResponse:
        return StreamingResponse(
            self.authenticated_events(request.cookies.get(SESSION_COOKIE)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )

    def follow(self, payload: DetectionFollowRequest) -> DetectionPayload:
        try:
            return self._service.set_follow(payload.enabled)
        except (RuntimeError, ServoUnavailableError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def authenticated_events(self, session_token: str | None) -> Iterator[bytes]:
        for message in self._service.events():
            if not self._sessions.verify(session_token):
                return
            yield message
