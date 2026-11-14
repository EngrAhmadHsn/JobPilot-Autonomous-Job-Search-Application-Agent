"""WS-26 Phase 2 · The same posting on two providers is one row.

The registry docstring said the dedup ran "across sources" and the code never
did: every key in ``src/jobs/deduplicate.py`` includes ``job.source``, so
Greenhouse and Ashby rows for one posting are two rows. This is the merge key
that fixes it, and it is deliberately **not** a replacement for the per-source
identity — a source's own rows must never collapse into each other.

Scoping, measured on the live 8,558-listing corpus on 2026-11-13: **zero**
cross-source groups exist under three normalization strengths (exact,
punctuation-stripped, and company-suffix/title-abbreviation normalized). So
the exact key lands and the spec's fuzzy MinHash path (§3.2) stays unbuilt:
there is no duplicate for it to collapse, and a fuzzy matcher with no
evidence is a way to merge two genuinely different postings.
"""

from __future__ import annotations

from src.jobs.contracts import JobListing
from src.jobs.cross_source import (
    COMPLETENESS_FIELDS,
    cross_source_key,
    merge_cross_source,
)
from src.jobs.deduplicate import deduplicate


def _listing(
    job_id: str,
    source: str,
    *,
    title: str = "Senior Backend Engineer",
    company: str = "Acme",
    location: str | None = "London",
    **extra,
) -> JobListing:
    return JobListing(
        id=f"{source}:{job_id}",
        source=source,
        source_job_id=job_id,
        title=title,
        company=company,
        location=location,
        **extra,
    )


# -- the key -----------------------------------------------------------------


def test_the_same_posting_on_two_sources_shares_a_key() -> None:
    assert cross_source_key(_listing("1", "greenhouse")) == cross_source_key(_listing("9", "ashby"))


def test_a_different_title_does_not_share_a_key() -> None:
    a = _listing("1", "greenhouse", title="Backend Engineer")
    b = _listing("2", "ashby", title="Frontend Engineer")
    assert cross_source_key(a) != cross_source_key(b)


def test_a_different_company_does_not_share_a_key() -> None:
    a = _listing("1", "greenhouse", company="Acme")
    b = _listing("2", "ashby", company="Globex")
    assert cross_source_key(a) != cross_source_key(b)


def test_spelling_of_case_and_whitespace_does_not_matter() -> None:
    a = _listing("1", "greenhouse", title="Senior  Backend Engineer", company="ACME")
    b = _listing("2", "ashby", title="senior backend engineer", company="acme")
    assert cross_source_key(a) == cross_source_key(b)


def test_a_legal_suffix_on_the_company_does_not_matter() -> None:
    a = _listing("1", "greenhouse", company="Acme Inc.")
    b = _listing("2", "ashby", company="Acme")
    assert cross_source_key(a) == cross_source_key(b)


def test_a_listing_without_a_company_cannot_be_keyed() -> None:
    """An unkeyable listing is never merged — a merge claims two rows are one."""
    assert cross_source_key(_listing("1", "greenhouse", company="   ")) is None


def test_a_listing_without_a_title_cannot_be_keyed() -> None:
    assert cross_source_key(_listing("1", "greenhouse", title="")) is None


def test_a_missing_location_is_part_of_the_key() -> None:
    """No location is not the same as a location; merging them would be a guess."""
    with_location = _listing("1", "greenhouse", location="London")
    without = _listing("2", "ashby", location=None)
    assert cross_source_key(with_location) != cross_source_key(without)


# -- the merge ---------------------------------------------------------------


def test_two_sources_publishing_one_posting_yield_one_row() -> None:
    merged = merge_cross_source([_listing("1", "greenhouse"), _listing("9", "ashby")])
    assert len(merged) == 1
    assert merged[0].source == "greenhouse"  # first-seen keeps the identity
    assert merged[0].id == "greenhouse:1"


