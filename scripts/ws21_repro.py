"""WS-21 · Part 2.1 reproduction: the reference profile's current top-N.

Runs the same code path as ``POST /api/jobs/search`` (``search_stored_jobs``)
against the live ``app.db`` corpus and prints the ranked matches with their
component breakdowns, including the WS-21 role component, so the ranking
defect can be inspected before and after the role-relevance work.

Usage (from the repo root)::

    env/Scripts/python.exe scripts/ws21_repro.py [profile_id]
    env/Scripts/python.exe scripts/ws21_repro.py [profile_id] --targets "Web Developer,Frontend Developer,Full-Stack Developer"

``--targets`` injects confirmed target roles **in memory only** — the script
never writes to the database. Without it, the target-resolution fallback
(confirmed current title → résumé headline → recent roles) applies, exactly
as a search over the API would.

Prints no personal information — job titles/companies are public listings.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.profiles import CandidateProfileDB, profile_from_row
from src.db.session import SessionLocal
from src.graph.job_executor import search_stored_jobs

DEFAULT_PROFILE_ID = "5e0d5bbebd68"
COMPONENTS = (
    ("semantic", "semantic_score"),
    ("lexical", "lexical_score"),
    ("skill", "skill_score"),
    ("experience", "experience_score"),
    ("seniority", "seniority_score"),
    ("location", "location_score"),
    ("preference", "preference_score"),
    ("role", "role_score"),
)


def _with_targets(profile, targets: list[str]):
    """A copy of the profile with confirmed target roles (in memory only)."""
    clone = profile.model_copy(deep=True)
    application = clone.application_profile
    application.preferences.target_roles = list(targets)
    marker = "preferences.target_roles"
    if marker not in application.confirmed_fields:
        application.confirmed_fields = [*application.confirmed_fields, marker]
    return clone


def main() -> int:
    args = [argument for argument in sys.argv[1:] if not argument.startswith("--")]
    profile_id = args[0] if args else DEFAULT_PROFILE_ID
    targets: list[str] = []
    if "--targets" in sys.argv:
        raw = sys.argv[sys.argv.index("--targets") + 1]
        targets = [part.strip() for part in raw.split(",") if part.strip()]

    with SessionLocal() as session:
        row = session.get(CandidateProfileDB, profile_id)
        if row is None:
            print(f"profile {profile_id!r} not found")
            return 1
        profile = profile_from_row(row)
    if targets:
        profile = _with_targets(profile, targets)

    app_profile = profile.application_profile
    print(f"profile {profile_id}: title={profile.personal_information.title!r}")
    print(f"  confirmed targets: {app_profile.preferences.target_roles or '(none)'}")
    print(
        "  application profile: "
        f"total_years={app_profile.professional.total_experience_years} "
        f"seniority={app_profile.professional.seniority_level!r} "
        f"current_title={app_profile.professional.current_title!r} "
        f"remote={app_profile.preferences.remote_preference!r}"
    )

    report = search_stored_jobs(profile, None, None, 30, session_factory=SessionLocal)
    stats = report.stats
    print(
        f"\nsearch: degraded={report.degraded} "
        f"semantic_covered={stats.semantic_covered}/{stats.stored} "
        f"corpus={stats.deduped}"
    )
    for rank, pair in enumerate(report.results, 1):
        match, job = pair.match, pair.job
        print(
            f"{rank:2}. {match.overall_score:5.1f} cov={match.evidence_coverage:3.0f}% "
            f"{job.title[:56]!r} @ {job.company[:22]!r}"
        )
        cells = []
        for name, attr in COMPONENTS:
            state = match.component_states.get(name, "?")
            if state in {"MATCHED", "PARTIAL_MATCH", "MISMATCH"}:
                cells.append(f"{name[:4]}={getattr(match, attr):.0f}")
            else:
                cells.append(f"{name[:4]}=unknown")
        role_note = ""
        if match.role_family:
            role_note = f" role={match.role_family}"
            if match.role_capped:
                role_note += " CAPPED"
        print("      " + " ".join(cells) + role_note)
        print(
            "      matched="
            f"{match.matched_requirements[:6]} "
            f"missing={match.missing_requirements[:6]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
