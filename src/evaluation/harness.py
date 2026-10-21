"""Evaluation harness for the WS-09 golden set (plan Phase 13 / §7).

Runs the real pipeline over the golden dataset and produces the numbers the
report shows. The **metrics themselves live in** ``src.evaluation.metrics``
(pure functions) — this module only produces the data they consume, so no
metric logic is buried in the runner script.

Two modes:

- ``offline`` (default): every model call is served from the canned drafts in
  ``golden/llm/`` and the semantic channel uses a deterministic lexical
  stand-in, so a run is free, reproducible, and provider-independent. The
  ranking metrics therefore measure the deterministic scorers (skills,
  experience, seniority, location, preference) — exactly the layers the
  FU-5 question is about.
- ``live``: the real LLM and the real embedding provider are used; the report
  states which mode produced it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.evaluation import metrics
from src.jobs.contracts import JobListing
from src.jobs.deduplicate import deduplicate
from src.matching.engine import calculate_match
from src.resume.ats import analyze_ats
from src.resume.parser import parse_resume
from src.resume.profile import CandidateProfile
from src.resume.tailor import TailoredResume, tailor_resume

GOLDEN_DIRNAME = "golden"


@dataclass
class GoldenDataset:
    """The loaded golden dataset."""

    root: Path
    expected_profiles: dict[str, dict] = field(default_factory=dict)
    jobs: list[dict] = field(default_factory=list)
    tailoring_pairs: list[dict] = field(default_factory=list)
    llm_drafts: dict[str, dict] = field(default_factory=dict)

    @property
    def listings(self) -> list[JobListing]:
        return [
            JobListing.model_validate(
                {k: v for k, v in job.items() if k not in ("labels", "dup_of")}
            )
            for job in self.jobs
        ]

    def labels_for(self, profile_key: str) -> dict[str, int]:
        """Graded relevance labels of every job for one profile."""
        return {job["id"]: int(job.get("labels", {}).get(profile_key, 0)) for job in self.jobs}

    def duplicate_map(self) -> dict[str, str]:
        """Annotated duplicate groups: duplicate id -> the id it duplicates."""
        return {job["id"]: job["dup_of"] for job in self.jobs if job.get("dup_of")}


def load_dataset(root: Path) -> GoldenDataset:
    """Load the golden dataset from ``root`` (the ``golden/`` directory)."""
    root = Path(root)
    expected_path = root / "expected_profiles.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    profiles = {key: value for key, value in expected.items() if not key.startswith("_")}

    jobs: list[dict] = []
    jobs_path = root / "jobs.jsonl"
    if jobs_path.exists():
        jobs = [
            json.loads(line)
            for line in jobs_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    pairs: list[dict] = []
    pairs_path = root / "tailoring_pairs.json"
    if pairs_path.exists():
        pairs = json.loads(pairs_path.read_text(encoding="utf-8")).get("pairs", [])

    drafts: dict[str, dict] = {}
    llm_dir = root / "llm"
    if llm_dir.exists():
        for path in sorted(llm_dir.glob("*.json")):
            key = path.stem.replace("golden_", "golden:")
            drafts[key] = json.loads(path.read_text(encoding="utf-8"))

    return GoldenDataset(
        root=root,
        expected_profiles=profiles,
        jobs=jobs,
        tailoring_pairs=pairs,
        llm_drafts=drafts,
    )


def dataset_hash(root: Path) -> str:
    """sha256 over the golden directory (file names + contents) — reproducibility."""
    digest = hashlib.sha256()
    root = Path(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


# --------------------------------------------------------------- semantics


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9+#.]+", (text or "").lower()) if token}


def lexical_semantic_scores(profile: CandidateProfile, jobs: list[JobListing]) -> dict[str, float]:
    """Deterministic stand-in for the semantic channel (offline mode).

    Cosine-style token overlap between the candidate's skills/title and each
    listing's text, scaled to 0-100. It is intentionally *not* an embedding:
    the offline run must be deterministic and provider-independent, and the
    ranking metrics are meant to measure the deterministic scorers.
    """
    candidate = _tokens(" ".join(profile.skills) + " " + profile.personal_information.title)
    scores: dict[str, float] = {}
    for job in jobs:
        document = _tokens(
            " ".join(
                [job.title, *job.required_skills, *job.preferred_skills, job.description or ""]
            )
        )
        if not candidate or not document:
            scores[job.id] = 0.0
            continue
        overlap = len(candidate & document)
        scores[job.id] = round(min(100.0, (overlap / len(candidate)) * 100.0), 4)
    return scores


# --------------------------------------------------------------- pipeline


def run_profile(
    dataset: GoldenDataset,
    profile_key: str,
    *,
    live: bool = False,
) -> dict[str, Any]:
    """Run the pipeline for one golden profile and return its measurements."""
    expected = dataset.expected_profiles[profile_key]
    profile = parse_resume(str(dataset.root / expected["file"]))

    # -- extraction --------------------------------------------------------
    produced_profile = {
        "name": profile.personal_information.name,
        "title": profile.personal_information.title,
        "email": profile.personal_information.email,
        "phone": profile.personal_information.phone,
        "location": profile.personal_information.location,
        "website": profile.personal_information.website,
    }
    scalar_fields = ["name", "title", "email", "phone", "location", "website"]
    extraction = {
        "field_accuracy": metrics.field_accuracy(expected, produced_profile, scalar_fields),
        "skills_f1": metrics.set_f1(expected.get("skills", []), profile.skills),
        "experience": metrics.entry_scores(
            expected.get("experience", []),
            [{"title": e.title, "company": e.company} for e in profile.experience],
            ("title", "company"),
        ),
        "education": metrics.entry_scores(
            expected.get("education", []),
            [{"degree": e.degree, "institution": e.institution} for e in profile.education],
            ("degree", "institution"),
        ),
    }
    summary_contains = expected.get("summary_contains", [])
    summary_hits = sum(
        1 for phrase in summary_contains if phrase.casefold() in profile.summary.casefold()
    )
    extraction["summary_coverage"] = (
        round(summary_hits / len(summary_contains), 6) if summary_contains else 1.0
    )

    # -- ranking -----------------------------------------------------------
    listings = dataset.listings
    unique = deduplicate(listings)
    kept_ids = {job.id for job in unique}
    removed_ids = {job.id for job in listings} - kept_ids
    semantic = lexical_semantic_scores(profile, unique)
    scored = [
        (job, calculate_match(job, profile, semantic_score=semantic.get(job.id))) for job in unique
    ]
    scored.sort(key=lambda pair: pair[1].overall_score, reverse=True)
    ranked_ids = [job.id for job, _ in scored]
    labels = dataset.labels_for(profile_key)
    ranking = {
        "ndcg_at_10": metrics.ndcg_at_k(ranked_ids, labels, k=10),
        "precision_at_5": metrics.precision_at_k(ranked_ids, labels, k=5),
        "candidates": len(unique),
    }

    # The same ranking in degraded mode (no semantics at all): the engine
    # redistributes the semantic weight and skill-less listings fall back to
    # the neutral score. Comparing the two turns the FU-5 question ("does the
    # neutral inflation distort the ranking?") into a measurement.
    degraded_scored = [(job, calculate_match(job, profile, semantic_score=None)) for job in unique]
    degraded_scored.sort(key=lambda pair: pair[1].overall_score, reverse=True)
    degraded_ranked = [job.id for job, _ in degraded_scored]
    ranking["degraded_ndcg_at_10"] = metrics.ndcg_at_k(degraded_ranked, labels, k=10)
    ranking["degraded_precision_at_5"] = metrics.precision_at_k(degraded_ranked, labels, k=5)
    ranking["semantic_delta_ndcg_at_10"] = round(
        ranking["ndcg_at_10"] - ranking["degraded_ndcg_at_10"], 6
    )

    return {
        "profile": profile_key,
        "extraction": extraction,
        "ranking": ranking,
        "ranked_ids": ranked_ids,
        "labels": labels,
        "_profile": profile,
        "_dedup": {"kept": kept_ids, "removed": removed_ids},
    }


def run_pair(
    dataset: GoldenDataset,
    pair: dict,
    profile: CandidateProfile,
    *,
    live: bool = False,
) -> dict[str, Any]:
    """Tailor one (profile, job) pair from the canned draft and measure it."""
    job = JobListing.model_validate(
        {
            key: value
            for key, value in next(j for j in dataset.jobs if j["id"] == pair["job"]).items()
            if key not in ("labels", "dup_of")
        }
    )
    draft = dataset.llm_drafts.get(f"{pair['profile']}__{pair['job']}".replace(":", "_"))
    if draft is None:
        draft = dataset.llm_drafts.get(pair["profile"] + "__" + pair["job"])
    if draft is None:
        raise KeyError(f"No canned draft for pair {pair['profile']} / {pair['job']}")

    def generate(_prompt: str, _schema: Any) -> TailoredResume:
        return TailoredResume.model_validate(draft)

    result = tailor_resume(profile, job, generate=generate)
    report = analyze_ats(result.tailored, profile, job)
    before = analyze_ats(_profile_as_tailored(profile), profile, job)
    return {
        "profile": pair["profile"],
        "job": pair["job"],
        "passed": result.factuality.passed,
        "violations": result.factuality.violations,
        "removed_skills": result.factuality.removed_skills,
        "removed_experience": result.factuality.removed_experience,
        "removed_projects": result.factuality.removed_projects,
        "coverage_before": before.keyword_coverage.required_coverage,
        "coverage_after": report.keyword_coverage.required_coverage,
        "ats_score": report.score,
    }


def _profile_as_tailored(profile: CandidateProfile) -> TailoredResume:
    """The untailored profile expressed as a TailoredResume ('before' state)."""
    from src.resume.tailor import TailoredExperience, TailoredProject

    return TailoredResume(
        summary=profile.summary,
        highlighted_skills=list(profile.skills),
        experience=[
            TailoredExperience(
                company=entry.company,
                title=entry.title,
                bullets=list(entry.bullets),
            )
            for entry in profile.experience
        ],
        projects=[
            TailoredProject(name=project.name, bullets=list(project.bullets))
            for project in profile.projects
        ],
        cover_letter="",
    )


def run_offline(dataset: GoldenDataset, *, live: bool = False) -> dict[str, Any]:
    """Run the whole golden set and return the aggregated measurements."""
    profiles: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for profile_key in dataset.expected_profiles:
        profile_result = run_profile(dataset, profile_key, live=live)
        profiles.append(profile_result)
        for pair in dataset.tailoring_pairs:
            if pair["profile"] != profile_key:
                continue
            pairs.append(run_pair(dataset, pair, profile_result["_profile"], live=live))

    dedup = metrics.dedup_scores(
        profiles[0]["_dedup"]["kept"] if profiles else set(),
        profiles[0]["_dedup"]["removed"] if profiles else set(),
        dataset.duplicate_map(),
    )

    expected_pairs = [
        {
            "expected_passed": pair["expected_passed"],
            "expected_violations": pair["expected_violations"],
        }
        for pair in dataset.tailoring_pairs
    ]
    produced_pairs = [
        {
            "passed": pair["passed"],
            "violations": pair["violations"],
            "removed_skills": pair["removed_skills"],
            "removed_experience": pair["removed_experience"],
            "removed_projects": pair["removed_projects"],
        }
        for pair in pairs
    ]
    factuality = metrics.factuality_scores(expected_pairs, produced_pairs)

    summary = {
        "extraction": {
            "field_accuracy": metrics.mean([p["extraction"]["field_accuracy"] for p in profiles]),
            "skills_f1": metrics.mean([p["extraction"]["skills_f1"] for p in profiles]),
            "summary_coverage": metrics.mean(
                [p["extraction"]["summary_coverage"] for p in profiles]
            ),
            "experience_precision": metrics.mean(
                [float(p["extraction"]["experience"]["precision"]) for p in profiles]
            ),
            "experience_recall": metrics.mean(
                [float(p["extraction"]["experience"]["recall"]) for p in profiles]
            ),
            "education_precision": metrics.mean(
                [float(p["extraction"]["education"]["precision"]) for p in profiles]
            ),
            "education_recall": metrics.mean(
                [float(p["extraction"]["education"]["recall"]) for p in profiles]
            ),
        },
        "dedup": dedup,
        "ranking": {
            "ndcg_at_10": metrics.mean([p["ranking"]["ndcg_at_10"] for p in profiles]),
            "precision_at_5": metrics.mean([p["ranking"]["precision_at_5"] for p in profiles]),
            # FU-5: what the semantic channel is actually worth on the golden
            # set, measured by re-ranking the same corpus in degraded mode.
            "degraded_ndcg_at_10": metrics.mean(
                [p["ranking"]["degraded_ndcg_at_10"] for p in profiles]
            ),
            "degraded_precision_at_5": metrics.mean(
                [p["ranking"]["degraded_precision_at_5"] for p in profiles]
            ),
            "semantic_delta_ndcg_at_10": metrics.mean(
                [p["ranking"]["semantic_delta_ndcg_at_10"] for p in profiles]
            ),
        },
        "tailoring": factuality,
        "ats": {
            "coverage_delta": metrics.mean(
                [metrics.coverage_delta(p["coverage_before"], p["coverage_after"]) for p in pairs]
            ),
            "mean_score": metrics.mean([p["ats_score"] for p in pairs]),
        },
    }

    return {
        "mode": "live" if live else "offline",
        "dataset": {
            "hash": dataset_hash(dataset.root),
            "profiles": len(dataset.expected_profiles),
            "jobs": len(dataset.jobs),
            "tailoring_pairs": len(dataset.tailoring_pairs),
        },
        "metrics": summary,
        "profiles": [
            {
                "profile": p["profile"],
                "extraction": p["extraction"],
                "ranking": p["ranking"],
            }
            for p in profiles
        ],
        "pairs": pairs,
    }


__all__ = [
    "GoldenDataset",
    "dataset_hash",
    "lexical_semantic_scores",
    "load_dataset",
    "run_offline",
    "run_pair",
    "run_profile",
]
