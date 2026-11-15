"""The assist-mode pilot: prepare, fill, hand the browser over, verify.

Run this **with a human sitting in front of the machine**. It is the harness for
WS-32's first real submission, in the form the evidence supports: the agent
prepares everything, drives the form up to the final submit, and stops. It
cannot press submit because it does not hold ``SUBMIT``
(``src/security/registry_setup.py`` grants ``assist-playwright`` ``PREPARE``
only), and the capability matrix — not this script — is what enforces that.

The purpose is **measurement, not automation**. One real posting, one run, and a
record of where it stopped: which questions it could not answer, which widgets
it did not recognise, whether the page's own validation complained. That
measurement decides which board shape to support next. What to record, and the
exact protocol, is in ``docs/implementation/32-submission-readiness.md``.

**What this harness gets right, from the plan's two requirements.**

*The allowlist decides where it may go, and it is checked first.* The target's
domain has to be on the operator's ``ALLOWED_DOMAINS`` **deliberately, per run**.
:func:`run_pilot` calls the real guard
(:func:`src.security.allowlist.assert_job_url_allowed`) before anything else —
before a profile is read, before a browser exists — and a refusal propagates as
:class:`~src.security.allowlist.DisallowedDomainError`, whose message names the
host and the ``ALLOWED_DOMAINS`` variable. An operator who mis-set the
environment therefore learns what to set, instead of watching a browser reach a
board the configuration did not intend. The adapter checks the allowlist again
before every page of the walk, so a redirect is caught too.

*A fresh browser context per run (SEC-07), and the browser is left open.* One
process, one browser, one context, one page: no cookie or storage survives into
the next run because the next run starts a new browser. The *end* of the run is
the opposite of the usual one — the context is deliberately **not** closed,
because the human has to be able to press the button on the page the agent
filled. :func:`run_pilot` closes it only when the operator says the run is over
(``--close-when-done``).

Usage::

    # 1. the local rehearsal — free to get wrong
    env\\Scripts\\python.exe scripts\\serve_fake_ats.py
    set PLAYWRIGHT_HEADLESS=false
    env\\Scripts\\python.exe scripts\\pilot_assist.py \\
        --url http://127.0.0.1:8901/basic --profile-id <id>

    # 2. the real run — the operator's allowlist, deliberately, per run
    set ALLOWED_DOMAINS=boards.greenhouse.io,greenhouse.io
    set PLAYWRIGHT_HEADLESS=false
    env\\Scripts\\python.exe scripts\\pilot_assist.py \\
        --url https://boards.greenhouse.io/acme/jobs/12345 \\
        --profile-id <id> --job-title "Backend Engineer" --company "Acme"

The window opens in front of the operator, filled up to (not including) the
submit. The script prints what it could not answer, the operator finishes the
form by hand and presses the form's own submit, and the script then captures the
page they submitted on and verifies it. Nothing in this script clicks the submit
button.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.applications.assist_adapter import AssistAdapter
from src.applications.contracts import (
    ApplicationAdapter,
    ApplicationRequest,
    ApplicationResult,
    PreparedApplication,
    SubmissionEvidence,
)
from src.security.allowlist import (
    DisallowedDomainError,
    assert_job_url_allowed,
    host_of,
)

logger = logging.getLogger("pilot_assist")

#: The callable the harness waits on while the human finishes the form. It is
#: handed the stopped adapter, so a human (or a test) can press the page's own
#: button in the window the agent left open.
HumanStep = Callable[[Any], None]


class PilotRefused(RuntimeError):
    """The pilot refused to run: the payload, not the target, was the problem.

    An allowlist refusal is deliberately **not** this exception — it propagates
    as :class:`~src.security.allowlist.DisallowedDomainError`, the real guard's
    own type, so a caller can tell "the configuration does not allow this board"
    from "the agent's own work was incomplete".
    """


@dataclass
class PilotReport:
    """What one assist run produced — the record the pilot exists to make.

    Every field is either a measurement taken during the run or ``None`` because
    the step did not happen. Nothing is inferred: a run with no human step has
    ``evidence=None`` and ``verified=None`` rather than a cheerful summary, and
    ``success`` is ``False`` whenever nothing was submitted.
    """

    url: str
    profile_id: str | None
    elapsed_seconds: float
    result: ApplicationResult
    prepared: PreparedApplication | None = None
    #: The page the human submitted on, captured after their step.
    evidence: SubmissionEvidence | None = None
    #: The verified result, or ``None`` when no human step happened.
    verified: ApplicationResult | None = None
    #: The questions the walker could not answer: the run stopped there.
    questions_unanswered: list[str] = field(default_factory=list)
    #: The optional questions it left for the human.
    questions_left_alone: list[str] = field(default_factory=list)
    #: The controls whose widget kind it did not recognise.
    unrecognised_widgets: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serialisable summary (field names, never candidate values)."""
        return {
            "url": self.url,
            "profile_id": self.profile_id,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "status": self.result.status,
            "success": self.result.success,
            "message": self.result.message,
            "questions_unanswered": self.questions_unanswered,
            "questions_left_alone": self.questions_left_alone,
            "unrecognised_widgets": self.unrecognised_widgets,
            "evidence": (
                {
                    "url": self.evidence.url,
                    "confirmation_text": (self.evidence.confirmation_text or "")[:280],
                    "screenshot_path": self.evidence.screenshot_path,
                    "trace_path": self.evidence.trace_path,
                    "status": self.evidence.status,
                }
                if self.evidence is not None
                else None
            ),
            "verified_status": self.verified.status if self.verified is not None else None,
        }


