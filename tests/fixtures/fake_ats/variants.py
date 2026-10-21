"""The fake-ATS variant server (WS-08).

A small FastAPI application that serves the page variants the browser layer
has to survive: a wizard, widget controls, an unknown question, a form the
server rejects, a challenge, and a page that demands a file.

It is served by uvicorn on an **ephemeral port** in a background thread, and
it is the *only* thing the browser talks to in these tests.

Two routes exist purely for the tests' benefit:

``GET /_last``
    the last request the server received — its path, its method, the cookie
    header it carried and the files it uploaded. It is how a test asserts a
    *negative*: that the challenge page was never posted to, that the unknown
    question was never answered, that the second run carried no cookie.
``GET /session``
    sets a cookie and reports the one it was given — the isolation probe.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import pages

logger = logging.getLogger(__name__)


class _ServerState:
    """What the server remembers between two requests."""

    def __init__(self) -> None:
        self.last: dict[str, Any] = {}
        self.requests: list[dict[str, Any]] = []
        self.submissions: list[dict[str, Any]] = []
        self.references = 0
        self.recoverable_attempts = 0

    def next_reference(self) -> str:
        """A fresh confirmation reference."""
        self.references += 1
        return f"FAKE-ATS-{self.references:04d}"


def create_app() -> FastAPI:
    """The fake-ATS application."""
    app = FastAPI(title="Fake ATS (WS-08)")
    state = _ServerState()
    app.state.server_state = state

    @app.middleware("http")
    async def record_request(request: Request, call_next):
        """Remember the request, so a test can assert what did *not* happen."""
        if request.url.path != "/_last":
            record = {
                "path": request.url.path,
                "method": request.method,
                "cookie": request.headers.get("cookie", ""),
                "files": [],
            }
            state.last = record
            state.requests.append(record)
        return await call_next(request)

    # -- the inspection route ------------------------------------------------

    @app.get("/_last")
    async def last_request() -> JSONResponse:
        """The last request the server received."""
        return JSONResponse(state.last)

    @app.get("/_requests")
    async def all_requests() -> JSONResponse:
        """Every request the server has received, in order."""
        return JSONResponse(state.requests)

    @app.get("/_submissions")
    async def submissions() -> JSONResponse:
        """Every submission the server has accepted."""
        return JSONResponse(state.submissions)

    # -- the single-page form ------------------------------------------------

    @app.get("/basic", response_class=HTMLResponse)
    async def basic() -> HTMLResponse:
        """The regression baseline: one page, one submit."""
        return HTMLResponse(pages.basic_form())

    @app.post("/basic")
    async def basic_submit(request: Request) -> HTMLResponse:
        """Accept the single-page application."""
        form = await request.form()
        _record_submission(state, form)
        return HTMLResponse(pages.confirmation_page(state.next_reference()))

    # -- the wizard ----------------------------------------------------------

    @app.get("/multipage", response_class=HTMLResponse)
    async def multipage() -> HTMLResponse:
        """Step 1 of the three-step form."""
        return HTMLResponse(pages.multipage_step1())

    @app.post("/multipage/step2")
    async def multipage_step2(request: Request) -> HTMLResponse:
        """Step 2 — the experience questions."""
        form = await request.form()
        return HTMLResponse(pages.multipage_step2(**_values(form)))

    @app.get("/multipage/step2", response_class=HTMLResponse)
    async def multipage_step2_get() -> HTMLResponse:
        """Step 2 on its own."""
        return HTMLResponse(pages.multipage_step2())

    @app.post("/multipage/step3")
    async def multipage_step3(request: Request) -> HTMLResponse:
        """Step 3 — the review."""
        form = await request.form()
        return HTMLResponse(pages.multipage_step3(**_values(form)))

    @app.get("/multipage/step3", response_class=HTMLResponse)
    async def multipage_step3_get() -> HTMLResponse:
        """Step 3 on its own."""
        return HTMLResponse(pages.multipage_step3())

    @app.post("/multipage/submit")
    async def multipage_submit(request: Request) -> HTMLResponse:
        """The last step of the wizard."""
        form = await request.form()
        _record_submission(state, form)
        return HTMLResponse(pages.confirmation_page(state.next_reference()))

    # -- the widgets ---------------------------------------------------------

    @app.get("/widgets", response_class=HTMLResponse)
    async def widgets() -> HTMLResponse:
        """A select, a checkbox and a radio group."""
        return HTMLResponse(pages.widgets_form())

    @app.post("/widgets")
    async def widgets_submit(request: Request) -> HTMLResponse:
        """Accept the widget application."""
        form = await request.form()
        _record_submission(state, form)
        return HTMLResponse(pages.confirmation_page(state.next_reference()))

    # -- the unknown question ------------------------------------------------

    @app.get("/unknown", response_class=HTMLResponse)
    async def unknown() -> HTMLResponse:
        """A page with a question the field map does not know."""
        return HTMLResponse(pages.unknown_form())

    @app.post("/unknown")
    async def unknown_submit(request: Request) -> HTMLResponse:
        """Accept the application (the agent must never get here)."""
        form = await request.form()
        _record_submission(state, form)
        return HTMLResponse(pages.confirmation_page(state.next_reference()))

    # -- the validation errors -----------------------------------------------

    @app.get("/validation", response_class=HTMLResponse)
    async def validation() -> HTMLResponse:
        """A form the server always rejects."""
        return HTMLResponse(pages.validation_form())

    @app.post("/validation")
    async def validation_submit(request: Request) -> HTMLResponse:
        """Reject the application — the prepared data cannot fix this."""
        await request.form()
        return HTMLResponse(
            pages.validation_form(
                "We could not verify your email address. Please use your personal address."
            )
        )

    @app.get("/validation-recoverable", response_class=HTMLResponse)
    async def validation_recoverable() -> HTMLResponse:
        """A form the server rejects only the first time."""
        return HTMLResponse(pages.validation_form(action="/validation-recoverable"))

    @app.post("/validation-recoverable")
    async def validation_recoverable_submit(request: Request) -> HTMLResponse:
        """Reject the first attempt, accept the second."""
        form = await request.form()
        state.recoverable_attempts += 1
        if state.recoverable_attempts == 1:
            return HTMLResponse(
                pages.validation_form(
                    "Your session expired. Please submit the form again.",
                    action="/validation-recoverable",
                )
            )
        _record_submission(state, form)
        return HTMLResponse(pages.confirmation_page(state.next_reference()))

    # -- the challenge -------------------------------------------------------

    @app.get("/captcha", response_class=HTMLResponse)
    async def captcha() -> HTMLResponse:
        """A page with a CAPTCHA. The flow must stop here."""
        return HTMLResponse(pages.captcha_page())

    # -- the file upload -----------------------------------------------------

    @app.get("/upload-required", response_class=HTMLResponse)
    async def upload_required() -> HTMLResponse:
        """A form whose file input is required."""
        return HTMLResponse(pages.upload_required_form())

    @app.post("/upload-required")
    async def upload_required_submit(request: Request) -> HTMLResponse:
        """Accept the application only when a file arrived."""
        form = await request.form()
        filenames = _filenames(form)
        state.last["files"] = filenames
        if not filenames:
            return HTMLResponse(
                pages.upload_required_form("Please attach your resume before submitting.")
            )
        _record_submission(state, form)
        return HTMLResponse(pages.confirmation_page(state.next_reference()))

    # -- the outcomes --------------------------------------------------------

    @app.get("/submitted", response_class=HTMLResponse)
    async def submitted() -> HTMLResponse:
        """The confirmation page."""
        return HTMLResponse(pages.confirmation_page(state.next_reference()))

    @app.get("/error", response_class=HTMLResponse)
    async def error() -> HTMLResponse:
        """A page that confirms nothing."""
        return HTMLResponse(pages.failure_page())

    # -- the session probe ---------------------------------------------------

    @app.get("/session", response_class=HTMLResponse)
    async def session(request: Request) -> Response:
        """Set a cookie and report the one that was sent."""
        received = request.headers.get("cookie", "")
        response = HTMLResponse(pages.session_page(received or None))
        response.set_cookie("ats_session", state.next_reference(), httponly=True, samesite="lax")
        return response

    @app.post("/session", response_class=HTMLResponse)
    async def session_post(request: Request) -> HTMLResponse:
        """The session probe's button: it echoes the storage marker back."""
        form = await request.form()
        marker = form.get("marker")
        marker = marker if isinstance(marker, str) else "none"
        return HTMLResponse(pages.confirmation_page(state.next_reference(), marker=marker))

    return app


