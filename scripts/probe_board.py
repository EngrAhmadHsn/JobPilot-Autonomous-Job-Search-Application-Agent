"""Probe a real ATS board and report what the walker would actually meet (WS-32).

The assist pilot's first live run (2026-11-15) needed a **read-only reconnaissance
step** before it could fill anything: which corpus postings are still open, what a
real board's form looks like, and what the planner makes of it. That work lived in
throwaway scripts, and this is the durable version — so the next run against a new
board shape starts from an instrument instead of from scratch.

It answers four questions, and it **changes nothing**: nothing is typed, clicked or
submitted.

1. **Is the posting live?** A closed Greenhouse posting answers ``200`` with a
   redirect to ``<company>?error=true``, so the *final URL* is the only tell — a
   status code will not do.
2. **What is on the page?** Every button with the walker's own classification
   (``is_submit`` / ``is_next``) and every control with the kind and required flag
   the product's reader assigns.
3. **What would the planner do?** ``build_form_plan`` against the demo facts —
   which questions are ``known`` / ``mappable`` / ``unknown``, and which land in
   ``unresolved`` (the list that stops a real run before it types).
4. **Would the fill actually work?** ``--fill`` drives the product's own
   ``_fill_control`` for every grounded answer and reads the values back from the
   DOM, which is what caught the trailing ``*`` breaking ``_label_locator`` on the
   four identity fields. ``--strip-required-marker`` measures the hypothesis by
   stripping the marker from the lookup only.

**Nothing here submits.** The submit button is located, classified and named; it is
never clicked. That is the point of the tool: it is safe to run against any board.

Usage::

    env\\Scripts\\python.exe scripts/probe_board.py <url>
    env\\Scripts\\python.exe scripts/probe_board.py <url> --fill
    env\\Scripts\\python.exe scripts/probe_board.py <url> --fill --strip-required-marker
    env\\Scripts\\python.exe scripts/probe_board.py <url> --json --out dir/

The target's host must already be on ``ALLOWED_DOMAINS`` — the real guard runs
first, exactly as it does in the pilot, so a refused host costs no browser.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

#: The demo candidate the live run used. Clearly fake on purpose: a probe that
#: reads like a real person is a probe someone will mistake for a real submission.
DEMO_FACTS: dict[str, str] = {
    "candidate_name": "Ada Lovelace",
    "name": "Ada Lovelace",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada.lovelace@example.com",
    "phone": "+1 555 0100",
    "location": "London, United Kingdom",
    "country": "United Kingdom",
    "linkedin": "https://www.linkedin.com/in/ada-lovelace-demo",
    "github": "https://github.com/ada-lovelace-demo",
    "website": "https://ada.example.com",
}

#: The controls a typed value can be written into. A file/select/radio needs a
#: different interaction, and this probe fills only what it can type.
_TYPED_KINDS = frozenset({"text", "tel", "email", "url", "number", "textarea"})


def _report_buttons(page: Any, submit_pattern: Any, next_pattern: Any) -> list[dict[str, Any]]:
    """Every button, with the walker's own submit/next classification."""
    rows: list[dict[str, Any]] = []
    locator = page.locator("button, input[type=submit], a[role=button]")
    for handle in locator.all():
        try:
            text = (handle.inner_text(timeout=1_000) or "").strip()
        except Exception:  # noqa: BLE001 - an unreadable button is not fatal
            text = ""
        if not text:
            try:
                text = (handle.get_attribute("value") or "").strip()
            except Exception:  # noqa: BLE001
                text = ""
        if text:
            rows.append(
                {
                    "text": text[:80],
                    "is_submit": bool(submit_pattern.search(text)),
                    "is_next": bool(next_pattern.search(text)),
                }
            )
    return rows


def _readback(page: Any) -> dict[str, str]:
    """What is actually in the controls now, read from the DOM."""
    return page.evaluate(
        """() => {
            const out = {};
            const sel = "input[type=text], input[type=tel], input[type=email], "
                      + "input[type=url], textarea";
            for (const el of document.querySelectorAll(sel)) {
                const name = (
                    el.getAttribute('aria-label')
                    || (el.labels && el.labels[0] && el.labels[0].textContent)
                    || el.getAttribute('name')
                    || ''
                ).trim();
                if (name) out[name.slice(0, 60)] = el.value;
            }
            return out;
        }"""
    )


