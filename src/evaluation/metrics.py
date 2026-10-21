"""Evaluation metrics for the WS-09 harness (plan Phase 13 / §7).

Every function here is **pure**: ``metric(golden, produced) -> float | dict``.
No I/O, no clock, no randomness, no model calls — so a metric can be
hand-checked against a hand-computed expectation, and two runs of the harness
over the same dataset must produce identical numbers.

Grading convention used across the golden set: ``2 = relevant``,
``1 = partial``, ``0 = irrelevant``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

GRADE_RELEVANT = 2
GRADE_PARTIAL = 1
GRADE_IRRELEVANT = 0


# --------------------------------------------------------------- extraction


def field_accuracy(
    expected: Mapping[str, object], produced: Mapping[str, object], fields: Sequence[str]
) -> float:
    """Fraction of scalar fields that match exactly (case-insensitive, trimmed)."""
    if not fields:
        return 1.0
    matches = 0
    for field in fields:
        want = str(expected.get(field, "") or "").strip().casefold()
        got = str(produced.get(field, "") or "").strip().casefold()
        if want == got:
            matches += 1
    return matches / len(fields)


def set_f1(expected: Iterable[str], produced: Iterable[str]) -> float:
    """F1 over two sets, comparing case-insensitively.

    Two empty sets score 1.0 (nothing to find, nothing wrong); an empty
    expectation with a non-empty production scores 0.0.
    """
    want = {str(item).strip().casefold() for item in expected if str(item).strip()}
    got = {str(item).strip().casefold() for item in produced if str(item).strip()}
    if not want and not got:
        return 1.0
    if not want or not got:
        return 0.0
    overlap = len(want & got)
    if overlap == 0:
        return 0.0
    precision = overlap / len(got)
    recall = overlap / len(want)
    return 2 * precision * recall / (precision + recall)


def entry_scores(
    expected: Sequence[Mapping[str, str]],
    produced: Sequence[Mapping[str, str]],
    keys: Sequence[str],
) -> dict[str, float | int]:
    """Per-entry precision/recall for repeated structures (experience, education).

    An entry matches when every key in ``keys`` matches exactly. Precision is
    over the produced entries, recall over the expected ones.
    """

    def matches(expected_entry: Mapping[str, str], produced_entry: Mapping[str, str]) -> bool:
        for key in keys:
            want = str(expected_entry.get(key, "") or "").strip().casefold()
            got = str(produced_entry.get(key, "") or "").strip().casefold()
            if want != got:
                return False
        return True

    matched = 0
    used: set[int] = set()
    for expected_entry in expected:
        for index, produced_entry in enumerate(produced):
            if index in used:
                continue
            if matches(expected_entry, produced_entry):
                matched += 1
                used.add(index)
                break
    precision = matched / len(produced) if produced else (1.0 if not expected else 0.0)
    recall = matched / len(expected) if expected else 1.0
    return {
        "matched": matched,
        "produced": len(produced),
        "expected": len(expected),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
    }


# ------------------------------------------------------------------- dedup


def dedup_scores(
    kept_ids: Iterable[str],
    removed_ids: Iterable[str],
    duplicate_of: Mapping[str, str],
) -> dict[str, float | int]:
    """Precision/recall of the deduplication over annotated duplicate groups.

    ``duplicate_of`` maps a duplicate listing id to the id of the listing it
    duplicates. A removed listing that is annotated as a duplicate is a true
    positive; a removed listing that is not, is a false positive; an
    annotated duplicate that was kept is a false negative.
    """
    kept = set(kept_ids)
    removed = set(removed_ids)
    annotated_duplicates = set(duplicate_of)
    true_positive = len(removed & annotated_duplicates)
    false_positive = len(removed - annotated_duplicates)
    false_negative = len(annotated_duplicates & kept)
    precision = (
        true_positive / (true_positive + false_positive)
        if (true_positive + false_positive)
        else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if (true_positive + false_negative)
        else 1.0
    )
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


# ----------------------------------------------------------------- ranking


def dcg_at_k(grades: Sequence[int], k: int = 10) -> float:
    """Discounted cumulative gain (2^rel - 1 over log2(rank + 1))."""
    total = 0.0
    for index, grade in enumerate(list(grades)[:k]):
        if grade <= 0:
            continue
        total += (2**grade - 1) / math.log2(index + 2)
    return total


def ndcg_at_k(
    ranked_ids: Sequence[str],
    labels: Mapping[str, int],
    k: int = 10,
) -> float:
    """Normalized DCG@k over graded relevance labels."""
    grades = [labels.get(job_id, GRADE_IRRELEVANT) for job_id in ranked_ids]
    ideal = sorted(labels.values(), reverse=True)[:k]
    ideal_dcg = dcg_at_k(ideal, k)
    if ideal_dcg == 0:
        return 0.0
    return round(dcg_at_k(grades, k) / ideal_dcg, 6)


def precision_at_k(
    ranked_ids: Sequence[str],
    labels: Mapping[str, int],
    k: int = 5,
    min_grade: int = GRADE_RELEVANT,
) -> float:
    """Fraction of the top k that is at least ``min_grade``."""
    if k <= 0:
        return 0.0
    top = list(ranked_ids)[:k]
    if not top:
        return 0.0
    hits = sum(1 for job_id in top if labels.get(job_id, GRADE_IRRELEVANT) >= min_grade)
    return round(hits / len(top), 6)


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean (0.0 for an empty sequence)."""
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