def _values(form: Any) -> dict[str, str]:
    """The submitted values, as plain strings."""
    values: dict[str, str] = {}
    for key in form:
        value = form.get(key)
        if isinstance(value, str):
            values[key] = value
    return values


def _filenames(form: Any) -> list[str]:
    """The names of the files that were uploaded."""
    names: list[str] = []
    for key in form:
        value = form.get(key)
        filename = getattr(value, "filename", None)
        if filename:
            names.append(filename)
    return names


def _record_submission(state: _ServerState, form: Any) -> None:
    """Remember a submission."""
    state.submissions.append(_values(form))
    state.last["files"] = _filenames(form)


@contextmanager
def serve_fake_ats_variants() -> Iterator[str]:
    """Serve the variant app on a free localhost port.

    Yields:
        The base URL of the running server.
    """
    app = create_app()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        lifespan="off",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = _wait_for_port(server)
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _wait_for_port(server: uvicorn.Server, timeout: float = 20.0) -> str:
    """The base URL of a started server, or a timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server.started:
            for bound in server.servers or []:
                for sock in bound.sockets or []:
                    host, port = sock.getsockname()[:2]
                    if port:
                        return f"http://{host}:{port}"
        time.sleep(0.05)
    raise RuntimeError("The fake ATS server did not start in time")