def probe(
    url: str,
    *,
    fill: bool = False,
    strip_required_marker: bool = False,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Reconnoitre one board and return the measurement. Nothing is submitted."""
    from playwright.sync_api import sync_playwright

    from src.applications.fake_ats_adapter import (
        NEXT_BUTTON,
        SUBMIT_BUTTON,
        FakeAtsPlaywrightAdapter,
        NavigationTrace,
    )
    from src.applications.form import ProfileFacts, build_form_plan, read_controls
    from src.security.allowlist import assert_navigation_allowed

    # SEC-06 first: the real guard decides, before a browser exists.
    assert_navigation_allowed(url)

    adapter = FakeAtsPlaywrightAdapter()
    trace = NavigationTrace()
    record: dict[str, Any] = {
        "url": url,
        "fill": fill,
        "strip_required_marker": strip_required_marker,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3_000)

        record["status_code"] = response.status if response else None
        record["final_url"] = page.url
        record["title"] = page.title()
        # A closed posting is a 200 plus a redirect to "<company>?error=true".
        record["closed_redirect"] = "error=true" in page.url
        # Liveness is the *final URL*, and only the final URL. Two redirects are in
        # play and they mean opposite things: the legacy host
        # (``boards.greenhouse.io``) 301s to the current one
        # (``job-boards.greenhouse.io``) and stays on ``/jobs/<id>`` — still live;
        # a **closed** posting lands on ``<company>?error=true`` with no ``/jobs/``
        # segment at all. So the tell is the error parameter, not the host and not
        # the status code (which is 200 either way).
        record["live"] = "/jobs/" in page.url and not record["closed_redirect"]
        record["frames"] = [f.url[:120] for f in page.frames]

        record["buttons"] = _report_buttons(page, SUBMIT_BUTTON, NEXT_BUTTON)
        walker_button, walker_is_submit = adapter._find_button(page)
        record["walker_button"] = {
            "text": (walker_button.inner_text(timeout=2_000).strip() if walker_button else None),
            "is_submit": walker_is_submit,
        }

        controls = read_controls(page)
        plan = build_form_plan(controls, ProfileFacts(values=DEMO_FACTS))
        record["control_count"] = len(controls)
        record["controls"] = [
            {
                "label": c.label,
                "kind": c.kind,
                "required": c.required,
                "classification": c.classification,
            }
            for c in plan.questions
        ]
        record["known"] = sorted(plan.answers)
        record["unresolved"] = plan.unresolved
        record["skipped"] = plan.skipped
        record["classification_counts"] = {
            kind: sum(1 for q in plan.questions if q.classification == kind)
            for kind in ("known", "mappable", "unknown")
        }

        if fill:
            filled: list[dict[str, str]] = []
            failed: list[dict[str, str]] = []
            for question in plan.questions:
                value = plan.answers.get(question.label)
                if value is None or question.kind not in _TYPED_KINDS:
                    continue
                try:
                    if strip_required_marker:
                        # The hypothesis under test: the visible label carries a
                        # required marker the accessible name does not.
                        candidate = re.sub(r"\s*\*+\s*$", "", question.label).strip()
                        locator = page.get_by_label(candidate, exact=True)
                        if locator.count() == 0:
                            locator = page.get_by_label(
                                re.compile(re.escape(candidate), re.IGNORECASE)
                            )
                        locator.fill(value)
                    else:
                        adapter._fill_control(page, question, value, trace)
                    filled.append({"label": question.label, "value": value})
                except Exception as exc:  # noqa: BLE001 - a failed fill is a measurement
                    failed.append(
                        {
                            "label": question.label,
                            "kind": question.kind,
                            "error": type(exc).__name__,
                        }
                    )
            record["filled"] = filled
            record["fill_failed"] = failed
            record["filled_count"] = len(filled)
            record["dom_readback"] = _readback(page)
            page.wait_for_timeout(1_000)

        record["trace_actions"] = [e.get("action") for e in trace.entries]
        record["clicked_anything_submit"] = False

        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            shot = out_dir / ("filled.png" if fill else "page.png")
            page.screenshot(path=str(shot), full_page=True)
            record["screenshot"] = str(shot)
            (out_dir / "page.html").write_text(page.content(), encoding="utf-8")

        browser.close()

    return record


def _print_human(record: dict[str, Any]) -> None:
    state = "LIVE" if record.get("live") else "CLOSED/redirected"
    print(f"\n{state}  {record['status_code']}  {record['title'][:70]}")
    print(f"  requested : {record['url']}")
    print(f"  settled   : {record['final_url']}")
    if record.get("closed_redirect"):
        print("  note      : redirected to ?error=true — a status code does not tell you this")

    walker = record.get("walker_button") or {}
    print(
        f"\n  the walker's first button: {walker.get('text')!r} "
        f"(is_submit={walker.get('is_submit')})"
    )
    submits = [b for b in record.get("buttons", []) if b["is_submit"]]
    print(f"  buttons classified submit: {[b['text'] for b in submits]}")

    counts = record.get("classification_counts") or {}
    print(
        f"\n  controls {record.get('control_count')}  "
        f"known={counts.get('known')} mappable={counts.get('mappable')} "
        f"unknown={counts.get('unknown')}"
    )
    print(f"  unresolved ({len(record.get('unresolved') or [])}): {record.get('unresolved')}")

    if record.get("fill"):
        print(
            f"\n  filled {record.get('filled_count')}  failed "
            f"{len(record.get('fill_failed') or [])}"
        )
        for row in record.get("fill_failed") or []:
            print(f"    FAILED {row['label'][:44]!r} ({row['kind']}: {row['error']})")
        print("  values now in the DOM:")
        for label, value in sorted((record.get("dom_readback") or {}).items()):
            if value:
                print(f"    {label[:52]:52} = {value!r}")
    print("\n  submitted: False — the submit button is located and never clicked.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reconnoitre a real ATS board read-only (nothing is submitted).",
        epilog=(
            "The host must be on ALLOWED_DOMAINS; the pilot's own guard runs before "
            "any browser exists, so a refused host costs nothing."
        ),
    )
    parser.add_argument("url", help="the posting's application URL")
    parser.add_argument(
        "--fill",
        action="store_true",
        help="drive the product's own fill code and read the values back (never submits)",
    )
    parser.add_argument(
        "--strip-required-marker",
        action="store_true",
        help=(
            "with --fill, strip a trailing '*' from the label before the lookup — "
            "the experiment that isolated the locator defect"
        ),
    )
    parser.add_argument("--json", action="store_true", help="print the record as JSON")
    parser.add_argument("--out", default=None, help="also write the record, page and shot here")
    args = parser.parse_args(argv)

    out_dir = Path(args.out) if args.out else None
    record = probe(
        args.url,
        fill=args.fill,
        strip_required_marker=args.strip_required_marker,
        out_dir=out_dir,
    )

    if args.json:
        print(json.dumps(record, indent=2))
    else:
        _print_human(record)

    if out_dir is not None:
        (out_dir / "probe.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"\nwrote {out_dir / 'probe.json'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