# --------------------------------------------------------------- tailoring


def factuality_scores(
    expected: Sequence[Mapping[str, object]],
    produced: Sequence[Mapping[str, object]],
) -> dict[str, float | int]:
    """Agreement between human labels and the factuality validator's verdicts.

    ``expected`` entries carry ``expected_passed`` and ``expected_violations``;
    ``produced`` entries carry ``passed``, ``violations`` and the validator's
    structured removals (``removed_skills``, ``removed_experience``,
    ``removed_projects``).

    A labelled violation matches when it appears **either** in the violation
    text **or** in one of the structured removal lists. Matching on the
    structured fields is what makes the metric independent of the validator's
    wording: the question is "did the validator catch *this* fact?", not "did
    it phrase the report the way I expected?".
    """
    agree = 0
    expected_violations = 0
    found_violations = 0
    for want, got in zip(expected, produced):
        if bool(want.get("expected_passed")) == bool(got.get("passed")):
            agree += 1
        produced_violations = [str(item) for item in (got.get("violations") or [])]
        structured: list[str] = []
        for field in ("removed_skills", "removed_experience", "removed_projects"):
            structured.extend(str(item) for item in (got.get(field) or []))
        for violation in want.get("expected_violations", []) or []:
            expected_violations += 1
            needle = str(violation).casefold()
            haystack = [item.casefold() for item in produced_violations + structured]
            if any(needle in item for item in haystack):
                found_violations += 1
    total = len(expected)
    return {
        "pairs": total,
        "agreement": round(agree / total, 6) if total else 1.0,
        "expected_violations": expected_violations,
        "found_violations": found_violations,
        "violation_recall": round(found_violations / expected_violations, 6)
        if expected_violations
        else 1.0,
    }


def live_factuality_scores(
    produced: Sequence[Mapping[str, object]],
) -> dict[str, float | int]:
    """The pipeline's own factuality behaviour over live drafts.

    The hand labels in the golden set describe the *canned* drafts. A live
    draft is different text, so agreement against those labels would be
    meaningless. What a live run can honestly measure is the guard's own
    behaviour: how often a live draft needed stripping, and how much was
    stripped.

    Args:
        produced: The produced records — each with ``passed``,
            ``violations`` and the three ``removed_*`` lists.

    Returns:
        The pass rate, the strip rate, and the counts behind them.
    """
    total = len(produced)
    passed = 0
    stripped_pairs = 0
    stripped_claims = 0
    violations = 0
    for record in produced:
        if bool(record.get("passed")):
            passed += 1
        removed = 0
        for field in ("removed_skills", "removed_experience", "removed_projects"):
            removed += len(list(record.get(field) or []))
        stripped_claims += removed
        if removed:
            stripped_pairs += 1
        violations += len(list(record.get("violations") or []))

    return {
        "pairs": total,
        "passed": passed,
        "pass_rate": round(passed / total, 6) if total else 1.0,
        "stripped_pairs": stripped_pairs,
        "strip_rate": round(stripped_pairs / total, 6) if total else 0.0,
        "stripped_claims": stripped_claims,
        "violations": violations,
    }


def recall_at_k(
    ranked_ids: Sequence[str],
    labels: Mapping[str, int],
    k: int = 10,
    min_grade: int = GRADE_RELEVANT,
) -> float:
    """Share of the relevant listings that appear in the top *k*.

    The counterpart to :func:`precision_at_k`: precision asks "of what we
    showed, how much was relevant", recall asks "of what was relevant, how
    much did we show". A ranking can score well on one and badly on the
    other, so both are reported.

    Args:
        ranked_ids: The ranked listing ids, best first.
        labels: The graded relevance of every listing.
        k: The slice of the ranking to consider.
        min_grade: The grade at which a listing counts as relevant.

    Returns:
        The recall, or 1.0 when nothing is relevant (nothing to find).
    """
    relevant = {job_id for job_id, grade in labels.items() if grade >= min_grade}
    if not relevant:
        return 1.0
    shown = set(list(ranked_ids)[:k])
    return round(len(relevant & shown) / len(relevant), 6)


