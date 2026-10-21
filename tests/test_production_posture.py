"""WS-14 · Phase F — the production posture.

**The property under test:** a production deployment cannot start in an
unsafe configuration, and the documentation says what is true.

The configuration rules are checked **in a subprocess**, because the
point is that the application *refuses to start* — a check inside the
running process would be testing something else.

The documentation is checked mechanically too, because a runbook that
tells an operator to run a development server is a runbook that
deployed one.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = REPO_ROOT / "docs" / "RUNBOOK.md"
README = REPO_ROOT / "README.md"

#: A configuration that starts.
SAFE = {
    "APP_ENV": "production",
    "CORS_ORIGINS": "https://app.example.com",
    "AUTH_SECRET": "a" * 48,
    "SUBMISSION_POLICY": "REQUIRE_APPROVAL",
}


def _start(overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Try to import the application with *overrides* applied."""
    env = {**os.environ, **SAFE, **overrides}
    return subprocess.run(
        [sys.executable, "-c", "from src.main import app; print('startup-ok')"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=180,
        check=False,
    )


class TestTheProductionRules:
    def test_a_safe_configuration_starts(self) -> None:
        result = _start({})
        assert result.returncode == 0, result.stderr
        assert "startup-ok" in result.stdout

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({"CORS_ORIGINS": ""}, "CORS_ORIGINS"),
            ({"CORS_ORIGINS": "*"}, "wildcard"),
            ({"AUTH_SECRET": ""}, "AUTH_SECRET"),
            ({"AUTH_SECRET": "short"}, "AUTH_SECRET"),
            ({"AUTH_COOKIE_SECURE": "false"}, "Secure session cookie"),
            ({"SUBMISSION_POLICY": ""}, "SUBMISSION_POLICY"),
            ({"APP_DEBUG": "true"}, "APP_DEBUG"),
            ({"EMBEDDING_PROVIDER": "gemini", "LLM_API_KEY": ""}, "LLM_API_KEY"),
        ],
    )
    def test_an_unsafe_configuration_is_refused(
        self, overrides: dict[str, str], expected: str
    ) -> None:
        result = _start(overrides)
        assert result.returncode != 0, "the application started with an unsafe configuration"
        assert expected in result.stderr, result.stderr

    def test_the_development_defaults_are_not_refused(self) -> None:
        """The rules are production rules. A laptop must still work."""
        env = {**os.environ, "APP_ENV": "development"}
        for name in (
            "AUTH_SECRET",
            "SUBMISSION_POLICY",
            "CORS_ORIGINS",
            "APP_DEBUG",
        ):
            env.pop(name, None)
        result = subprocess.run(
            [sys.executable, "-c", "from src.main import app; print('startup-ok')"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            timeout=180,
            check=False,
        )
        assert result.returncode == 0, result.stderr


class TestTheRunbook:
    def test_the_runbook_exists(self) -> None:
        assert RUNBOOK.is_file(), f"{RUNBOOK} is missing"

    def test_the_runbook_has_no_development_server(self) -> None:
        """A runbook that names a development server is a runbook that
        deploys one."""
        text = RUNBOOK.read_text(encoding="utf-8")
        for forbidden in ("--reload", "APP_DEBUG=true", "reload"):
            # The runbook may *say* that it does not use them; what it
            # may not do is hand them to the operator as a command.
            for line in text.splitlines():
                if forbidden in line and line.strip().startswith(("uvicorn", "python", "env")):
                    raise AssertionError(
                        f"the runbook hands the operator a development server: {line!r}"
                    )

    def test_the_runbook_says_how_to_deploy(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8").lower()
        for topic in ("alembic upgrade head", "auth_secret", "cors_origins", "proxy"):
            assert topic in text, f"the runbook does not mention {topic!r}"

    def test_the_runbook_documents_the_purge(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        assert "purge_expired.py" in text


class TestTheReadmeSecuritySection:
    def test_the_security_section_states_the_authentication(self) -> None:
        text = README.read_text(encoding="utf-8")
        start = text.index("## Security posture")
        section = text[start : text.index("\n## ", start + 10)]
        assert "401" in section, "the security section does not say what an anonymous caller gets"
        assert "X-CSRF-Token" in section
        assert "owner_id" in section
        assert "404" in section and "403" in section

    def test_the_security_section_states_the_retention(self) -> None:
        text = README.read_text(encoding="utf-8")
        start = text.index("## Security posture")
        section = text[start : text.index("\n## ", start + 10)]
        assert "anonymize" in section.lower()
        assert "purge_expired.py" in section

    def test_the_readme_links_the_runbook(self) -> None:
        assert "docs/RUNBOOK.md" in README.read_text(encoding="utf-8")
