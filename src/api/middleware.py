"""API middleware: abuse limits, body caps, and response hardening (WS-12).

Four controls, one module, because they are four facets of the same
question — *what may an untrusted caller make this process do?*

1. **Rate limiting** (:class:`RateLimitMiddleware`) — a per-client request
   budget. The API has no authentication, so this is the only thing standing
   between a script and a saturated process.
2. **Body-size cap** (:class:`BodySizeLimitMiddleware`) — a request body
   larger than the cap is refused *before* it is read. The resume upload
   validates its 5 MB file cap only after the multipart parser has already
   spooled the whole body to disk, so without this a 10 GB upload costs the
   server 10 GB of disk before the validator ever sees it.
3. **Concurrency gate** (:class:`ConcurrencyLimitMiddleware`) — the
   expensive endpoints (the refresh, the search, the tailoring) may not run
   more than a few at once. A rate limit bounds how *often* the refresh runs;
   this bounds how many run *at the same time*, which is what actually
   exhausts the CPU and the memory.
4. **Security headers** (:class:`SecurityHeadersMiddleware`) — the response
   headers that stop a browser treating this API's output as something it
   is not. ``X-Content-Type-Options: nosniff`` is the load-bearing one: a
   JSON response carrying attacker-controlled job descriptions must never be
   re-interpreted as HTML by a sniffing browser.

The headers are applied to **every** response, including the error responses
the middleware itself produces, so a 429 is as well-formed as a 200.
"""

from __future__ import annotations

import logging
import threading
from typing import ClassVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.security.limits import get_limits
from src.security.rate_limit import RateLimiter, client_address

logger = logging.getLogger(__name__)

__all__ = [
    "BodySizeLimitMiddleware",
    "ConcurrencyLimitMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    "get_rate_limiter",
    "heavy_path_matcher",
    "reset_rate_limiter",
]


#: Paths that may not be executed more than ``max_concurrent_heavy`` at once.
#: Matched as a prefix: the refresh and the search both walk the whole
#: corpus, and the tailoring calls the model.
HEAVY_PATH_PREFIXES: tuple[str, ...] = (
    "/api/jobs/refresh",
    "/api/jobs/search",
    "/api/tailor",
)


def heavy_path_matcher(path: str) -> bool:
    """True when *path* is one of the expensive endpoints."""
    return any(path.startswith(prefix) for prefix in HEAVY_PATH_PREFIXES)


# -- rate limiting ------------------------------------------------------------


_limiter: RateLimiter | None = None
_limiter_lock = threading.Lock()


def get_rate_limiter() -> RateLimiter:
    """The process-wide rate limiter (built on first use)."""
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                limits = get_limits()
                _limiter = RateLimiter(
                    limits.rate_limit_requests,
                    limits.rate_limit_window_seconds,
                )
    return _limiter


