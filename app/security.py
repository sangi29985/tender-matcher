"""Request-level protection: cross-site request checks, security headers, sign-in throttling."""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Browsers cannot attach a custom header to a cross-site form post, so requiring one on every
# state-changing API call blocks cross-site request forgery on top of SameSite cookies.
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "tender-matcher"
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts: bool = False):
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next):
        if (
            request.method in _UNSAFE
            and request.url.path.startswith("/api/")
            and request.headers.get(CSRF_HEADER) != CSRF_VALUE
        ):
            return JSONResponse({"detail": "Missing request header"}, status_code=403)
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if self.hsts:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


class LoginThrottle:
    """Counts recent failed sign-ins per email and per client address (single process)."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _recent(self, key: str, window: float) -> deque[float]:
        attempts = self._failures[key]
        cutoff = time.monotonic() - window
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        return attempts

    def blocked(self, keys: list[str], limit: int, window: float) -> bool:
        with self._lock:
            return any(len(self._recent(key, window)) >= limit for key in keys)

    def failed(self, keys: list[str]) -> None:
        with self._lock:
            now = time.monotonic()
            for key in keys:
                self._failures[key].append(now)

    def succeeded(self, keys: list[str]) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)


login_throttle = LoginThrottle()
