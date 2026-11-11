"""WS-26b · The board verifier.

Nothing in the project proved that a board had not renamed a field. The
circuit breaker catches a board that is **down**; a verifier catches a
board whose **shape changed** — the failure that produced the 0% field
population WS-23 set out to fix.

What each test pins, and why:

* a healthy board passes;
* **the dead-tenant trap**: a host that does not exist can answer 200
  with an HTML page, so the body must parse as JSON;
* a renamed id shape **fails**, because the canonical job ids are built
  from it — a rename silently breaks dedup and eviction;
* a transient DNS failure is a **SKIP**, not a FAIL, because a resolver
  blip must not make CI red;
* an empty board passes: it is a fact, not a fault.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import verify_sources as verify


def _response(monkeypatch, *, status: int, body: bytes):
    """Make the verifier's fetch return a fixed response."""
    monkeypatch.setattr(verify, "_fetch", lambda url, timeout: (status, body))


def _greenhouse_body(count: int = 3, *, job_id: str = "12345") -> bytes:
    return json.dumps(
        {"jobs": [{"id": job_id, "title": f"Job {i}"} for i in range(count)]}
    ).encode()


# ------------------------------------------------------------ the happy path


def test_a_healthy_board_passes(monkeypatch):
    _response(monkeypatch, status=200, body=_greenhouse_body(3))

    result = verify.verify_board("greenhouse", "stripe", timeout=1)

    assert result.status == verify.PASS
    assert result.jobs == 3


def test_an_empty_board_passes(monkeypatch):
    """A board with no openings is a fact, not a fault."""
    _response(monkeypatch, status=200, body=b'{"jobs": []}')

    result = verify.verify_board("greenhouse", "quiet", timeout=1)

    assert result.status == verify.PASS
    assert "empty" in result.detail
    assert result.jobs == 0


def test_a_lever_board_passes(monkeypatch):
    """Lever returns a bare array, not an object with a jobs key."""
    body = json.dumps([{"id": "ad208490-4052-4f91-a57e-433f2d1e484b"}]).encode()
    _response(monkeypatch, status=200, body=body)

    result = verify.verify_board("lever", "palantir", timeout=1)

    assert result.status == verify.PASS
    assert result.jobs == 1


# ------------------------------------------------------- the dead-tenant trap


def test_a_200_with_html_fails(monkeypatch):
    """The BambooHR trap: a tenant that does not exist answers 200 + HTML.

    A verifier that only checked the status code would call that board
    healthy, and every parser would then return nulls from an HTML page.
    """
    _response(
        monkeypatch,
        status=200,
        body=b"<!DOCTYPE html><html><body>Company not found</body></html>",
    )

    result = verify.verify_board("greenhouse", "gone", timeout=1)

    assert result.status == verify.FAIL
    assert "not JSON" in result.detail


def test_a_payload_with_no_job_list_fails(monkeypatch):
    """A JSON body of the wrong shape is still a failure."""
    _response(monkeypatch, status=200, body=b'{"data": []}')

    result = verify.verify_board("greenhouse", "odd", timeout=1)

    assert result.status == verify.FAIL
    assert "no job list" in result.detail


# ------------------------------------------------------------ the id shape


def test_a_renamed_id_shape_fails(monkeypatch):
    """The canonical job ids are built from the provider's id.

    A rename here does not crash anything — it silently changes every
    id, which breaks dedup and the eviction's identity. So it is a FAIL,
    not a note.
    """
    _response(monkeypatch, status=200, body=_greenhouse_body(1, job_id=None))

    result = verify.verify_board("greenhouse", "odd", timeout=1)

    assert result.status == verify.FAIL
    assert "id" in result.detail


def test_a_lever_id_that_is_not_a_uuid_fails(monkeypatch):
    """Lever posting ids are UUIDs; a changed shape means a changed API."""
    body = json.dumps([{"id": "not-a-uuid"}]).encode()
    _response(monkeypatch, status=200, body=body)

    result = verify.verify_board("lever", "odd", timeout=1)

    assert result.status == verify.FAIL
    assert "UUID" in result.detail


# --------------------------------------------------------------- the statuses


def test_a_404_fails(monkeypatch):
    """A slug that does not exist is a dead board, not a warning."""
    _response(monkeypatch, status=404, body=b'{"status":404}')

    result = verify.verify_board("greenhouse", "notaboard", timeout=1)

    assert result.status == verify.FAIL
    assert "does not exist" in result.detail


def test_a_500_fails(monkeypatch):
    _response(monkeypatch, status=500, body=b"oops")

    result = verify.verify_board("greenhouse", "broken", timeout=1)

    assert result.status == verify.FAIL
    assert "HTTP 500" in result.detail


def test_a_dns_failure_is_a_skip_not_a_fail(monkeypatch):
    """A resolver blip must not make CI red.

    The board may be perfectly healthy; the network is not.
    """
    import urllib.error

    def explode(url, timeout):
        raise urllib.error.URLError(OSError("Name or service not known: does not resolve"))

    monkeypatch.setattr(verify, "_fetch", explode)

    result = verify.verify_board("greenhouse", "stripe", timeout=1)

    assert result.status == verify.SKIP
    assert "DNS" in result.detail


def test_a_timeout_is_a_skip(monkeypatch):
    def explode(url, timeout):
        raise TimeoutError()

    monkeypatch.setattr(verify, "_fetch", explode)

    result = verify.verify_board("greenhouse", "slow", timeout=1)

    assert result.status == verify.SKIP


def test_an_unknown_provider_is_skipped():
    """A provider with no verifier is skipped, not failed."""
    result = verify.verify_board("workday", "acme", timeout=1)

    assert result.status == verify.SKIP
    assert "no verifier" in result.detail


# ------------------------------------------------------------------ the main


def test_the_main_exits_nonzero_when_a_board_fails(monkeypatch, capsys):
    monkeypatch.setattr(verify, "_registered_boards", lambda ats: [("greenhouse", "broken")])
    _response(monkeypatch, status=404, body=b"{}")

    assert verify.main(["--json"]) == 1


def test_the_main_exits_zero_when_every_board_passes(monkeypatch):
    monkeypatch.setattr(verify, "_registered_boards", lambda ats: [("greenhouse", "stripe")])
    _response(monkeypatch, status=200, body=_greenhouse_body(2))

    assert verify.main(["--json"]) == 0


def test_the_main_reports_machine_readably(monkeypatch, capsys):
    monkeypatch.setattr(verify, "_registered_boards", lambda ats: [("greenhouse", "stripe")])
    _response(monkeypatch, status=200, body=_greenhouse_body(2))

    verify.main(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["passed"] == 1
    assert payload["failed"] == 0
    assert payload["results"][0]["slug"] == "stripe"


def test_the_main_with_no_boards_exits_nonzero(monkeypatch):
    monkeypatch.setattr(verify, "_registered_boards", lambda ats: [])

    assert verify.main([]) == 1


def test_the_seed_comes_from_the_environment_when_the_registry_is_empty(monkeypatch):
    """A fresh checkout has no registry; the env lists are the seed."""
    monkeypatch.setenv("GREENHOUSE_BOARDS", "stripe,figma")
    monkeypatch.setenv("LEVER_COMPANIES", "palantir")
    monkeypatch.setenv("ASHBY_ORGS", "openai")

    boards = verify._env_seed()

    assert ("greenhouse", "stripe") in boards
    assert ("greenhouse", "figma") in boards
    assert ("lever", "palantir") in boards
    assert ("ashby", "openai") in boards