def reset_rate_limiter() -> None:
    """Drop the process-wide limiter (the next call rebuilds it)."""
    global _limiter
    with _limiter_lock:
        _limiter = None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Refuse requests beyond a client's budget with 429 and ``Retry-After``."""

    def __init__(self, app: ASGIApp, limiter: RateLimiter | None = None) -> None:
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next):
        limiter = self._limiter or get_rate_limiter()
        decision = limiter.check(client_address(request))
        if not decision.allowed:
            logger.warning(
                "Rate limit exceeded for %s %s (limit %d per window)",
                request.method,
                request.url.path,
                decision.limit,
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please retry later."},
                headers={
                    "Retry-After": str(max(1, int(decision.retry_after) + 1)),
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response


# -- body size ----------------------------------------------------------------


class BodySizeLimitMiddleware:
    """Refuse a request body larger than the cap with 413.

    Implemented as raw ASGI rather than as a ``BaseHTTPMiddleware`` so it can
    wrap the ``receive`` channel: the body is counted as it streams in, and
    the connection is cut the moment the cap is passed. Checking
    ``Content-Length`` alone would not be enough — a request that omits it
    (or lies about it) would still be read in full.

    A declared ``Content-Length`` above the cap is refused without reading
    the body at all, which is the common case and the cheapest.
    """

    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self._max_bytes = max_bytes

    @property
    def max_bytes(self) -> int:
        """The effective cap (from the limits module unless overridden)."""
        if self._max_bytes is not None:
            return self._max_bytes
        return get_limits().body_limit_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_bytes = self.max_bytes
        declared = _declared_content_length(scope)
        if declared is not None and declared > max_bytes:
            await _send_error(
                scope,
                send,
                status_code=413,
                detail=f"Request body exceeds the {max_bytes} byte limit",
            )
            return

        received = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise _BodyTooLarge()
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _BodyTooLarge:
            logger.warning("Request body exceeded the %d byte limit; refused", max_bytes)
            if response_started:
                # The application already began its response; the status
                # cannot be changed now. Cut the body short so the client
                # sees a truncated, failed request rather than a valid one.
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
            await _send_error(
                scope,
                send,
                status_code=413,
                detail=f"Request body exceeds the {max_bytes} byte limit",
            )


class _BodyTooLarge(Exception):
    """Raised inside the receive channel when the body cap is passed."""


def _declared_content_length(scope: Scope) -> int | None:
    """The declared body length of the request, when it declares one."""
    for key, value in scope.get("headers", ()):
        if key == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _send_error(scope: Scope, send: Send, *, status_code: int, detail: str) -> None:
    """Send a JSON error response on a raw ASGI scope."""
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    await response(scope, _empty_receive, send)


async def _empty_receive() -> Message:
    """A receive channel that yields the end-of-body message."""
    return {"type": "http.request", "body": b"", "more_body": False}


# -- concurrency --------------------------------------------------------------


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """Bound how many expensive endpoints run at the same time.

    The gate is non-blocking: when the limit is reached the request is
    refused with 503 immediately rather than queued. Queueing would keep the
    work in memory and let the pile-up grow without bound, which is the
    opposite of what the limit is for.
    """

    def __init__(self, app: ASGIApp, max_concurrent: int | None = None) -> None:
        super().__init__(app)
        self._max_concurrent = max_concurrent
        self._semaphore = threading.Semaphore(
            self._max_concurrent if self._max_concurrent is not None else 2
        )

    @property
    def max_concurrent(self) -> int:
        """The effective concurrency cap."""
        if self._max_concurrent is not None:
            return self._max_concurrent
        return get_limits().max_concurrent_heavy

    async def dispatch(self, request: Request, call_next):
        if not heavy_path_matcher(request.url.path):
            return await call_next(request)

        if not self._semaphore.acquire(blocking=False):
            logger.warning(
                "Refused %s %s: %d heavy requests already running",
                request.method,
                request.url.path,
                self.max_concurrent,
            )
            return JSONResponse(
                status_code=503,
                content={"detail": "Server busy. Please retry shortly."},
                headers={"Retry-After": "5"},
            )
        try:
            return await call_next(request)
        finally:
            self._semaphore.release()


# -- response headers --------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add the response headers that stop a browser misreading the output.

    ``X-Content-Type-Options: nosniff`` is the one that matters most here:
    job descriptions are attacker-controlled text that this API returns
    verbatim, and without ``nosniff`` a browser is free to decide that a
    JSON response is really HTML and execute it. The rest are cheap
    defence in depth.
    """

    #: Headers applied to every response.
    HEADERS: ClassVar[dict[str, str]] = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Opener-Policy": "same-origin",
        # No Content-Security-Policy here on purpose: this API returns JSON
        # that other origins fetch, and a CSP on a JSON response is inert.
        # The API's own HTML surface is the docs page, which is disabled
        # outside development (see src/main.py).
    }

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        for header, value in self.HEADERS.items():
            response.headers.setdefault(header, value)
        return response
