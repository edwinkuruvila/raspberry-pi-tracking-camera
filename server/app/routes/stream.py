import hmac
import re
import secrets
import time

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from ..config import Settings

MAX_REQUEST_BYTES = 1024 * 1024
SESSION_COOKIE = "roomcam_stream_session"
SESSION_TTL_SECONDS = 120
REQUEST_HEADERS = {
    "accept",
    "accept-language",
    "content-type",
    "if-match",
    "if-modified-since",
    "if-none-match",
    "user-agent",
}
RESPONSE_HEADERS = {"cache-control", "content-type", "etag", "last-modified", "link", "location"}


class StreamRoutes:
    """Authenticated MediaMTX signaling proxy and its short-lived session."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session_secret = secrets.token_bytes(32)
        self._http_client: httpx.AsyncClient | None = None
        self.router = APIRouter()
        self.router.add_api_route("/api/stream/session", self.create_session, methods=["GET"], status_code=204)
        self.router.add_api_route(
            f"{settings.public_stream_url}{{proxy_path:path}}",
            self.proxy,
            methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        )

    async def close(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    def create_session(self, request: Request) -> Response:
        response = Response(status_code=204)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=self.issue_session_cookie(),
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="strict",
            secure=request.headers.get("x-forwarded-proto") == "https",
            path=self._settings.public_stream_url,
        )
        return response

    async def proxy(self, proxy_path: str, request: Request) -> Response:
        self.require_session(request)
        self.require_playback_target(proxy_path, request.method)
        upstream_url = f"{self._settings.stream_upstream}{self._settings.stream_path}{proxy_path}"
        if request.url.query:
            upstream_url = f"{upstream_url}?{request.url.query}"

        body = await self.limited_request_body(request)
        headers = {name: value for name, value in request.headers.items() if name.lower() in REQUEST_HEADERS}
        try:
            upstream = await self._get_http_client().request(
                request.method,
                upstream_url,
                headers=headers,
                content=body,
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail="Stream service unavailable") from exc

        response_headers = {name: value for name, value in upstream.headers.items() if name.lower() in RESPONSE_HEADERS}
        location = response_headers.get("location")
        if location and location.startswith(self._settings.stream_path):
            response_headers["location"] = location.replace(
                self._settings.stream_path,
                self._settings.public_stream_url,
                1,
            )
        return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(follow_redirects=False, timeout=10.0, trust_env=False)
        return self._http_client

    @staticmethod
    def require_playback_target(proxy_path: str, method: str) -> None:
        is_stream_asset = method == "GET" and proxy_path in {"", "reader.js"}
        is_whep_options = method == "OPTIONS" and proxy_path == "whep"
        is_whep_start = method == "POST" and proxy_path == "whep"
        is_whep_session = method in {"PATCH", "DELETE"} and re.fullmatch(
            r"whep/[A-Za-z0-9_-]+",
            proxy_path,
        )
        if not (is_stream_asset or is_whep_options or is_whep_start or is_whep_session):
            raise HTTPException(status_code=404)

    @staticmethod
    async def limited_request_body(request: Request) -> bytes:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BYTES:
                    raise HTTPException(status_code=413, detail="Stream request too large")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
        body = await request.body()
        if len(body) > MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="Stream request too large")
        return body

    def issue_session_cookie(self, now: int | None = None) -> str:
        issued_at = int(time.time()) if now is None else now
        payload = str(issued_at)
        signature = hmac.digest(self._session_secret, payload.encode("ascii"), "sha256").hex()
        return f"{payload}.{signature}"

    def require_session(self, request: Request) -> None:
        token = request.cookies.get(SESSION_COOKIE)
        if token is None:
            raise HTTPException(status_code=403, detail="Stream session required")
        try:
            issued_at_text, provided_signature = token.split(".", 1)
            issued_at = int(issued_at_text)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Invalid stream session") from exc

        expected = hmac.digest(self._session_secret, issued_at_text.encode("ascii"), "sha256").hex()
        if not hmac.compare_digest(provided_signature, expected):
            raise HTTPException(status_code=403, detail="Invalid stream session")
        token_age = int(time.time()) - issued_at
        if token_age < 0:
            raise HTTPException(status_code=403, detail="Invalid stream session")
        if token_age > SESSION_TTL_SECONDS:
            raise HTTPException(status_code=403, detail="Expired stream session")
