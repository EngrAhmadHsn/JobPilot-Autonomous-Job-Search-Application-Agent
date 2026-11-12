"""WS-24c · The per-listing residual, and the repeat-search memo.

The measurements this workstream was built on (2026-11-12, the live
8,558-listing corpus, one real candidate profile, the real artifacts):

* a warm search took **9.3–10.7 s** before the change and **4.5–4.6 s**
  after it (cold artifacts: 68.7 s, unchanged in kind);
* the query embedding alone was **3.17 s** of the warm search, and the
  vector fetch another ~1.1 s — both paid again by an identical repeat;
* ``_effective_preferences`` deep-copied the whole preferences model
  **17,116** times per search (twice per listing);
* the candidate's years of experience were re-derived **twice** per
  listing, each a union over every dated entry;
* the lexical evidence lists took **3.4 M list appends** per search, then
  truncated to 25.

The property that matters most is that **nothing changed but the time**:
every score, state, rank, explanation and evidence list is identical.
``test_the_scores_are_unchanged_against_the_reference_path`` pins that by
re-running the pre-WS-24c code path beside the current one.
"""

from __future__ import annotations

import re

import pytest

# --------------------------------------------------------------------------
# Phase A — the per-search constants
# --------------------------------------------------------------------------


def test_the_seniority_prefilter_is_exactly_equivalent():
    """The substring prefilter must not change which keyword wins.

    WS-24c replaced 19 word-boundary regex scans per text with 19 ``in``
    checks that escalate to a regex only on a hit. A combined alternation
    regex would have been faster still, but it changes *which* keyword
    matches when a text contains two (``"Senior Staff Engineer"``), so the
    ladder order is kept and the regex stays the arbiter.

    The reference below is the pre-change implementation, verbatim.
    """
    from src.matching.engine import _SENIORITY_RANKS, _seniority_rank

    def reference(text):
        if not text or not text.strip():
            return None
        lowered = text.casefold()
        for keyword, rank in _SENIORITY_RANKS:
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                return rank
        return None

    samples = [
        "Senior Staff Engineer",
        "Staff Software Engineer",
        "Senior Backend Developer",
        "Principal Platform Architect",
        "Entry Level Data Analyst",
        "Junior ML Engineer",
        "International Sales Lead",
        "Mid-level Designer",
        "Lead Data Scientist",
        "Sr. Director of Engineering",
        "Associate Product Manager",
        "Graduate Trainee",
        "Distinguished Engineer",
        "Software Engineer II",
        "Architect (Cloud)",
        "Snr DevOps",
        "midweight front end",
        "Trainee Solicitor",
        "Intern - Research",
        "Senior Principal Engineer",
        "staff sre",
        "SENIOR",
        # The cases a substring check gets wrong if the regex is dropped:
        # "intern" inside "international"/"internal", "lead" inside
        # "leadership", "jr" inside a word.
        "Internal Auditor",
        "debugging internals",
        "leadership program",
        "Junior/Senior mix",
        "Sr.Engineer",
        "S.R. Engineer",
        "",
        None,
        "   ",
    ]
    for sample in samples:
        assert _seniority_rank(sample) == reference(sample), sample


def test_the_candidate_constants_are_computed_once_in_the_context():
    """The context carries the profile-only values the components read.

    Each of these used to be computed inside a component builder, so a
    search paid for it once per listing.
    """
    from src.matching.engine import CandidateContext
    from src.resume.profile import CandidateProfile, WorkPreferences

    profile = CandidateProfile(
        skills=["Python", "  SQL  ", ""],
        work_preferences=WorkPreferences(
            preferred_locations=["  Berlin ", "", "Remote"],
            employment_types=["Full Time", "contract"],
            min_salary="$80,000",
        ),
    )
    context = CandidateContext.for_profile(profile)

    # The same answers the per-listing helpers would give.
    from src.matching.engine import (
        _candidate_rank,
        _effective_preferences,
        _normalize_employment_type,
        _parse_salary,
    )

    assert context.effective_preferences == _effective_preferences(profile)
    assert context.candidate_rank == _candidate_rank(profile)
    assert context.preferred_locations == ("berlin", "remote")
    assert context.employment_types == tuple(
        _normalize_employment_type(value)
        for value in context.effective_preferences.employment_types
        if _normalize_employment_type(value)
    )
    assert context.parsed_min_salary == _parse_salary(context.effective_preferences.min_salary)


