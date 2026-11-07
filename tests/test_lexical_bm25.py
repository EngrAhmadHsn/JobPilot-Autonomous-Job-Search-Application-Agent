"""WS-20 · BM25 lexical retrieval and keyword/phrase matching."""

from __future__ import annotations

from src.jobs.contracts import JobListing
from src.matching.lexical import (
    BM25_HALF_SATURATION,
    Bm25Index,
    candidate_lexical_text,
    candidate_tokens,
    lexical_score,
    normalize_term,
    tokenize,
)
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    ProjectEntry,
)


def job(**kwargs) -> JobListing:
    defaults = {"id": "job-1", "source": "greenhouse", "title": "Engineer", "company": "Acme"}
    defaults.update(kwargs)
    return JobListing(**defaults)


def profile(**kwargs) -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(title=kwargs.get("title", "Engineer")),
        summary=kwargs.get("summary", ""),
        skills=kwargs.get("skills", []),
        experience=kwargs.get("experience", []),
        projects=kwargs.get("projects", []),
    )


def score(job_listing, cand, corpus=None) -> float:
    corpus = corpus if corpus is not None else [job_listing]
    index = Bm25Index(corpus)
    return lexical_score(
        job_listing,
        index=index,
        candidate_token_list=candidate_tokens(cand),
        candidate_text=candidate_lexical_text(cand),
    ).score


# -- tokenization -------------------------------------------------------------


def test_tokenizer_keeps_technical_punctuation():
    # A curated alias normalizes "node.js" to "node"; "c++"/"c#" are kept whole.
    assert normalize_term("Node.js") == "node"
    assert "node" in tokenize("Experience with Node.js")
    assert "c++" in tokenize("C++ and C#")
    assert "c#" in tokenize("C++ and C#")


def test_single_letter_tokens_are_dropped():
    # A bare "C" cannot be allowed to match an unrelated word.
    assert "c" not in tokenize("Proficient in C programming")


def test_java_does_not_match_javascript():
    assert normalize_term("Java") == "java"
    assert normalize_term("JavaScript") == "javascript"
    index = Bm25Index(
        [job(id="j", title="Backend", description="We use Java for backend services")]
    )
    java_dev = profile(skills=["Java"])
    js_dev = profile(skills=["JavaScript"])
    assert index.score("j", candidate_tokens(java_dev)) > 0
    # The JS developer's only token is "javascript", which the document lacks.
    assert index.score("j", candidate_tokens(js_dev)) == 0


def test_aliases_are_limited_and_equivalent():
    assert normalize_term("k8s") == "kubernetes"
    assert normalize_term("Postgres") == "postgresql"


# -- BM25 relevance -----------------------------------------------------------


def test_requirement_buried_in_a_long_description_is_found():
    buried = job(
        id="buried",
        title="Backend Engineer",
        description=("word " * 400) + "You will work with Kubernetes and Terraform daily.",
    )
    unrelated = job(
        id="unrelated",
        title="Backend Engineer",
        description=("word " * 400) + "You will maintain spreadsheets.",
    )
    cand = profile(skills=["Kubernetes", "Terraform"])
    assert score(buried, cand, [buried, unrelated]) > score(unrelated, cand, [buried, unrelated])


def test_exact_skill_in_description_but_not_in_required_skills():
    listing = job(required_skills=[], description="Strong Kubernetes experience required.")
    cand = profile(skills=["Kubernetes"])
    result = lexical_score(
        listing,
        index=Bm25Index([listing]),
        candidate_token_list=candidate_tokens(cand),
        candidate_text=candidate_lexical_text(cand),
    )
    assert "kubernetes" in result.matched_keywords
    assert result.score > 0


def test_unrelated_description_scores_low():
    listing = job(description="We need a florist with retail experience.")
    cand = profile(skills=["Kubernetes", "Terraform", "Go"])
    result = lexical_score(
        listing,
        index=Bm25Index([listing]),
        candidate_token_list=candidate_tokens(cand),
        candidate_text=candidate_lexical_text(cand),
    )
    assert result.score < 20.0


def test_title_hits_weigh_more_than_body_hits():
    titled = job(id="t", title="Kubernetes Engineer", description="generic text here")
    body = job(id="b", title="Engineer", description="generic kubernetes text here")
    cand = profile(skills=["Kubernetes"])
    assert score(titled, cand, [titled, body]) > score(body, cand, [titled, body])


# -- phrases ------------------------------------------------------------------


def test_required_multiword_phrase_is_preserved():
    listing = job(required_skills=["machine learning"])
    cand = profile(skills=["machine learning"], summary="Built machine learning pipelines")
    result = lexical_score(
        listing,
        index=Bm25Index([listing]),
        candidate_token_list=candidate_tokens(cand),
        candidate_text=candidate_lexical_text(cand),
    )
    assert "machine learning" in result.matched_phrases


def test_missing_phrase_reported():
    listing = job(required_skills=["machine learning"])
    cand = profile(skills=["python"])
    result = lexical_score(
        listing,
        index=Bm25Index([listing]),
        candidate_token_list=candidate_tokens(cand),
        candidate_text=candidate_lexical_text(cand),
    )
    assert "machine learning" in result.missing_phrases


# -- normalization ------------------------------------------------------------


def test_scale_is_absolute_and_bounded():
    assert Bm25Index.scale(0.0) == 0.0
    assert Bm25Index.scale(1e9) <= 100.0
    assert Bm25Index.scale(BM25_HALF_SATURATION) == 50.0
    # Monotonic.
    assert Bm25Index.scale(2.0) < Bm25Index.scale(4.0)


def test_ranking_is_stable_across_repeated_runs():
    listings = [
        job(id=f"j{i}", title=f"Engineer {i}", description="python fastapi kubernetes terraform")
        for i in range(5)
    ]
    cand = profile(skills=["python", "fastapi"])
    first = [score(listing, cand, listings) for listing in listings]
    second = [score(listing, cand, listings) for listing in listings]
    assert first == second


def test_candidate_query_excludes_contact_information():
    cand = CandidateProfile(
        personal_information=PersonalInformation(
            title="Engineer", email="me@example.com", phone="123"
        ),
        skills=["python"],
    )
    text = candidate_lexical_text(cand)
    assert "me@example.com" not in text
    assert "123" not in text


def test_candidate_query_uses_experience_bullets_and_projects():
    cand = profile(
        skills=["python"],
        experience=[ExperienceEntry(title="Engineer", bullets=["Built a Terraform module"])],
        projects=[ProjectEntry(name="Widget", tech="Kubernetes")],
    )
    text = candidate_lexical_text(cand)
    assert "Terraform" in text and "Kubernetes" in text