def duplicate_rate(total_listings: int, duplicates: int) -> float:
    """Share of the corpus that was a duplicate.

    The corpus-level view, complementing the dedup *precision* and
    *recall* of the deduplicator: those score the deduplicator against
    the annotations, this states how much duplication there was to
    remove in the first place.
    """
    if total_listings <= 0:
        return 0.0
    return round(duplicates / total_listings, 6)


def matching_error_rates(
    ranked_ids: Sequence[str],
    labels: Mapping[str, int],
    scores: Mapping[str, float],
    threshold: float,
    min_grade: int = GRADE_PARTIAL,
) -> dict[str, float | int]:
    """The false-positive and false-negative rates of the match decision.

    The engine produces a score, not a decision. A decision needs a
    threshold, and this metric takes it as an argument — the caller
    declares it, and the report prints it, so the number is never
    mistaken for a property of the engine.

    A listing is **predicted relevant** when its score reaches the
    threshold, and **actually relevant** when its label reaches
    ``min_grade``. The rates are over the two populations separately,
    which is what makes them comparable to each other.

    Args:
        ranked_ids: The ranked listing ids (the ranking under test).
        labels: The graded relevance of every listing.
        scores: The score of every listing.
        threshold: The decision threshold on the score.
        min_grade: The grade at which a listing counts as relevant.

    Returns:
        The two rates, with the confusion counts behind them.
    """
    true_positive = 0
    false_positive = 0
    true_negative = 0
    false_negative = 0

    for job_id, label in labels.items():
        if label < GRADE_IRRELEVANT:
            continue
        predicted = scores.get(job_id, 0.0) >= threshold
        actually = label >= min_grade
        if predicted and actually:
            true_positive += 1
        elif predicted and not actually:
            false_positive += 1
        elif not predicted and actually:
            false_negative += 1
        else:
            true_negative += 1

    positives = true_positive + false_negative
    negatives = false_positive + true_negative
    return {
        "threshold": threshold,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "true_negative": true_negative,
        "false_negative": false_negative,
        "false_positive_rate": (round(false_positive / negatives, 6) if negatives else 0.0),
        "false_negative_rate": (round(false_negative / positives, 6) if positives else 0.0),
    }


def job_relevance(
    job_required_skills: Sequence[str],
    tailored_skills: Sequence[str],
    tailored_text: str = "",
) -> float:
    """Share of the job's required skills the tailored resume carries.

    The job-relevance measure: a tailored resume that drops the job's
    core requirements is not a tailored resume, however well it scores on
    ATS structure.

    Args:
        job_required_skills: The job's required skills.
        tailored_skills: The skills the tailored resume highlights.
        tailored_text: The tailored resume's free text (bullets, summary),
            searched as well, so a skill mentioned in a bullet counts.

    Returns:
        The share of required skills present, or 1.0 when the job names
        no required skills.
    """
    required = [str(skill).strip() for skill in job_required_skills if str(skill).strip()]
    if not required:
        return 1.0
    haystack_skills = {str(skill).strip().casefold() for skill in tailored_skills}
    haystack_text = tailored_text.casefold()
    present = sum(
        1
        for skill in required
        if skill.casefold() in haystack_skills or skill.casefold() in haystack_text
    )
    return round(present / len(required), 6)


def hallucination_rate(
    produced_claims: int,
    stripped_claims: int,
) -> float:
    """Share of the tailored claims that were not supported by the profile.

    The factuality validator removes every claim the candidate's document
    does not support. The share it removes is the rate at which the model
    invented something — the number the plan calls the hallucination
    rate.
    """
    if produced_claims <= 0:
        return 0.0
    return round(stripped_claims / produced_claims, 6)


# --------------------------------------------------------------------- ATS


def coverage_delta(before_ratio: float, after_ratio: float) -> float:
    """Keyword-coverage change caused by tailoring (after - before)."""
    return round(after_ratio - before_ratio, 6)


__all__ = [
    "GRADE_IRRELEVANT",
    "GRADE_PARTIAL",
    "GRADE_RELEVANT",
    "coverage_delta",
    "dcg_at_k",
    "dedup_scores",
    "duplicate_rate",
    "entry_scores",
    "factuality_scores",
    "field_accuracy",
    "hallucination_rate",
    "job_relevance",
    "live_factuality_scores",
    "matching_error_rates",
    "mean",
    "ndcg_at_k",
    "precision_at_k",
    "recall_at_k",
    "set_f1",
]