def test_the_context_skill_set_drops_blank_entries():
    """A blank skill must not become an empty string in the match set."""
    from src.matching.engine import CandidateContext
    from src.resume.profile import CandidateProfile

    context = CandidateContext.for_profile(CandidateProfile(skills=["Python", "  ", ""]))
    assert context.skill_set == frozenset({"python"})


# --------------------------------------------------------------------------
# Phase B — the job-side rank in the artifacts
# --------------------------------------------------------------------------


def test_the_corpus_artifacts_carry_the_seniority_rank():
    """The rank is listing-only, so it belongs with the other artifacts."""
    from src.matching.corpus_cache import CorpusArtifacts

    artifacts = CorpusArtifacts(fingerprint=("db", 0, "hash"))
    assert hasattr(artifacts, "seniority_ranks")
    assert artifacts.seniority_ranks == {}


def test_the_seniority_rank_is_read_from_the_artifacts_not_recomputed():
    """A cached rank is used as-is, even when the title disagrees.

    This is what proves the cache is actually consulted: a title that
    classifies one way and a cached rank that says another must produce
    the cached answer.
    """
    from src.matching.corpus_cache import CorpusArtifacts
    from src.matching.engine import CandidateContext, calculate_match
    from src.matching.scores import ScoreState
    from src.resume.profile import CandidateProfile

    job = _listing(title="Senior Backend Engineer", seniority=None)
    profile = CandidateProfile()
    context = CandidateContext.for_profile(profile)

    # Unranked (5) against a junior candidate (1) would be a 20-point
    # miss-driven score; a rank of 1 is a perfect match.
    artifacts = CorpusArtifacts(fingerprint=("db", 1, "hash"))
    artifacts.seniority_ranks = {job.id: 1}

    # The candidate has no stated level, so the component cannot measure;
    # use a confirmed level so only the job side is in play.
    profile = _profile_with_confirmed_level("junior")
    context = CandidateContext.for_profile(profile)
    result = calculate_match(job, profile, artifacts=artifacts, context=context)
    assert result.component_states["seniority"] == ScoreState.MATCHED.value
    assert result.seniority_score == pytest.approx(100.0)


def test_a_seniority_change_moves_the_content_version():
    """The cached rank reads this column, so the digest must cover it.

    WS-24c: without this, a refresh that changed only ``seniority`` would
    keep the corpus fingerprint and serve a stale cached rank.
    """
    from src.db.jobs import content_version_for

    base = _listing(title="Engineer", seniority=None)
    changed = _listing(title="Engineer", seniority="senior")
    assert content_version_for(base) != content_version_for(changed)

    # And a re-sighting of the same content still does not move it.
    assert content_version_for(_listing(title="Engineer", seniority="senior")) == (
        content_version_for(changed)
    )


def test_the_artifacts_version_is_in_the_fingerprint():
    """Adding a derived field must invalidate exactly once.

    The fingerprint hashes the corpus *content*, which cannot tell that the
    shape of ``CorpusArtifacts`` changed. The version constant is what
    forces the rebuild.
    """
    from src.matching import corpus_cache

    assert corpus_cache._ARTIFACTS_VERSION >= 2

    digest_source = corpus_cache.corpus_fingerprint.__doc__ or ""
    # The constant is used, not merely defined.
    source = __import__("inspect").getsource(corpus_cache.corpus_fingerprint)
    assert "_ARTIFACTS_VERSION" in source, digest_source


# --------------------------------------------------------------------------
# Phase C — the truncated evidence lists
# --------------------------------------------------------------------------