def assert_target_allowed(url: str) -> None:
    """Refuse a target the operator's ``ALLOWED_DOMAINS`` does not intend.

    The real guard does the deciding; this wrapper only makes its message
    actionable for an operator (the host, and the variable that has to change)
    and keeps the exception type the guard's own, so nothing can mistake a
    configuration refusal for an agent failure.

    Raises:
        DisallowedDomainError: The URL is empty, not ``http``/``https``, points
            at an internal or metadata address, or its host is not on
            ``ALLOWED_DOMAINS``.
    """
    try:
        assert_job_url_allowed(url)
    except DisallowedDomainError as exc:
        host = host_of(url) or url
        raise DisallowedDomainError(
            f"{exc} The pilot requires the target's domain to be on the operator's "
            f"ALLOWED_DOMAINS before it will start: add {host!r} to ALLOWED_DOMAINS "
            "for this run, deliberately."
        ) from exc


def load_profile_request(
    profile_id: str | None,
    *,
    job_title: str,
    company_name: str,
    job_url: str,
    candidate_name: str = "",
    email: str = "",
    phone: str = "",
    resume_path: str | None = None,
    owner_id: str | None = None,
) -> ApplicationRequest:
    """Build the request from the **stored** profile, or from the flags given.

    The grounded facts come from the profile the candidate uploaded — the same
    source the API's prepare route uses
    (:func:`src.api.routes.applications._profile_facts`) — so a question the
    document does not answer stays unanswered instead of being invented.

    The request's own ``candidate_name``/``email``/``phone`` are **not** filled
    from the profile here: the adapter's ``prepare`` reads the profile facts for
    those and applies the name split there. Duplicating that choice in two
    places is how the two drift; an explicit flag still wins over the facts,
    which is the adapter's documented rule.

    Args:
        profile_id: The stored profile to ground the answers in.
        job_title: The posting's title.
        company_name: The company's name.
        job_url: The application URL; the caller has already allowlist-checked it.
        candidate_name: An explicit name, when the operator wants one.
        email: An explicit email.
        phone: An explicit phone number.
        resume_path: The résumé file to attach, when one is supplied.
        owner_id: The account the run belongs to (WS-14 · Phase B), so the
            evidence lands in that account's own directory.

    Returns:
        The request the adapter prepares from.

    Raises:
        PilotRefused: ``profile_id`` was given but no readable profile exists.
            An empty payload submitted to a real board is exactly the failure
            this pilot must not produce.
    """
    facts: dict[str, str] = {}
    if profile_id:
        from src.db.access import UserScope, get_profile
        from src.db.profiles import profile_from_row
        from src.db.session import SessionLocal

        with SessionLocal() as session:
            scope = UserScope(user_id=owner_id or _legacy_owner_id(), is_superuser=not owner_id)
            row = get_profile(session, scope, profile_id)
            if row is None:
                raise PilotRefused(
                    f"No candidate profile {profile_id!r} is readable by this account; the "
                    "pilot will not run against a board without the candidate's own data."
                )
            facts = _facts_for(profile_from_row(row), job_url, session)

    return ApplicationRequest(
        job_title=job_title,
        company_name=company_name,
        job_url=job_url,
        candidate_name=candidate_name,
        email=email,
        phone=phone,
        resume_path=resume_path,
        profile_facts=facts,
    )


def _legacy_owner_id() -> str:
    from src.db.users import LEGACY_OWNER_ID

    return LEGACY_OWNER_ID


