"""A local fake ATS for the end-to-end verification runs (WS-06).

The fake ATS is a tiny HTTP server that serves three pages:

- ``/apply`` — a form with the fields the fake-ATS adapter fills;
- ``/apply/confirm`` — the confirmation page the adapter verifies;
- ``/challenge`` — a page that presents a CAPTCHA (the flow must stop
  there, and the challenge must never be solved).

It exists so the security controls can be exercised against a **real
browser** instead of a mock: the allowlist check before the navigation, the
redirect check after it, the challenge stop, and the evidence artifacts on
disk.

WS-08 moved this file into the ``fake_ats`` package and added the ``<label>``
elements to the form, so the adapter can find the controls through the
accessibility tree. The ids, the routes and the behaviour are unchanged.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FORM_HTML = """<!doctype html>
<html>
  <head><title>Apply — Acme Labs</title></head>
  <body>
    <h1>Apply for Backend Engineer</h1>
    <form method="post" action="/apply/confirm" enctype="multipart/form-data">
      <label for="candidate-name">Full name</label>
      <input id="candidate-name" name="candidate_name" type="text" />
      <label for="email">Email address</label>
      <input id="email" name="email" type="text" />
      <label for="phone">Phone number</label>
      <input id="phone" name="phone" type="text" />
      <label for="cover-letter">Cover letter</label>
      <textarea id="cover-letter" name="cover_letter"></textarea>
      <label for="resume">Resume</label>
      <input id="resume" name="resume" type="file" />
      <button type="submit">Submit application</button>
    </form>
  </body>
</html>
"""

CONFIRMATION_HTML = """<!doctype html>
<html>
  <head><title>Application received</title></head>
  <body>
    <h1>Application Submitted</h1>
    <p>Thanks for applying. We received your application for Backend Engineer.</p>
    <p>Confirmation id: FAKE-ATS-0001</p>
  </body>
</html>
"""

CHALLENGE_HTML = """<!doctype html>
<html>
  <head><title>Just a moment...</title></head>
  <body>
    <h1>Verify you are human</h1>
    <p>Please complete the CAPTCHA to continue.</p>
    <iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>
  </body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    """Serves the three fake-ATS pages."""

    def log_message(self, format: str, *args) -> None:
        return None  # keep the verification output clean

    def _respond(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path in ("/", "/apply"):
            self._respond(FORM_HTML)
        elif path == "/apply/confirm":
            self._respond(CONFIRMATION_HTML)
        elif path == "/challenge":
            self._respond(CHALLENGE_HTML)
        else:
            self._respond("<html><body>Not found</body></html>", status=404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self._respond(CONFIRMATION_HTML)


@contextmanager
def serve_fake_ats() -> Iterator[str]:
    """Serve the fake ATS on a free localhost port.

    Yields:
        The base URL of the running server.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