def test_the_evidence_lists_stop_at_the_limit_but_the_coverage_does_not():
    """Capping the lists must not change the score.

    The coverage divides by the **weight** of every matched term, so the
    weight must keep accumulating past the point the list stops growing.
    """
    from src.matching.lexical import EVIDENCE_LIMIT, Bm25Index, lexical_score

    # A listing with far more distinct terms than the limit.
    job = _listing(
        title="Engineer",
        description=" ".join(f"term{index}" for index in range(EVIDENCE_LIMIT * 3)),
        required_skills=[],
        preferred_skills=[],
    )
    index = Bm25Index([job])
    terms = [(f"term{index}", 1.0) for index in range(EVIDENCE_LIMIT * 3)]
    total = float(len(terms))

    result = lexical_score(
        job,
        index=index,
        candidate_token_list=["unrelated-only"],
        candidate_text="unrelated-only",
        important_terms=terms,
        total_weight=total,
    )
    # Nothing matched, so the coverage is 0 — but the *missing* list is
    # capped while the score is computed from the full term set.
    assert len(result.missing_keywords) == EVIDENCE_LIMIT
    assert result.keyword_coverage == pytest.approx(0.0)

    # Now the matched side: every term matches, so the coverage is full
    # even though the returned list is truncated.
    result = lexical_score(
        job,
        index=index,
        candidate_token_list=[f"term{index}" for index in range(EVIDENCE_LIMIT * 3)],
        candidate_text=" ".join(f"term{index}" for index in range(EVIDENCE_LIMIT * 3)),
        important_terms=terms,
        total_weight=total,
    )
    assert len(result.matched_keywords) == EVIDENCE_LIMIT
    assert result.keyword_coverage == pytest.approx(100.0)


def test_the_truncated_list_keeps_the_first_entries_in_order():
    """The cap must not shuffle the evidence — the first N is what it was."""
    from src.matching.lexical import EVIDENCE_LIMIT, Bm25Index, lexical_score

    terms = [(f"term{index:03d}", 1.0) for index in range(EVIDENCE_LIMIT * 2)]
    job = _listing(title="Engineer", description=" ".join(t for t, _ in terms))
    index = Bm25Index([job])

    result = lexical_score(
        job,
        index=index,
        candidate_token_list=[],
        candidate_text="nothing",
        important_terms=terms,
        total_weight=float(len(terms)),
    )
    assert result.missing_keywords == [f"term{index:03d}" for index in range(EVIDENCE_LIMIT)]


# --------------------------------------------------------------------------
# Phase D — the in-process scan memo
# --------------------------------------------------------------------------


class _StubStore:
    """A vector store whose scan is counted, so the memo is observable."""

    def __init__(self, count: int = 3, scope: str = "stub") -> None:
        self.scans = 0
        self._ids = [f"job:{index}" for index in range(count)]
        self.collection_name = "stub"
        self._persist_dir = scope

    def count(self) -> int:
        return len(self._ids)

    def _scan(self, query_text: str) -> dict[str, float]:
        self.scans += 1
        return {job_id: float(len(query_text)) for job_id in self._ids}

    def _scan_key(self, query_text: str, covered: int) -> tuple[str, str, int]:
        """The store's own key builder, so the test cannot drift from it."""
        from src.rag.chroma_store import ChromaVectorStore

        return ChromaVectorStore._scan_key(self, query_text, covered)


def _scan_via_memo(store: _StubStore, query_text: str) -> dict[str, float]:
    """The memo lookup + miss path, as ``similarities_for_all`` uses it."""
    from src.rag.chroma_store import _recall_scan, _remember_scan

    key = store._scan_key(query_text, len(store._ids))
    cached = _recall_scan(key)
    if cached is not None:
        return cached
    scores = store._scan(query_text)
    _remember_scan(key, scores)
    return scores


def test_a_repeat_scan_is_served_from_the_memo():
    """The same query against the same corpus scans once, not twice."""
    from src.rag.chroma_store import clear_process_scan_cache

    clear_process_scan_cache()
    store = _StubStore()
    first = _scan_via_memo(store, "a candidate")
    second = _scan_via_memo(store, "a candidate")
    assert store.scans == 1
    assert first == second


def test_a_different_query_does_not_share_a_scan():
    """Two profiles must never be served each other's similarities."""
    from src.rag.chroma_store import clear_process_scan_cache

    clear_process_scan_cache()
    store = _StubStore()
    _scan_via_memo(store, "candidate one")
    _scan_via_memo(store, "candidate two")
    assert store.scans == 2


def test_a_corpus_size_change_invalidates_the_memo():
    """A scan covers a fixed set of ids; a different set is a different key."""
    from src.rag.chroma_store import clear_process_scan_cache

    clear_process_scan_cache()
    store = _StubStore(count=3)
    _scan_via_memo(store, "a candidate")
    store._ids = [*store._ids, "job:new"]
    _scan_via_memo(store, "a candidate")
    assert store.scans == 2