def _facts_for(profile, job_url: str, session) -> dict[str, str]:
    """The grounded facts of a profile, with the posting's country applied.

    WS-25c: the boards ask "are you authorized to work in the country for which
    you apply?", so the work-authorization fact is qualified by the posting's
    own location — read from the corpus by the listing's application URL. An
    unresolvable location withholds the fact, which is the safe direction.
    """
    from src.applications.form import facts_from_profile, resolve_job_country
    from src.db.jobs import location_for_application_url

    try:
        location = location_for_application_url(job_url, session_factory=session.get_bind())
    except Exception:  # an unknown country withholds the answer, safely
        logger.debug("The posting's location could not be resolved", exc_info=True)
        location = None
    return facts_from_profile(profile, job_country=resolve_job_country(location))


def _default_human_step(assist) -> None:
    """Wait for the operator: the window is theirs until they press Enter."""
    print()
    print("=" * 78)
    print("THE BROWSER IS YOURS")
    print(f"  Page: {assist.page_url or '(unknown page)'}")
    print("  The form is filled up to the submit button. The agent cannot press it:")
    print("  it does not hold the SUBMIT capability.")
    print("  Finish anything the agent could not, then press the form's own Submit.")
    print("  When the confirmation page is showing, come back here and press Enter.")
    print("=" * 78)
    try:
        input("Press Enter once you have submitted, or Ctrl-C to abandon the run: ")
    except EOFError:  # a non-interactive caller (a pipe) still gets the capture
        logger.warning("No interactive terminal: capturing the page as it stands now.")


def run_pilot(
    url: str,
    profile_id: str | None,
    *,
    job_title: str = "Backend Engineer",
    company_name: str = "Acme Labs",
    candidate_name: str = "",
    email: str = "",
    phone: str = "",
    resume_path: str | None = None,
    owner_id: str | None = None,
    adapter: ApplicationAdapter | None = None,
    human: HumanStep | None = _default_human_step,
    close_when_done: bool = False,
    request: ApplicationRequest | None = None,
) -> PilotReport:
    """Run the pilot once: prepare, fill, hand over, capture, verify.

    Args:
        url: The posting's application URL.
        profile_id: The stored candidate profile to ground the answers in.
        job_title: The posting's title.
        company_name: The company's name.
        candidate_name: An explicit name (empty means "use the stored profile").
        email: An explicit email.
        phone: An explicit phone number.
        resume_path: The résumé file to attach.
        owner_id: The account the run belongs to.
        adapter: The adapter to drive. ``None`` constructs the real
            :class:`~src.applications.assist_adapter.AssistAdapter`; a caller (a
            test) may hand over a stub, which is how this harness is covered
            without a browser.
        human: The callable the harness waits on. ``None`` runs unattended: the
            form is filled and the report says no human step happened, so no
            evidence is ever claimed.
        close_when_done: Whether to close the browser the run left open. The
            default is deliberately ``False``: that window is the human's.
        request: A pre-built request; overrides the flags (used by tests).

    Returns:
        The :class:`PilotReport`: the stop result, the questions it could not
        answer, the widgets it did not recognise, the evidence from the page the
        human submitted on, and the verified result.

    Raises:
        DisallowedDomainError: The target's host is not on the operator's
            ``ALLOWED_DOMAINS`` (or is an internal address). Raised before a
            browser exists, so a refused target costs nothing.
        PilotRefused: The payload could not be completed from the stored
            profile, or the provider's contract refused it — the provider would
            have accepted the blank, so the pilot stops instead of measuring a
            submission that was never complete.
    """
    started = time.monotonic()

    # SEC-06 first, and the real guard decides: nothing may be opened before the
    # allowlist has agreed to this host, deliberately, for this run.
    assert_target_allowed(url)

    assist_adapter = adapter if adapter is not None else AssistAdapter()
    if not assist_adapter.supports_url(url):
        raise PilotRefused(f"The adapter {assist_adapter.name!r} does not support {url!r}")

    if request is None:
        request = load_profile_request(
            profile_id,
            job_title=job_title,
            company_name=company_name,
            job_url=url,
            candidate_name=candidate_name,
            email=email,
            phone=phone,
            resume_path=resume_path,
            owner_id=owner_id,
        )

    prepared = assist_adapter.prepare(request)
    prepared.owner_id = owner_id or prepared.owner_id

    result = assist_adapter.submit(prepared)

    report = PilotReport(
        url=url,
        profile_id=profile_id,
        elapsed_seconds=time.monotonic() - started,
        result=result,
        prepared=prepared,
        questions_unanswered=list(result.metadata.get("questions") or ()),
        questions_left_alone=list(result.metadata.get("questions_left_alone") or ()),
        unrecognised_widgets=list(result.metadata.get("unrecognised_widgets") or ()),
    )

    if result.status == "incomplete_payload":
        # The provider would have accepted an incomplete payload and reported
        # nothing. The pilot stops rather than measure a submission that was
        # never complete.
        raise PilotRefused(result.message)

    if result.status != "awaiting_human_submit" or human is None:
        report.elapsed_seconds = time.monotonic() - started
        return report

    # The handover. The human's step is theirs; the capture reads the page they
    # submitted on, and `verify` is what turns its text into a verified status.
    human(assist_adapter)

    capture = getattr(assist_adapter, "capture_human_submission", None)
    if callable(capture):
        submitted = capture()
        report.evidence = submitted.evidence
        report.verified = assist_adapter.verify(submitted)
    else:  # an adapter without the seam: nothing is claimed
        logger.warning("The adapter %r cannot capture the human's submission", assist_adapter.name)

    if close_when_done:
        close = getattr(assist_adapter, "close", None)
        if callable(close):
            close()

    report.elapsed_seconds = time.monotonic() - started
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pilot_assist.py",
        description=(
            "WS-32 assist-mode pilot: fill one application form and hand the submit to a human."
        ),
        epilog=(
            "The target's domain must be on ALLOWED_DOMAINS before the run. For the local "
            "rehearsal, run scripts/serve_fake_ats.py and use the URL it prints."
        ),
    )
    parser.add_argument("--url", required=True, help="the posting's application URL")
    parser.add_argument("--profile-id", default=None, help="the stored candidate profile to use")
    parser.add_argument("--job-title", default="Backend Engineer")
    parser.add_argument("--company", default="Acme Labs")
    parser.add_argument("--candidate-name", default="")
    parser.add_argument("--email", default="")
    parser.add_argument("--phone", default="")
    parser.add_argument("--resume-path", default=None)
    parser.add_argument("--owner-id", default=None)
    parser.add_argument(
        "--unattended",
        action="store_true",
        help="fill the form and stop without waiting for a human (no evidence is claimed)",
    )
    parser.add_argument(
        "--close-when-done",
        action="store_true",
        help="close the browser at the end (default: leave it open for the operator)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="log the adapters' own decisions"
    )
    return parser


