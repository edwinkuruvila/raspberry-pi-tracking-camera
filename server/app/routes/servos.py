from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..detection.service import DetectionService
from ..servo_controller import ServoCommand, ServoController, ServoUnavailableError


class ServoCommandRequest(BaseModel):
    command: ServoCommand


class ServoRoutes:
    def __init__(self, controller: ServoController, detection: DetectionService) -> None:
        self._controller = controller
        self._detection = detection
        self.router = APIRouter(prefix="/api/servos")
        self.router.add_api_route("", self.status, methods=["GET"])
        self.router.add_api_route("/command", self.command, methods=["POST"])

    def status(self) -> dict[str, object]:
        try:
            return self._controller.status()
        except ServoUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def command(self, payload: ServoCommandRequest) -> dict[str, object]:
        self._detection.disable_follow()
        try:
            return self._controller.command(payload.command)
        except ServoUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