def test_two_listings_from_one_source_are_never_merged() -> None:
    """The per-source identity is not this key's to collapse."""
    same_source = [_listing("1", "greenhouse"), _listing("2", "greenhouse")]
    assert len(merge_cross_source(same_source)) == 2


def test_a_different_location_does_not_merge() -> None:
    rows = [
        _listing("1", "greenhouse", location="London"),
        _listing("9", "ashby", location="Berlin"),
    ]
    assert len(merge_cross_source(rows)) == 2


def test_an_unkeyable_listing_survives_the_merge() -> None:
    rows = [_listing("1", "greenhouse"), _listing("9", "ashby", company="")]
    assert len(merge_cross_source(rows)) == 2


def test_three_sources_publishing_one_posting_yield_one_row() -> None:
    rows = [
        _listing("1", "greenhouse"),
        _listing("9", "ashby"),
        _listing("4", "lever"),
    ]
    assert len(merge_cross_source(rows)) == 1


def test_the_merge_preserves_the_input_order_of_the_survivors() -> None:
    rows = [
        _listing("2", "greenhouse", title="Data Engineer"),
        _listing("1", "greenhouse"),
        _listing("9", "ashby"),
    ]
    merged = merge_cross_source(rows)
    assert [job.title for job in merged] == ["Data Engineer", "Senior Backend Engineer"]


# -- the precedence rule (§3.3) ----------------------------------------------


def test_the_more_complete_source_wins_a_disagreement() -> None:
    thin = _listing("1", "greenhouse")
    rich = _listing(
        "9",
        "ashby",
        salary="GBP 90k",
        currency="GBP",
        remote_policy="hybrid",
        employment_type="full-time",
        seniority="senior",
        description="A long posting.",
        required_skills=["python", "sql"],
    )
    merged = merge_cross_source([thin, rich])
    assert len(merged) == 1
    # The richer listing supplies the facts; the first-seen keeps the identity.
    assert merged[0].id == "greenhouse:1"
    assert merged[0].source == "greenhouse"
    assert merged[0].salary == "GBP 90k"
    assert merged[0].currency == "GBP"
    assert merged[0].seniority == "senior"
    assert merged[0].required_skills == ["python", "sql"]


def test_first_seen_wins_a_tie() -> None:
    equal_a = _listing("1", "greenhouse", salary="GBP 90k")
    equal_b = _listing("9", "ashby", salary="EUR 100k")
    merged = merge_cross_source([equal_a, equal_b])
    assert len(merged) == 1
    assert merged[0].salary == "GBP 90k"


def test_a_field_the_survivor_has_is_not_blanked_by_a_thinner_listing() -> None:
    """Filling a gap is the point; emptying a value is not."""
    rich = _listing("1", "greenhouse", salary="GBP 90k", seniority="senior")
    thin = _listing("9", "ashby", description="A long posting about the role.")
    merged = merge_cross_source([rich, thin])
    assert len(merged) == 1
    assert merged[0].salary == "GBP 90k"
    assert merged[0].seniority == "senior"
    # And the thin one still contributed the field it had.
    assert merged[0].description is not None


def test_the_identity_fields_are_never_overwritten() -> None:
    """The canonical id is ``{source}:{source_job_id}`` and it survives."""
    first = _listing("1", "greenhouse")
    richer = _listing("9", "ashby", description="A long posting.")
    merged = merge_cross_source([first, richer])
    assert merged[0].id == "greenhouse:1"
    assert merged[0].source_job_id == "1"


def test_completeness_counts_the_documented_field_set() -> None:
    """The score is data, not a private heuristic — it is listed and testable."""
    bare = _listing("1", "greenhouse")
    rich = _listing(
        "9",
        "ashby",
        description="d",
        salary="s",
        currency="c",
        remote_policy="r",
        employment_type="e",
        seniority="sen",
        experience_requirements="x",
        required_skills=["a", "b"],
    )
    from src.jobs.cross_source import field_completeness

    assert field_completeness(bare) < field_completeness(rich)
    assert set(COMPLETENESS_FIELDS) >= {
        "description",
        "salary",
        "currency",
        "remote_policy",
        "employment_type",
        "seniority",
        "experience_requirements",
    }