def _print_report(report: PilotReport, *, as_json: bool) -> None:
    """Print the measurement, in the shape the workstream doc records it."""
    if as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return

    print()
    print("-" * 78)
    print(f"Assist run: {report.result.status}  ({report.elapsed_seconds:.1f}s)")
    print(f"  {report.result.message}")
    print(f"  Questions it could not answer : {report.questions_unanswered or '(none)'}")
    print(f"  Questions left for the human  : {report.questions_left_alone or '(none)'}")
    print(f"  Widgets it did not recognise  : {report.unrecognised_widgets or '(none)'}")
    if report.evidence is not None:
        print(f"  Evidence page                 : {report.evidence.url}")
        print(f"  Screenshot                    : {report.evidence.screenshot_path}")
        print(f"  Trace                         : {report.evidence.trace_path}")
    else:
        print("  Evidence                      : (none — no human step happened)")
    if report.verified is not None:
        print(f"  Verified                      : {report.verified.status}")
    else:
        print("  Verified                      : (not verified)")
    print("-" * 78)


def main(argv: list[str] | None = None) -> int:
    """The CLI: a thin wrapper around :func:`run_pilot`."""
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        report = run_pilot(
            args.url,
            args.profile_id,
            job_title=args.job_title,
            company_name=args.company,
            candidate_name=args.candidate_name,
            email=args.email,
            phone=args.phone,
            resume_path=args.resume_path,
            owner_id=args.owner_id,
            human=None if args.unattended else _default_human_step,
            close_when_done=args.close_when_done,
        )
    except DisallowedDomainError as exc:
        print(f"The pilot refused to start: {exc}", file=sys.stderr)
        return 3
    except PilotRefused as exc:
        print(f"The pilot refused to run: {exc}", file=sys.stderr)
        return 4

    _print_report(report, as_json=args.json)
    if report.result.status == "awaiting_human_submit" and report.verified is None:
        print("The form is filled and unfinished by design; a human must press submit.")
    return 0 if report.result.status == "awaiting_human_submit" else 1


if __name__ == "__main__":
    raise SystemExit(main())
