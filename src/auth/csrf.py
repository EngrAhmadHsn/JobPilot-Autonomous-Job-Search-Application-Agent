"""Double-submit CSRF protection (WS-14 · A1).

**``fastapi-users`` v15 does not protect the cookie transport.** Its only
CSRF code is the OAuth ``state`` check, which does not apply to a
password login. So the control is written here, and it is written as a
**middleware** rather than as a per-route dependency — a per-route
dependency is a check that one of the routes will eventually forget, and
the routes are exactly where the mistake would be invisible.

**The mechanism.** Two values that must match:

- a ``csrf_token`` **cookie**, readable by JavaScript (deliberately *not*
  ``HttpOnly``);
- an ``X-CSRF-Token`` **header**, set by the client from that cookie.

The server compares them with :func:`secrets.compare_digest`. An
attacker on another origin can cause the browser to *send* the cookie,
but cannot read it, so cannot put the right value in the header.

**When it applies.** Only to a request that authenticates with the
**session cookie**:

- a request with the session cookie and an unsafe method must carry the
  header, or it is refused with a 403;
- a request that authenticates with a **bearer token** is exempt. A
  bearer token is not sent ambiently by a browser, so it is not a CSRF
  vector — and the CLI and the repo's scripts must keep working;
- a **safe** method (GET, HEAD, OPTIONS) is exempt: a safe method must
  not change state, so it cannot be the cross-site request that CSRF is
  about.

**The login endpoints are exempt.** A client that has never logged in has
no CSRF token to send, so requiring one at login would make logging in
impossible. (Login CSRF — being logged in as the *victim* — is a real but
minor attack, and it is answered here by the fact that a login always
produces a session for the account whose credentials were supplied, not
for the account the browser was already using.)

The cookie is issued on any response that does not already carry one, so
a page load is enough for the console to obtain it.
"""

from __future__ import annotations

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config.settings import get_settings

logger = logging.getLogger(__name__)

__all__ = ["CSRF_COOKIE_HEADER", "CSRFProtectionMiddleware"]

#: The header the client echoes the cookie value in.
CSRF_COOKIE_HEADER = "X-CSRF-Token"

#: The methods that cannot change state, and so need no CSRF token.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: The paths that are exempt: a client that has never logged in has no
#: token to send, so the login endpoints cannot require one.
DEFAULT_EXEMPT_PATHS: tuple[str, ...] = (
    "/api/auth/cookie/login",
    "/api/auth/token/login",
)


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """Refuse an unsafe, cookie-authenticated request with no CSRF token."""

    def __init__(
        self,
        app,
        *,
        cookie_name: str | None = None,
        header_name: str = CSRF_COOKIE_HEADER,
        exempt_paths: tuple[str, ...] = DEFAULT_EXEMPT_PATHS,
    ) -> None:
        super().__init__(app)
        self._cookie_name = cookie_name
        self._header_name = header_name
        self._exempt_paths = exempt_paths

    @property
    def cookie_name(self) -> str:
        return self._cookie_name or get_settings().auth_csrf_cookie_name

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() in SAFE_METHODS:
            response = await call_next(request)
            return self._ensure_cookie(request, response)

        if request.url.path in self._exempt_paths:
            response = await call_next(request)
            return self._ensure_cookie(request, response)

        # Only a request that carries the **session cookie** needs the
        # token. A bearer-authenticated request is not a CSRF vector.
        session_cookie = request.cookies.get(get_settings().auth_session_cookie_name)
        if not session_cookie:
            response = await call_next(request)
            return self._ensure_cookie(request, response)

        cookie_token = request.cookies.get(self.cookie_name)
        header_token = request.headers.get(self._header_name)
        if not cookie_token or not header_token:
            logger.warning(
                "Refused a CSRF-unprotected %s %s: no %s token",
                request.method,
                request.url.path,
                self._header_name,
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "The CSRF token is missing or invalid."},
            )
        if not secrets.compare_digest(cookie_token, header_token):
            logger.warning(
                "Refused a CSRF-unprotected %s %s: the token did not match",
                request.method,
                request.url.path,
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "The CSRF token is missing or invalid."},
            )

        response = await call_next(request)
        return self._ensure_cookie(request, response)

    def _ensure_cookie(self, request: Request, response: Response) -> Response:
        """Make sure the response carries a CSRF cookie.

        The cookie is **not** ``HttpOnly``: the console's JavaScript reads
        it and echoes it in the header. It grants nothing on its own —
        without the session cookie it is just a string.
        """
        if request.cookies.get(self.cookie_name):
            return response
        settings = get_settings()
        response.set_cookie(
            self.cookie_name,
            secrets.token_urlsafe(32),
            max_age=settings.auth_session_ttl_seconds,
            path="/",
            secure=settings.cookie_secure(),
            httponly=False,
            samesite="lax",
        )
        return response
