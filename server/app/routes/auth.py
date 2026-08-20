import asyncio
import ipaddress
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..auth import LoginAttemptLimiter, SessionStore, verify_password

SESSION_COOKIE = "roomcam_auth_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
logger = logging.getLogger("roomcam.auth")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class AuthRoutes:
    def __init__(
        self,
        sessions: SessionStore,
        attempt_limiter: LoginAttemptLimiter,
        password_hash: str,
    ) -> None:
        self.sessions = sessions
        self.attempt_limiter = attempt_limiter
        self._password_hash = password_hash
        self._verification_semaphore = asyncio.Semaphore(1)
        self.router = APIRouter(prefix="/api/auth")
        self.router.add_api_route("/status", self.status, methods=["GET"])
        self.router.add_api_route("/login", self.login, methods=["POST"], status_code=204)
        self.router.add_api_route("/logout", self.logout, methods=["POST"], status_code=204)

    def is_authenticated(self, request: Request) -> bool:
        return self.sessions.verify(request.cookies.get(SESSION_COOKIE))

    def status(self, request: Request) -> dict[str, bool]:
        return {"authenticated": self.is_authenticated(request)}

    async def login(self, payload: LoginRequest, request: Request) -> Response:
        client_key = login_client_key(request)
        if not self.attempt_limiter.reserve(client_key):
            logger.warning("Rate-limited login attempt from %r", client_key)
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again later")

        try:
            async with self._verification_semaphore:
                password_is_valid = await asyncio.to_thread(verify_password, payload.password, self._password_hash)
        except BaseException:
            self.attempt_limiter.cancel(client_key)
            raise
        if not password_is_valid:
            self.attempt_limiter.record_failure(client_key)
            logger.warning("Failed login attempt from %r", client_key)
            await asyncio.sleep(0.25)
            raise HTTPException(status_code=401, detail="Incorrect password")

        self.attempt_limiter.record_success(client_key)
        response = Response(status_code=204)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=self.sessions.create(),
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="strict",
            secure=request.headers.get("x-forwarded-proto") == "https",
            path="/",
        )
        return response

    def logout(self, request: Request) -> Response:
        self.sessions.revoke(request.cookies.get(SESSION_COOKIE))
        response = Response(status_code=204)
        response.delete_cookie(key=SESSION_COOKIE, path="/", samesite="strict")
        return response


def login_client_key(request: Request) -> str:
    tailscale_login = request.headers.get("tailscale-user-login")
    client_host = request.client.host if request.client is not None else None
    if tailscale_login and client_host is not None and is_loopback_address(client_host):
        return f"tailscale:{tailscale_login}"
    if client_host is not None:
        return f"client:{client_host}"
    return "client:unknown"


def is_loopback_address(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