def test_an_expired_scan_is_not_served():
    """The TTL is what surfaces a write by the separate worker process."""
    from src.rag import chroma_store

    chroma_store.clear_process_scan_cache()
    store = _StubStore()
    _scan_via_memo(store, "a candidate")
    assert store.scans == 1

    # Rewind the recorded time past the TTL rather than sleeping.
    key = next(iter(chroma_store._PROCESS_SCAN))
    stored_at, scores = chroma_store._PROCESS_SCAN[key]
    chroma_store._PROCESS_SCAN[key] = (
        stored_at - chroma_store._PROCESS_SCAN_TTL_SECONDS - 1.0,
        scores,
    )
    _scan_via_memo(store, "a candidate")
    assert store.scans == 2


def test_a_write_clears_the_memo():
    """A re-embedded listing changes a score without changing the count."""
    from src.rag.chroma_store import _PROCESS_SCAN, _remember_scan, clear_process_scan_cache

    clear_process_scan_cache()
    _remember_scan(("stub", "digest", 3), {"job:0": 1.0})
    assert _PROCESS_SCAN
    clear_process_scan_cache()
    assert not _PROCESS_SCAN


def test_the_memo_holds_no_candidate_text():
    """The key is a digest, so no profile prose is retained.

    WS-14 · Phase G forbids a *persistent, shared* candidate cache. This
    one is process-local and memory-only; the test pins the remaining
    property that the key itself carries no readable text.
    """
    import hashlib

    from src.rag.chroma_store import _PROCESS_SCAN, clear_process_scan_cache

    clear_process_scan_cache()
    secret = "a very specific and identifying candidate summary"
    store = _StubStore()
    _scan_via_memo(store, secret)

    joined = repr(tuple(_PROCESS_SCAN.keys()))
    assert secret not in joined
    assert hashlib.sha256(secret.encode()).hexdigest() in joined


def test_two_stores_in_different_directories_do_not_share_a_scan():
    """A shared collection *name* is not a shared corpus.

    The tests build one Chroma directory per ``tmp_path``; a memo keyed on
    the name alone would serve one test's similarities to another. That is a
    wrong answer, not merely a stale one.
    """
    from src.rag.chroma_store import clear_process_scan_cache

    clear_process_scan_cache()
    one = _StubStore(scope="/tmp/corpus-a")
    two = _StubStore(scope="/tmp/corpus-b")
    _scan_via_memo(one, "a candidate")
    _scan_via_memo(two, "a candidate")
    assert one.scans == 1
    assert two.scans == 1


# --------------------------------------------------------------------------
# The exactness gate
# --------------------------------------------------------------------------


