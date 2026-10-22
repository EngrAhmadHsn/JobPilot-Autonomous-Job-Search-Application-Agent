"""WS-14 · Phase E — the CI gate.

**The property under test:** the controls are in CI. An isolation
control that is not in CI is a control that decays, and a rule that is
not enforced is a comment.

What is proved here:

- the workflow exists, is valid YAML, and runs the whole gate: the
  linter, the **whole** test suite (the two-user isolation matrix
  included), the migration check and the dependency audit;
- the migration check runs green, against the real Alembic chain;
- the dependency audit's exception list is **well-formed**: every
  group names a package the project depends on, every group states a
  reason, and no id is listed twice.

The exception list is the part that decays fastest, so it is checked
mechanically rather than by review alone.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
IGNORE_FILE = REPO_ROOT / "security" / "dependency-audit-ignores.txt"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


# -- the workflow --------------------------------------------------------------


class TestTheWorkflow:
    def test_the_workflow_exists(self) -> None:
        assert WORKFLOW.is_file(), f"{WORKFLOW} is missing"

    def test_the_workflow_is_valid_yaml(self) -> None:
        import yaml

        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        assert isinstance(document, dict)
        assert "jobs" in document

    def test_the_workflow_runs_on_every_push(self) -> None:
        import yaml

        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        triggers = document.get("on") or document.get(True)  # "on" is a YAML boolean
        assert "push" in triggers
        assert "pull_request" in triggers

    def test_the_gate_runs_the_whole_suite(self) -> None:
        """Not a subset: the isolation matrix is part of the suite."""
        import yaml

        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = document["jobs"]["gate"]["steps"]
        commands = " ".join(str(step.get("run", "")) for step in steps)
        assert "pytest tests" in commands, "the gate does not run the whole suite"
        assert "-q" in commands

    def test_the_gate_runs_the_linter(self) -> None:
        import yaml

        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = document["jobs"]["gate"]["steps"]
        commands = " ".join(str(step.get("run", "")) for step in steps)
        assert "ruff check src tests scripts" in commands

    def test_the_gate_runs_the_migration_check(self) -> None:
        import yaml

        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = document["jobs"]["gate"]["steps"]
        commands = " ".join(str(step.get("run", "")) for step in steps)
        assert "verify_migrations.py" in commands

    def test_the_gate_runs_the_dependency_audit(self) -> None:
        import yaml

        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = document["jobs"]["gate"]["steps"]
        commands = " ".join(str(step.get("run", "")) for step in steps)
        assert "audit_dependencies.py" in commands

    def test_the_browser_suite_gets_a_browser(self) -> None:
        """The browser tests need a real Chromium, and a separate job."""
        import yaml

        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        assert "browser" in document["jobs"]
        steps = document["jobs"]["browser"]["steps"]
        commands = " ".join(str(step.get("run", "")) for step in steps)
        assert "playwright install" in commands


class TestTheBrowserTests:
    """The browser tests, and the browser they need.

    The gate once ran the **whole** suite in a job that did not install
    Chromium, and sixteen browser tests died on a runner with no browser
    binary. These checks are the mechanical version of that lesson.
    """

    def _commands(self, job: str) -> str:
        import yaml

        document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = document["jobs"][job]["steps"]
        return " ".join(str(step.get("run", "")) for step in steps)

    def test_both_jobs_install_chromium(self) -> None:
        """The gate installs it as insurance, so an unmarked browser test
        still passes there rather than dying on a missing binary."""
        for job in ("gate", "browser"):
            assert "playwright install" in self._commands(job), (
                f"the {job} job does not install a browser"
            )

    def test_the_browser_job_selects_by_the_marker(self) -> None:
        """Not by a hand-written list of files: a list goes stale, and a
        stale list is a test that quietly stops running."""
        commands = self._commands("browser")
        assert "-m browser" in commands
        assert "tests/test_browser_variants.py" not in commands, (
            "the browser job names files instead of selecting the marker — "
            "a new browser test would not run"
        )

    def test_the_gate_excludes_the_browser_tests(self) -> None:
        commands = self._commands("gate")
        assert '-m "not browser"' in commands

    def test_the_marker_is_registered(self) -> None:
        """An unregistered marker is a warning, not an error — and a
        warning is not a guard."""
        import tomllib

        pyproject = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )
        markers = pyproject["tool"]["pytest"]["ini_options"]["markers"]
        assert any(marker.startswith("browser:") for marker in markers)

    def test_the_browser_tests_are_marked(self) -> None:
        """The files that drive a real browser carry the marker.

        The list is the one the suite itself proved: with the browser
        binaries pointed at an empty directory, exactly these two files
        failed. A new browser test that is not marked still passes in the
        gate job (Chromium is installed there), but it belongs here.
        """
        marked = set()
        for path in (Path(__file__).parent).glob("test_*.py"):
            if path.name == Path(__file__).name:
                # This file names the marker in its own assertions.
                continue
            if "pytest.mark.browser" in path.read_text(encoding="utf-8"):
                marked.add(path.name)
        assert marked == {"test_browser_variants.py", "test_isolation.py"}


# -- the migration check -------------------------------------------------------


class TestTheMigrationCheck:
    def test_the_script_runs_green(self) -> None:
        """The check runs the real Alembic chain, both ways."""
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "verify_migrations.py")],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=600,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "the migrations apply, reverse, and preserve the data" in result.stdout


# -- the dependency audit's exception list --------------------------------------


class TestTheExceptionList:
    def test_the_list_is_well_formed(self) -> None:
        import audit_dependencies

        problems = audit_dependencies.check_the_list()
        assert not problems, "\n".join(problems)

    def test_every_group_states_a_reason(self) -> None:
        import audit_dependencies

        groups = audit_dependencies.parse_ignores()
        assert groups, "the exception list is empty"
        text = IGNORE_FILE.read_text(encoding="utf-8")
        for package in groups:
            header = f"[{package}]"
            index = text.index(header)
            tail = text[index + len(header) :].splitlines()
            assert any(line.strip().startswith("#") for line in tail), (
                f"the {package} group has no stated reason"
            )

    def test_no_id_is_listed_twice(self) -> None:
        import audit_dependencies

        ids = audit_dependencies.read_ignores()
        assert len(ids) == len(set(ids))

    def test_every_id_looks_like_an_id(self) -> None:
        import audit_dependencies

        for entry in audit_dependencies.read_ignores():
            assert audit_dependencies._ID.match(entry), f"{entry!r} is not an id"

    def test_the_audit_script_exists(self) -> None:
        assert (REPO_ROOT / "scripts" / "audit_dependencies.py").is_file()


# -- the audit's one exemption, and its strictness ---------------------------


class TestTheAuditExemptsTheProject:
    """The project is installed from this checkout, so it cannot be audited.

    ``pip-audit`` would look ``agentic-job-applier`` up on PyPI, not find
    it, and fail the build on the *project*. The audit therefore skips
    editable packages — and this class checks that the package being
    skipped is this code and not somebody else's.
    """

    def test_the_audit_skips_editable_packages(self) -> None:
        import audit_dependencies

        command = audit_dependencies.build_command([])
        assert "--skip-editable" in command

    def test_the_audit_does_not_ask_for_strict(self) -> None:
        """``--strict`` and ``--skip-editable`` cannot be combined.

        ``--strict`` turns *every* skipped package into a fatal error, and
        the project is one. The strictness is enforced over the report
        instead, so the two flags must never meet.
        """
        import audit_dependencies

        command = audit_dependencies.build_command([])
        assert "--strict" not in command

    def test_the_documented_exceptions_reach_the_command(self) -> None:
        import audit_dependencies

        ids = audit_dependencies.read_ignores()
        command = audit_dependencies.build_command(ids)
        for entry in ids:
            assert command.count(entry) == 1, entry

    def test_the_project_is_exempt_only_as_an_editable_install(self) -> None:
        import audit_dependencies

        class _Distribution:
            version = "0.1.0"

            def __init__(self, payload: str) -> None:
                self._payload = payload

            def read_text(self, name: str) -> str | None:
                return self._payload if name == "direct_url.json" else None

        def _problems(payload: str) -> list[str]:
            original = audit_dependencies.importlib.metadata.distribution
            audit_dependencies.importlib.metadata.distribution = lambda name: _Distribution(payload)
            try:
                return audit_dependencies.check_the_project_is_local()
            finally:
                audit_dependencies.importlib.metadata.distribution = original

        # A wheel from PyPI: somebody else's code under our name. The
        # exemption must not cover it.
        assert _problems('{"url": "https://pypi.org/x/agentic_job_applier.whl"}')

        # Editable, but from another checkout.
        assert _problems('{"dir_info": {"editable": true}, "url": "file:///somewhere/else"}')

        # Editable, and from this checkout: the one exemption.
        assert not _problems(
            json.dumps(
                {
                    "dir_info": {"editable": True},
                    "url": REPO_ROOT.as_uri(),
                }
            )
        )


class TestTheAuditIsStillStrict:
    """The gate must not pass vacuously.

    ``--strict`` could not be used (it cannot be combined with the
    skip), so the script enforces the same rule over the report. These
    are the cases ``--strict`` used to catch.
    """

    def test_a_finding_fails_the_gate(self) -> None:
        import audit_dependencies

        report = {
            "dependencies": [
                {
                    "name": "some-package",
                    "version": "1.0.0",
                    "vulns": [{"id": "PYSEC-2026-1234"}],
                }
            ]
        }
        problems = audit_dependencies.check_the_report(report)
        assert problems
        assert "PYSEC-2026-1234" in problems[0]

    def test_an_unauditable_dependency_fails_the_gate(self) -> None:
        import audit_dependencies

        report = {
            "dependencies": [
                {
                    "name": "not-on-pypi",
                    "skip_reason": "Dependency not found on PyPI and could not be audited",
                }
            ]
        }
        assert audit_dependencies.check_the_report(report)

    def test_the_project_skipped_as_editable_is_not_a_problem(self) -> None:
        import audit_dependencies

        report = {
            "dependencies": [
                {
                    "name": audit_dependencies.PROJECT_NAME,
                    "skip_reason": "distribution marked as editable",
                },
                {"name": "some-package", "version": "1.0.0", "vulns": []},
            ]
        }
        assert not audit_dependencies.check_the_report(report)

    def test_a_report_the_gate_cannot_read_fails_the_gate(self) -> None:
        import audit_dependencies

        assert audit_dependencies.check_the_report(None)
        assert audit_dependencies.check_the_report({"something": "else"})

    def test_a_clean_report_passes(self) -> None:
        import audit_dependencies

        report = {
            "dependencies": [
                {"name": "some-package", "version": "1.0.0", "vulns": []},
                {"name": "another-package", "version": "2.0.0", "vulns": []},
            ]
        }
        assert not audit_dependencies.check_the_report(report)


@pytest.mark.parametrize("name", ["gate", "browser"])
def test_every_job_has_a_timeout(name: str) -> None:
    """A job with no timeout can hang a pull request forever."""
    import yaml

    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = document["jobs"][name]
    assert job.get("timeout-minutes"), f"the {name} job has no timeout"