# -- extra_metadata (§3.1, with the one exception that matters) --------------


def test_informational_metadata_travels_with_the_merge() -> None:
    thin = _listing("1", "greenhouse")
    rich = _listing("9", "ashby", metadata={"team": "Payments", "country": "GB"})
    merged = merge_cross_source([thin, rich])
    assert merged[0].metadata["team"] == "Payments"
    assert merged[0].metadata["country"] == "GB"


def test_the_change_stamp_never_crosses_a_source_boundary() -> None:
    """``updated_at`` is the delta refresh's per-source clock, not a fact.

    ``registry._stored_update_stamps`` reads it back per *source* to decide
    what the delta refresh must re-fetch. Copying another provider's stamp
    into the survivor would make one source's bookkeeping carry another's
    timestamp — so its next refresh either re-fetches everything forever or
    reads a foreign stamp as "unchanged" and silently misses a real edit.
    """
    mine = _listing("1", "greenhouse", metadata={"updated_at": "2026-11-01T00:00:00Z"})
    theirs = _listing(
        "9",
        "ashby",
        metadata={"updated_at": "2026-11-13T00:00:00Z", "team": "Payments"},
    )
    merged = merge_cross_source([mine, theirs])
    assert merged[0].id == "greenhouse:1"
    assert merged[0].metadata["updated_at"] == "2026-11-01T00:00:00Z"
    # …and the informational key still arrived.
    assert merged[0].metadata["team"] == "Payments"


def test_a_stamp_is_not_adopted_when_the_survivor_states_none() -> None:
    """No stamp is not the same as another source's stamp.

    The survivor here publishes no ``updated_at``. Adopting the other
    provider's would be a *claim* about this source's freshness that this
    source never made, and the delta refresh would then treat the listing as
    recently changed when its own board may not have been reached at all.
    """
    mine = _listing("1", "greenhouse", metadata={"team": "Payments"})
    theirs = _listing("9", "ashby", metadata={"updated_at": "2026-11-13T00:00:00Z"})
    merged = merge_cross_source([mine, theirs])
    assert "updated_at" not in merged[0].metadata


def test_an_unknown_metadata_key_does_not_travel() -> None:
    """An adapter's private bookkeeping stays with the row that owns it."""
    thin = _listing("1", "greenhouse")
    rich = _listing(
        "9",
        "ashby",
        metadata={"team": "Payments", "ashby_internal_paging": {"cursor": "abc"}},
    )
    merged = merge_cross_source([thin, rich])
    assert merged[0].metadata["team"] == "Payments"
    assert "ashby_internal_paging" not in merged[0].metadata


def test_metadata_is_not_shared_between_the_input_and_the_result() -> None:
    """The merge is pure, so the caller's listing must not be mutated."""
    thin = _listing("1", "greenhouse", metadata={"team": "Payments"})
    rich = _listing("9", "ashby", metadata={"country": "GB"})
    merged = merge_cross_source([thin, rich])
    merged[0].metadata["injected"] = "value"
    assert "injected" not in thin.metadata


# -- composition with the existing per-source dedup --------------------------


def test_composed_dedup_keeps_same_source_rows_and_collapses_cross_source() -> None:
    rows = [
        _listing("1", "greenhouse"),
        _listing("1", "greenhouse"),  # a true per-source duplicate
        _listing("9", "ashby"),  # the same posting, another provider
        _listing("2", "greenhouse", title="Data Engineer"),  # a different role
    ]
    assert len(merge_cross_source(deduplicate(rows))) == 2


def test_the_merge_is_pure() -> None:
    """The caller's listings are not mutated: the pipeline may still read them."""
    a = _listing("1", "greenhouse")
    b = _listing("9", "ashby", salary="GBP 90k")
    original = a.model_copy(deep=True)
    merge_cross_source([a, b])
    assert a.model_dump() == original.model_dump()
