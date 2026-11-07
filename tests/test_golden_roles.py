"""WS-21: the golden set's occupational-role classifications are pinned.

The benchmark's role metrics measure the classifier, so a classifier drift
would silently change what the benchmark means. Every golden listing's
classification is recorded in ``role_families.json`` and compared here; an
intentional taxonomy change updates the file in the same commit.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.jobs.contracts import JobListing
from src.matching.roles import classify_job_role

GOLDEN = Path(__file__).parent / "evaluation" / "golden"


def _classifications() -> dict[str, dict]:
    jobs = [
        json.loads(line)
        for line in (GOLDEN / "jobs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out: dict[str, dict] = {}
    for job in jobs:
        listing = JobListing.model_validate(
            {key: value for key, value in job.items() if key not in ("labels", "dup_of")}
        )
        classification = classify_job_role(listing)
        out[job["id"]] = {
            "family": classification.family,
            "track": classification.track,
            "ambiguous": classification.ambiguous,
        }
    return out


def test_golden_role_classifications_are_stable():
    pinned = json.loads((GOLDEN / "role_families.json").read_text(encoding="utf-8"))
    produced = _classifications()
    assert produced == pinned


def test_golden_hard_negatives_classify_as_documented():
    """The named cases from the WS-21 brief, stated explicitly.

    The pin above would happily *record* a wrong drift; these assertions say
    what the answers must be, so a re-pin cannot approve a regression.
    """
    produced = _classifications()
    assert produced["golden:job-026"]["family"] == "data_analytics"
    assert produced["golden:job-027"]["family"] == "hardware_physical_design"
    assert produced["golden:job-028"]["family"] == "hardware_physical_design"
    assert produced["golden:job-029"]["family"] == "sales"
