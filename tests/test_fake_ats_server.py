"""WS-08 · Phase B — the fake ATS serves what it claims.

The browser layer is only as good as the pages it is tested against, so the
pages themselves are pinned: the routes answer, the labels are semantic, and
the WS-06 server still behaves exactly as it did.
"""

from __future__ import annotations

import httpx
import pytest

from tests.fixtures.fake_ats import serve_fake_ats, serve_fake_ats_variants


@pytest.fixture(scope="module")
def ats():
    """The variant server, running for the whole module."""
    with serve_fake_ats_variants() as base_url:
        yield base_url


@pytest.mark.parametrize(
    "path",
    [
        "/basic",
        "/multipage",
        "/widgets",
        "/unknown",
        "/validation",
        "/validation-recoverable",
        "/captcha",
        "/upload-required",
        "/submitted",
        "/error",
        "/session",
    ],
)
def test_every_variant_route_answers(ats: str, path: str) -> None:
    response = httpx.get(f"{ats}{path}", timeout=10)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text


def test_the_pages_carry_real_labels(ats: str) -> None:
    body = httpx.get(f"{ats}/basic", timeout=10).text

    assert '<label for="candidate_name">Full name</label>' in body
    assert '<label for="email">Email address</label>' in body
    assert '<label for="phone">Phone number</label>' in body


def test_the_widget_page_carries_a_select_a_checkbox_and_a_radio_group(ats: str) -> None:
    body = httpx.get(f"{ats}/widgets", timeout=10).text

    assert '<select id="country"' in body
    assert '<input type="checkbox" id="work_authorization"' in body
    assert "<legend>Work mode</legend>" in body
    assert '<input type="radio" id="work_mode_remote"' in body


def test_the_confirmation_page_confirms_and_the_error_page_does_not(ats: str) -> None:
    from src.applications.fake_ats_adapter import CONFIRMATION_MARKERS

    confirmation = httpx.get(f"{ats}/submitted", timeout=10).text.lower()
    failure = httpx.get(f"{ats}/error", timeout=10).text.lower()

    assert any(marker in confirmation for marker in CONFIRMATION_MARKERS)
    assert not any(marker in failure for marker in CONFIRMATION_MARKERS)


def test_the_server_remembers_the_last_request(ats: str) -> None:
    httpx.get(f"{ats}/basic", timeout=10)

    last = httpx.get(f"{ats}/_last", timeout=10).json()

    assert last["path"] == "/basic"
    assert last["method"] == "GET"
    assert last["cookie"] == ""


def test_the_validation_route_rejects_the_submission(ats: str) -> None:
    response = httpx.post(f"{ats}/validation", data={"candidate_name": "Ada"}, timeout=10)

    assert 'role="alert"' in response.text
    assert "Application Submitted" not in response.text


def test_the_recoverable_validation_route_accepts_the_second_attempt(ats: str) -> None:
    first = httpx.post(f"{ats}/validation-recoverable", data={"candidate_name": "Ada"}, timeout=10)
    second = httpx.post(f"{ats}/validation-recoverable", data={"candidate_name": "Ada"}, timeout=10)

    assert 'role="alert"' in first.text
    assert "Application Submitted" in second.text


def test_the_upload_route_rejects_a_submission_without_a_file(ats: str) -> None:
    response = httpx.post(f"{ats}/upload-required", data={"candidate_name": "Ada"}, timeout=10)

    assert 'role="alert"' in response.text


def test_the_upload_route_accepts_a_submission_with_a_file(ats: str) -> None:
    response = httpx.post(
        f"{ats}/upload-required",
        data={"candidate_name": "Ada"},
        files={"resume": ("resume.txt", b"a resume", "text/plain")},
        timeout=10,
    )

    assert "Application Submitted" in response.text


def test_the_session_route_sets_a_cookie(ats: str) -> None:
    response = httpx.get(f"{ats}/session", timeout=10)

    assert "ats_session" in response.headers.get("set-cookie", "")


def test_the_ws06_server_still_serves_its_three_pages() -> None:
    with serve_fake_ats() as base_url:
        form = httpx.get(f"{base_url}/apply", timeout=10).text
        confirmation = httpx.get(f"{base_url}/apply/confirm", timeout=10).text
        challenge = httpx.get(f"{base_url}/challenge", timeout=10).text

    # The ids are unchanged...
    assert 'id="candidate-name"' in form
    assert 'id="email"' in form
    # ...and the labels are there for the semantic adapter.
    assert '<label for="candidate-name">Full name</label>' in form
    assert "Application Submitted" in confirmation
    assert "captcha" in challenge.lower()
