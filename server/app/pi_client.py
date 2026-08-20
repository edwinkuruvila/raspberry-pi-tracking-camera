import time
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import Settings


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str
    latency_ms: int | None = None

    def as_dict(self) -> dict[str, bool | int | str | None]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "latency_ms": self.latency_ms,
        }


def _time_call(check) -> CheckResult:
    start = time.monotonic()
    try:
        detail = check()
    except (OSError, URLError, TimeoutError):
        return CheckResult(ok=False, detail="unavailable", latency_ms=None)

    latency_ms = round((time.monotonic() - start) * 1000)
    return CheckResult(ok=True, detail=detail, latency_ms=latency_ms)


def _http_check(url: str, timeout: float) -> CheckResult:
    def check() -> str:
        request = Request(url, method="GET")
        with urlopen(request, timeout=timeout) as response:
            return "reachable" if 200 <= response.status < 400 else "unavailable"

    return _time_call(check)


def get_pi_health(settings: Settings, timeout: float = 2.0) -> dict[str, object]:
    stream_http_check = _http_check(settings.stream_health_url, timeout)

    return {
        "ok": stream_http_check.ok,
        "checks": {
            "stream_http": stream_http_check.as_dict(),
        },
    }
