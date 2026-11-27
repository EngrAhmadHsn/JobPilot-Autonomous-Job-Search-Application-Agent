"""Turn one explicitly approved local review into a headed, fill-only session."""

from __future__ import annotations

import argparse
import getpass
import warnings
from contextlib import suppress

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import Route, sync_playwright
from sqlalchemy.exc import SQLAlchemyError

from src.api.posting_assist import FillRefused, claim_local_fill
from src.applications.review_fill import fill_review_page, review_domain, same_review_posting
from src.db.session import SessionLocal
from src.security.audit import OUTCOME_BLOCKED, OUTCOME_SUCCESS, Actor, record_audit


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        with warnings.catch_warnings():
            # getpass otherwise falls back to an echoed prompt on some terminals.
            warnings.simplefilter("error", getpass.GetPassWarning)
            code = getpass.getpass("Single-use autofill code (input hidden): ").strip()
        with SessionLocal() as db:
            grant = claim_local_fill(db, code)
        del code
        host = review_domain(grant.job_url)
        answer = input(
            f"Fill supported fields on {host}? This will enter your reviewed answers and résumé. "
            "JobPilot does not submit. Type yes to open and fill this form: "
        )
    except FillRefused as exc:
        print(str(exc))
        return 2
    except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("No form opened. Run this command in an interactive terminal with hidden input.")
        return 2
    except (SQLAlchemyError, ValueError):
        print(
            "Could not open this review. Use the same local JobPilot database and generate a new code."
        )
        return 2
    if answer.strip().lower() != "yes":
        print("Autofill cancelled. No employer page was opened.")
        return 0

    actor = Actor.user(grant.owner_id)
    record_audit(
        "application.local_fill_started",
        actor=actor,
        owner_id=grant.owner_id,
        resource=grant.application_id,
        outcome=OUTCOME_SUCCESS,
    )
    try:
        with (
            sync_playwright() as playwright,
            playwright.chromium.launch(headless=False) as browser,
            browser.new_context(service_workers="block", accept_downloads=False) as context,
        ):
            page = context.new_page()
            page.set_default_timeout(3_000)

            def fill_only(route: Route) -> None:
                request = route.request
                # Block all write requests and cross-posting navigation during fill.
                if request.method not in {"GET", "HEAD"} or (
                    request.is_navigation_request()
                    and not same_review_posting(request.url, grant.job_url)
                ):
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", fill_only)
            response = page.goto(grant.job_url, wait_until="domcontentloaded", timeout=20_000)
            outcome = (
                fill_review_page(page, grant, confirmed=True)
                if response is not None and response.ok
                else None
            )
            ready = outcome is not None and outcome.status == "handoff"
            record_audit(
                "application.local_fill_finished",
                actor=actor,
                owner_id=grant.owner_id,
                resource=grant.application_id,
                outcome=OUTCOME_SUCCESS if ready else OUTCOME_BLOCKED,
                metadata={
                    "filled": outcome.filled if outcome else 0,
                    "skipped": outcome.skipped if outcome else len(grant.form.questions),
                    "status": outcome.status if outcome else "no_form",
                },
            )
            if not ready:
                print(
                    "Autofill stopped. Open the employer site from the review and complete the form manually."
                )
                return 2
            print(
                f"Filled {outcome.filled} supported fields; {outcome.skipped} reviewed fields were left alone."
            )
            print(
                "Check every field and the résumé attachment. You may have to attach the file again manually."
            )
            if (
                input("Type take over to allow normal browser requests, or press Enter to close: ")
                .strip()
                .lower()
                == "take over"
            ):
                context.unroute("**/*", fill_only)
                print("The browser is yours. Only you can decide whether to press Submit.")
                with suppress(EOFError, KeyboardInterrupt):
                    input("Press Enter here when you want to close the browser: ")
    except (BrowserError, EOFError, KeyboardInterrupt):
        print("The assisted browser stopped. JobPilot did not submit or verify an application.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
