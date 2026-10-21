"""WS-06 · Phase C — the submission policy (SEC-05, plan §23).

Three policies exist. ``REQUIRE_APPROVAL`` is the default and the only one
that allows an application to be executed (and only after a human approval
record exists). ``PREPARE_ONLY`` forbids execution. ``AUTO_SUBMIT`` is defined
but **unreachable**: no code path may execute a submission under it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.config import settings as settings_module
from src.security import policy as policy_module
from src.security.policy import (
    VALID_POLICY_VALUES,
    AutoSubmitNotAllowed,
    PolicyError,
    SubmissionPolicy,
    assert_execution_allowed,
    get_submission_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class _FakeSettings:
    submission_policy: str = "REQUIRE_APPROVAL"


def _use_policy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr(
        settings_module, "get_settings", lambda: _FakeSettings(submission_policy=value)
    )


class TestPolicyEnum:
    def test_the_three_policies_exist(self) -> None:
        assert VALID_POLICY_VALUES == ("PREPARE_ONLY", "REQUIRE_APPROVAL", "AUTO_SUBMIT")

    def test_default_is_require_approval(self) -> None:
        assert settings_module.Settings().submission_policy == "REQUIRE_APPROVAL"

    def test_configured_policy_is_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_policy(monkeypatch, "PREPARE_ONLY")
        assert get_submission_policy() is SubmissionPolicy.PREPARE_ONLY

    def test_unknown_policy_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _use_policy(monkeypatch, "SUBMIT_WHEN_YOU_FEEL_LIKE_IT")
        with pytest.raises(PolicyError):
            get_submission_policy()


class TestExecutionGate:
    def test_require_approval_allows_execution(self) -> None:
        assert_execution_allowed(SubmissionPolicy.REQUIRE_APPROVAL)

    def test_prepare_only_forbids_execution(self) -> None:
        with pytest.raises(PolicyError):
            assert_execution_allowed(SubmissionPolicy.PREPARE_ONLY)

    def test_auto_submit_is_refused(self) -> None:
        with pytest.raises(AutoSubmitNotAllowed):
            assert_execution_allowed(SubmissionPolicy.AUTO_SUBMIT)

    def test_auto_submit_is_a_policy_error_too(self) -> None:
        # Callers that only know about PolicyError still catch it.
        assert issubclass(AutoSubmitNotAllowed, PolicyError)

    def test_policy_module_is_imported_by_the_settings_module(self) -> None:
        assert policy_module.SubmissionPolicy is SubmissionPolicy


def _import_app_subprocess(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **env_overrides}
    return subprocess.run(
        [sys.executable, "-c", "from src.main import app; print('startup-ok')"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
        check=False,
    )


class TestStartupFailsFastOnBadPolicy:
    def test_unknown_policy_refuses_to_start(self) -> None:
        result = _import_app_subprocess({"SUBMISSION_POLICY": "SUBMIT_EVERYTHING"})
        assert result.returncode != 0
        assert "SUBMISSION_POLICY" in result.stderr

    def test_known_policy_starts(self) -> None:
        result = _import_app_subprocess({"SUBMISSION_POLICY": "PREPARE_ONLY"})
        assert result.returncode == 0, result.stderr
        assert "startup-ok" in result.stdout
