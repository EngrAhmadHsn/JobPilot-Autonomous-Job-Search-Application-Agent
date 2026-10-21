"""Evaluation harness for the WS-09 golden set (plan Phase 13 / §7).

Runs the real pipeline over the golden dataset and produces the numbers the
report shows. The **metrics themselves live in** ``src.evaluation.metrics``
(pure functions) — this module only produces the data they consume, so no
metric logic is buried in the runner script.

Two modes, and the difference is what *runs*, not what the report calls it:

- ``offline`` (default): every model call is served from the canned drafts in
  ``golden/llm/`` and the semantic channel uses a deterministic lexical
  stand-in, so a run is free, reproducible, and provider-independent. The
  ranking metrics therefore measure the deterministic scorers (skills,
  experience, seniority, location, preference) — exactly the layers the
  FU-5 question is about.
- ``live``: the real LLM produces the tailored drafts (through the
  production ``tailor_resume`` seam) and the real embedding provider produces
  the semantic scores (through the production text contract). The numbers
  are **not** bit-reproducible, and the report says so.

A live run that cannot reach its provider **fails**; it never falls back to
the canned data under a "live" label — a report that lies about its own
provenance is worse than no report.
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

#: The decision threshold the match error rates are measured at.
#:
#: The engine produces a score, not a decision. This constant is the score
#: at which a listing is treated as "predicted relevant". It is **declared,
#: not fitted**: it is the engine's own documented neutral score (70 — the
#: score a component returns when its inputs are unknown), so "predicted
#: relevant" means "scored above the line where the engine admits it has
#: no signal". The rates are therefore conservative by construction, and
#: the report prints the threshold beside them.
MATCH_DECISION_THRESHOLD = 70.0

#: The modes a run can take. ``offline`` is deterministic and reproducible;
#: ``live`` uses the real providers and is therefore not.
MODE_OFFLINE = "offline"
MODE_LIVE = "live"
MODES = (MODE_OFFLINE, MODE_LIVE)


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


def default_live_channel() -> Any:
    """The real semantic channel, built on the configured embedding provider.

    The provider is the production one (``build_embedding_fn``), so the live
    numbers come from the same embedding space production ranks in. If the
    provider cannot be constructed the call **raises**: a live run that
    silently fell back to the lexical stand-in would be a report that lies
    about its own provenance.
    """
    from src.evaluation.semantics import RealSemanticChannel
    from src.llm.embeddings import build_embedding_fn

    return RealSemanticChannel(build_embedding_fn())


def run_profile(
    dataset: GoldenDataset,
    profile_key: str,
    *,
    live: bool = False,
    semantic_channel: Any | None = None,
) -> dict[str, Any]:
    """Run the pipeline for one golden profile and return its measurements.

    Args:
        dataset: The loaded golden dataset.
        profile_key: Which golden profile to run.
        live: When true, the semantic scores come from the real embedding
            provider instead of the lexical stand-in.
        semantic_channel: The channel to score with. Defaults to the real
            one when ``live`` is true and to the lexical stand-in otherwise.

    Returns:
        The profile's measurements, plus the parsed profile and the dedup
        bookkeeping the caller needs.
    """
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
    if semantic_channel is None:
        semantic_channel = default_live_channel() if live else lexical_semantic_scores
    semantic = semantic_channel(profile, unique)
    scored = [
        (job, calculate_match(job, profile, semantic_score=semantic.get(job.id))) for job in unique
    ]
    scored.sort(key=lambda pair: pair[1].overall_score, reverse=True)
    ranked_ids = [job.id for job, _ in scored]
    labels = dataset.labels_for(profile_key)
    scores = {job.id: result.overall_score for job, result in scored}
    ranking = {
        "ndcg_at_10": metrics.ndcg_at_k(ranked_ids, labels, k=10),
        "precision_at_5": metrics.precision_at_k(ranked_ids, labels, k=5),
        "recall_at_10": metrics.recall_at_k(ranked_ids, labels, k=10),
        "candidates": len(unique),
    }

    # The false-positive and false-negative rates of the match decision.
    # The engine produces a score, not a decision, so the threshold is
    # declared (not fitted) and printed in the report.
    ranking["matching"] = metrics.matching_error_rates(
        ranked_ids, labels, scores, MATCH_DECISION_THRESHOLD
    )

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
    generate: Any | None = None,
) -> dict[str, Any]:
    """Tailor one (profile, job) pair and measure it.

    Args:
        dataset: The loaded golden dataset.
        pair: The golden tailoring pair.
        profile: The parsed candidate profile.
        live: When true, the draft comes from the real LLM through the
            production ``tailor_resume`` seam instead of the canned draft.
        generate: An explicit generation callable, overriding the mode.
            Used by the tests to stand in for the model.

    Returns:
        The pair's measurements, including what the factuality validator
        had to strip.
    """
    job = JobListing.model_validate(
        {
            key: value
            for key, value in next(j for j in dataset.jobs if j["id"] == pair["job"]).items()
            if key not in ("labels", "dup_of")
        }
    )

    # The produced draft is captured so the claim counts are real: the
    # hallucination rate is stripped claims over *produced* claims, and the
    # produced claims only exist in the draft the model wrote.
    produced: dict[str, TailoredResume] = {}

    if generate is None:
        if live:
            # The production seam: ``tailor_resume`` builds the prompt and
            # calls the configured provider. Nothing is canned.
            generate = None
        else:
            draft = dataset.llm_drafts.get(f"{pair['profile']}__{pair['job']}".replace(":", "_"))
            if draft is None:
                draft = dataset.llm_drafts.get(pair["profile"] + "__" + pair["job"])
            if draft is None:
                raise KeyError(f"No canned draft for pair {pair['profile']} / {pair['job']}")

            def generate(_prompt: str, _schema: Any) -> TailoredResume:
                return TailoredResume.model_validate(draft)

    if generate is not None:
        inner = generate

        def capturing_generate(prompt: str, schema: Any) -> TailoredResume:
            draft = inner(prompt, schema)
            produced["draft"] = draft
            return draft

        generate = capturing_generate

    result = tailor_resume(profile, job, generate=generate)
    report = analyze_ats(result.tailored, profile, job)
    before = analyze_ats(_profile_as_tailored(profile), profile, job)

    draft = produced.get("draft")
    produced_claims = _claim_count(draft) if draft is not None else 0
    stripped_claims = (
        len(result.factuality.removed_skills)
        + len(result.factuality.removed_experience)
        + len(result.factuality.removed_projects)
    )

    tailored_text = " ".join(
        [
            result.tailored.summary,
            result.tailored.cover_letter,
            *result.tailored.highlighted_skills,
            *[bullet for entry in result.tailored.experience for bullet in entry.bullets],
        ]
    )

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
        "produced_claims": produced_claims,
        "stripped_claims": stripped_claims,
        "job_relevance": metrics.job_relevance(
            job.required_skills, result.tailored.highlighted_skills, tailored_text
        ),
    }


def _claim_count(draft: TailoredResume) -> int:
    """How many factual claims a draft asserted.

    A claim is one thing the draft says the candidate did or can do: a
    highlighted skill, an experience entry or a project. The hallucination
    rate is the share of them the validator had to remove.
    """
    return len(draft.highlighted_skills) + len(draft.experience) + len(draft.projects)


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


def run_evaluation(
    dataset: GoldenDataset,
    *,
    mode: str = MODE_OFFLINE,
    semantic_channel: Any | None = None,
    generate: Any | None = None,
) -> dict[str, Any]:
    """Run the whole golden set and return the aggregated measurements.

    Args:
        dataset: The loaded golden dataset.
        mode: ``offline`` (deterministic, free) or ``live`` (the real
            providers).
        semantic_channel: The semantic scorer. Defaults to the lexical
            stand-in offline and the real embedding provider live.
        generate: The generation callable for the tailoring step. Defaults
            to the canned drafts offline and the real LLM live.

    Returns:
        The measurements, the dataset fingerprint, and the identity of the
        providers that produced them.

    Raises:
        ValueError: The mode is not one of the known modes.
    """
    if mode not in MODES:
        raise ValueError(f"Unknown evaluation mode {mode!r}; expected one of {MODES}")

    live = mode == MODE_LIVE
    if semantic_channel is None and live:
        semantic_channel = default_live_channel()

    profiles: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for profile_key in dataset.expected_profiles:
        profile_result = run_profile(
            dataset, profile_key, live=live, semantic_channel=semantic_channel
        )
        profiles.append(profile_result)
        for pair in dataset.tailoring_pairs:
            if pair["profile"] != profile_key:
                continue
            pairs.append(
                run_pair(dataset, pair, profile_result["_profile"], live=live, generate=generate)
            )

    dedup = metrics.dedup_scores(
        profiles[0]["_dedup"]["kept"] if profiles else set(),
        profiles[0]["_dedup"]["removed"] if profiles else set(),
        dataset.duplicate_map(),
    )

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

    if live:
        # The golden labels describe the *canned* drafts. A live draft is
        # different text, so agreement against those labels would be
        # meaningless. What the live run measures is the pipeline's own
        # factuality behaviour: how often a live draft needed stripping, and
        # how much was stripped.
        tailoring = metrics.live_factuality_scores(produced_pairs)
    else:
        expected_pairs = [
            {
                "expected_passed": pair["expected_passed"],
                "expected_violations": pair["expected_violations"],
            }
            for pair in dataset.tailoring_pairs
        ]
        tailoring = metrics.factuality_scores(expected_pairs, produced_pairs)

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
            "recall_at_10": metrics.mean([p["ranking"]["recall_at_10"] for p in profiles]),
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
            # The match decision's error rates, at the declared threshold.
            "false_positive_rate": metrics.mean(
                [p["ranking"]["matching"]["false_positive_rate"] for p in profiles]
            ),
            "false_negative_rate": metrics.mean(
                [p["ranking"]["matching"]["false_negative_rate"] for p in profiles]
            ),
            "match_decision_threshold": MATCH_DECISION_THRESHOLD,
        },
        "tailoring": tailoring,
        "ats": {
            "coverage_delta": metrics.mean(
                [metrics.coverage_delta(p["coverage_before"], p["coverage_after"]) for p in pairs]
            ),
            "mean_score": metrics.mean([p["ats_score"] for p in pairs]),
        },
        "relevance": {
            # The corpus-level duplicate rate, complementing the dedup
            # precision and recall of the deduplicator itself.
            "duplicate_rate": metrics.duplicate_rate(
                len(dataset.jobs),
                len(dataset.duplicate_map()),
            ),
            # How much of the job's core requirements the tailored resume
            # carries — a tailored resume that drops them is not tailored.
            "job_relevance": metrics.mean([p["job_relevance"] for p in pairs]),
            # The rate at which the model asserted something the profile
            # does not support.
            "hallucination_rate": metrics.hallucination_rate(
                sum(p["produced_claims"] for p in pairs),
                sum(p["stripped_claims"] for p in pairs),
            ),
        },
    }

    return {
        "mode": mode,
        "reproducible": not live,
        "providers": _provider_identity(live),
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


def _provider_identity(live: bool) -> dict[str, Any]:
    """The identity of the providers that produced a run.

    A report that says "live" must name the model and the embedding
    provider, so a reader can tell *which* live system produced the
    numbers. Offline runs name the stand-ins they used instead.
    """
    if not live:
        return {
            "llm": {"provider": "canned-drafts", "model": "none"},
            "embeddings": {"provider": "lexical-standin", "model": "none"},
        }
    from src.config.settings import get_settings

    settings = get_settings()
    return {
        "llm": {"provider": settings.llm_provider, "model": settings.llm_model},
        "embeddings": {
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
        },
    }


def run_offline(dataset: GoldenDataset, *, live: bool = False) -> dict[str, Any]:
    """Run the golden set, offline by default.

    Kept as the entry point the existing tests and the docs use;
    :func:`run_evaluation` is the mode-explicit form.
    """
    return run_evaluation(dataset, mode=MODE_LIVE if live else MODE_OFFLINE)


__all__ = [
    "MODES",
    "MODE_LIVE",
    "MODE_OFFLINE",
    "GoldenDataset",
    "dataset_hash",
    "default_live_channel",
    "lexical_semantic_scores",
    "load_dataset",
    "run_evaluation",
    "run_offline",
    "run_pair",
    "run_profile",
]
