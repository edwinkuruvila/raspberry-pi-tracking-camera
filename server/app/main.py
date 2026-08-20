import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from .auth import LoginAttemptLimiter, SessionStore
from .config import Settings, load_settings
from .detection.service import DetectionService
from .routes.auth import SESSION_TTL_SECONDS as AUTH_SESSION_TTL_SECONDS
from .routes.auth import AuthRoutes
from .routes.detection import DetectionRoutes
from .routes.servos import ServoRoutes
from .routes.stream import StreamRoutes
from .routes.system import build_system_router
from .servo_controller import ServoController

LOGIN_ATTEMPT_WINDOW_SECONDS = 5 * 60
LOGIN_ATTEMPT_PER_CLIENT_LIMIT = 5
LOGIN_ATTEMPT_GLOBAL_LIMIT = 20
PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/status",
}
SPA_BLOCKED_PATHS = {"docs", "redoc", "openapi.json"}

settings = load_settings()
auth_sessions = SessionStore(ttl_seconds=AUTH_SESSION_TTL_SECONDS, max_sessions=1)
login_attempt_limiter = LoginAttemptLimiter(
    per_client_limit=LOGIN_ATTEMPT_PER_CLIENT_LIMIT,
    global_limit=LOGIN_ATTEMPT_GLOBAL_LIMIT,
    window_seconds=LOGIN_ATTEMPT_WINDOW_SECONDS,
)
servo_controller = ServoController()
detection_service = DetectionService(
    enabled=settings.detection_enabled,
    source=settings.detection_source,
    model_path=settings.detection_model,
    confidence=settings.detection_confidence,
    threads=settings.detection_threads,
    servo_controller=servo_controller,
)
stream_routes = StreamRoutes(settings)
auth_routes = AuthRoutes(auth_sessions, login_attempt_limiter, settings.auth_password_hash)
detection_routes = DetectionRoutes(detection_service, auth_sessions)
servo_routes = ServoRoutes(servo_controller, detection_service)
app_file = Path(__file__).resolve()
web_dir = (
    next(
        (candidate for candidate in (app_file.parents[1] / "web", app_file.parents[2] / "web") if candidate.exists()),
        None,
    )
    if settings.serve_web
    else None
)
if settings.serve_web and web_dir is None:
    raise RuntimeError("Frontend directory not found")


class EventStreamSafeGZipMiddleware(GZipMiddleware):
    """Compress ordinary responses without buffering detection SSE updates."""

    def __init__(self, app: ASGIApp, minimum_size: int, compresslevel: int) -> None:
        super().__init__(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/api/detection/events":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


def build_lifespan(
    detection: DetectionService,
    servos: ServoController,
    streams: StreamRoutes,
):
    @asynccontextmanager
    async def app_lifespan(_: FastAPI):
        detection.start()
        try:
            yield
        finally:
            await asyncio.to_thread(detection.close)
            await asyncio.to_thread(servos.close)
            await streams.close()

    return app_lifespan


lifespan = build_lifespan(detection_service, servo_controller, stream_routes)


async def _security_response(
    request: Request,
    call_next,
    app_settings: Settings,
    authentication: AuthRoutes,
) -> Response:
    if requires_authentication(request.url.path, app_settings) and not authentication.is_authenticated(request):
        response = JSONResponse(status_code=401, content={"detail": "Authentication required"})
    else:
        response = await call_next(request)

    script_sources = (
        "'self' 'unsafe-inline'" if request.url.path.startswith(app_settings.public_stream_url) else "'self'"
    )
    response.headers.update(
        {
            "Content-Security-Policy": (
                f"default-src 'self'; script-src {script_sources}; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; "
                "base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
            ),
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        }
    )
    if request.headers.get("x-forwarded-proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path == f"{app_settings.public_stream_url}reader.js" and response.status_code == 200:
        response.headers["Cache-Control"] = "private, max-age=3600, must-revalidate"
    elif request.url.path.startswith("/assets/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def requires_authentication(path: str, app_settings: Settings) -> bool:
    protected_api = path.startswith("/api/") and path not in PUBLIC_API_PATHS
    protected_stream = path.startswith(app_settings.public_stream_url)
    return protected_api or protected_stream


def create_app(
    app_settings: Settings,
    authentication: AuthRoutes,
    detection: DetectionRoutes,
    servos: ServoRoutes,
    streams: StreamRoutes,
    *,
    app_lifespan,
    frontend_dir: Path | None,
) -> FastAPI:
    application = FastAPI(
        title="Room Camera API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=app_lifespan,
    )
    application.add_middleware(EventStreamSafeGZipMiddleware, minimum_size=500, compresslevel=6)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=list(app_settings.allowed_hosts))
    application.include_router(authentication.router)
    application.include_router(build_system_router(app_settings))
    application.include_router(servos.router)
    application.include_router(detection.router)
    application.include_router(streams.router)

    @application.middleware("http")
    async def security_headers(request: Request, call_next) -> Response:
        return await _security_response(request, call_next, app_settings, authentication)

    if frontend_dir is not None:
        frontend_dist = frontend_dir / "dist"
        if (frontend_dist / "assets").exists():
            application.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @application.get("/{full_path:path}")
        def spa(full_path: str) -> FileResponse:
            if full_path in SPA_BLOCKED_PATHS or full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            index_path = frontend_dist / "index.html"
            return FileResponse(index_path if index_path.exists() else frontend_dir / "index.html")

    return application


app = create_app(
    settings,
    auth_routes,
    detection_routes,
    servo_routes,
    stream_routes,
    app_lifespan=lifespan,
    frontend_dir=web_dir,
)