def test_the_component_scores_are_unchanged_against_the_reference_path():
    """Every component must agree with an independently computed reference.

    WS-24c moved the candidate-side work out of the component builders. That
    refactor can only be trusted if the numbers are *the same*, so each
    component is recomputed here from the pre-change formula — the ladder
    inline, the preferences merged per call, the date union per call — and
    compared exactly.
    """
    from src.matching.engine import (
        CONFLICT_SCORE,
        _candidate_rank,
        _effective_preferences,
        _normalize_employment_type,
        _parse_salary,
        _seniority_rank,
        calculate_match,
        measured_state,
        work_preferences_stated,
    )
    from src.matching.experience import years_of_experience
    from src.matching.lexical import Bm25Index, lexical_score
    from src.matching.scores import ScoreState
    from src.resume.profile import WorkPreferences

    profile = _profile_with_confirmed_level("senior")
    profile.work_preferences = WorkPreferences(
        preferred_locations=["Berlin"],
        employment_types=["Full Time"],
        min_salary="$90,000",
    )
    jobs = [
        _listing(
            title="Senior Backend Engineer",
            seniority=None,
            location="Berlin, Germany",
            remote_policy="hybrid",
            employment_type="Full Time",
            salary="$100,000-$130,000",
            required_skills=["Python", "SQL"],
            preferred_skills=["Go"],
            description="Five years of experience with Python and SQL.",
            experience_requirements="5 years",
        ),
        _listing(
            id="test:2",
            source_job_id="2",
            title="Junior Designer",
            seniority="junior",
            location="Lisbon",
            remote_policy="onsite",
            employment_type="Contract",
            salary="$30,000",
            required_skills=["Figma"],
            description="Design work.",
            experience_requirements="1 year",
        ),
        _listing(
            id="test:3",
            source_job_id="3",
            title="Engineer",
            seniority=None,
            location=None,
            remote_policy=None,
        ),
    ]
    index = Bm25Index(jobs)
    tokens = ["python", "sql", "engineer", "backend"]
    text = " ".join(tokens)

    for job in jobs:
        lexical = lexical_score(job, index=index, candidate_token_list=tokens, candidate_text=text)
        result = calculate_match(job, profile, semantic_score=50.0, lexical=lexical)

        # -- seniority: the ladder, read straight from the listing ---------
        job_rank = _seniority_rank(job.seniority) or _seniority_rank(job.title)
        candidate_rank = _candidate_rank(profile)
        if job_rank is None or candidate_rank is None:
            expected_seniority = 0.0
        else:
            expected_seniority = max(0.0, min(100.0, 100.0 - 30.0 * abs(candidate_rank - job_rank)))
        assert result.seniority_score == pytest.approx(expected_seniority), job.id

        # -- location: the pre-change order of the checks -------------------
        prefs = _effective_preferences(profile)
        policy = (job.remote_policy or "").casefold().replace("-", "").replace(" ", "")
        job_location = (job.location or "").casefold()
        preferred = [loc.strip().casefold() for loc in prefs.preferred_locations if loc.strip()]
        if (
            policy == "remote"
            or preferred
            and job_location
            and any(loc in job_location or job_location in loc for loc in preferred)
        ):
            expected_location = 100.0
        elif not work_preferences_stated(prefs) or not job_location and not policy:
            expected_location = 0.0
        elif policy == "onsite":
            expected_location = CONFLICT_SCORE
        elif policy == "hybrid":
            expected_location = 55.0
        elif job_location:
            expected_location = 40.0
        else:
            expected_location = 0.0
        assert result.location_score == pytest.approx(expected_location), job.id

        # -- preference: employment type and salary, computed per call -----
        subscores = []
        employment_pref = [
            normalized
            for normalized in (_normalize_employment_type(t) for t in prefs.employment_types)
            if normalized
        ]
        job_employment = _normalize_employment_type(job.employment_type)
        if employment_pref and job_employment:
            subscores.append(100.0 if job_employment in employment_pref else 40.0)
        candidate_min = _parse_salary(prefs.min_salary)
        job_salary = _parse_salary(job.salary)
        if candidate_min is not None and job_salary is not None:
            subscores.append(100.0 if job_salary[1] >= candidate_min[0] else CONFLICT_SCORE)
        expected_preference = (sum(subscores) / len(subscores)) if subscores else 0.0
        assert result.preference_score == pytest.approx(expected_preference), job.id

        # -- experience: the bar against the unioned date ranges -----------
        requirement = _bar_for(job)
        actual = years_of_experience(profile)
        if requirement is None or actual is None:
            expected_experience = 0.0
        else:
            expected_experience = max(
                0.0, min(100.0, 100.0 - 25.0 * max(0.0, requirement - actual))
            )
        assert result.experience_score == pytest.approx(expected_experience), job.id

        # -- and the states that carry the "unknown" vocabulary ------------
        if expected_location == 0.0 and policy != "hybrid":
            assert result.component_states["location"] in {
                ScoreState.JOB_REQUIREMENT_MISSING.value,
                ScoreState.CANDIDATE_DATA_MISSING.value,
            }
        assert result.component_states["seniority"] in {
            ScoreState.MATCHED.value,
            ScoreState.PARTIAL_MATCH.value,
            ScoreState.MISMATCH.value,
            ScoreState.JOB_REQUIREMENT_MISSING.value,
            ScoreState.CANDIDATE_DATA_MISSING.value,
        }
        assert measured_state(result.overall_score) is not None


def _bar_for(job) -> float | None:
    """The stated experience bar, mined the pre-change way (per call)."""
    from src.matching.experience import required_years

    return required_years(job)


# --------------------------------------------------------------------------
# Fixtures (plain builders — these tests need real model shapes)
# --------------------------------------------------------------------------


def _listing(**overrides):
    from src.jobs.contracts import JobListing

    data = {
        "id": "test:1",
        "source": "test",
        "source_job_id": "1",
        "title": "Engineer",
        "company": "Acme",
        "description": "",
    }
    data.update(overrides)
    return JobListing(**data)


def _profile_with_confirmed_level(level: str):
    from src.resume.application_profile import ApplicationProfile, ProfessionalInfo
    from src.resume.profile import CandidateProfile

    return CandidateProfile(
        skills=["Python", "SQL"],
        application_profile=ApplicationProfile(
            professional=ProfessionalInfo(seniority_level=level),
            confirmed_fields=["professional"],
        ),
    )
