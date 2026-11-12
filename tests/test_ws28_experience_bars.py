"""WS-28 · The miner must not discard a bar that names a domain, not a tool.

The technology rule exists so "3 years with Python" is not read as a total
bar. It fired on every noun, so it also discarded "7+ years of sales
experience" — a total bar the listing states plainly. Measured on the live
corpus: 1,145 listings gain a bar, 90 change value.
"""

from __future__ import annotations

import pytest

from src.matching.experience import required_years


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


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Minimum requirements 7+ years of sales or prospecting experience.", 7.0),
        ("5+ years of software sales experience selling to enterprises.", 5.0),
        ("Minimum of 3 years of experience in a Customer Success role.", 3.0),
        ("9+ years of experience in customer support and operations.", 9.0),
        ("2+ years of industry experience, with cloud security preferred.", 2.0),
        ("4+ years of experience in a technical support environment.", 4.0),
    ],
)
def test_a_domain_bar_is_a_total_bar(description, expected):
    """A bar naming a domain the candidate could work in is the total bar."""
    assert required_years(_listing(description=description)) == expected


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("3+ years of experience with Python and Django.", None),
        ("4 years of professional experience using React.", None),
        ("2 years with Kubernetes in production.", None),
    ],
)
def test_a_technology_bar_is_still_not_a_total_bar(description, expected):
    """The rule the fix must not break: a real tool is not a total bar."""
    assert required_years(_listing(description=description)) is expected


def test_an_empty_description_is_minable():
    """An empty string is not a crash and not a bar."""
    assert required_years(_listing(description="")) is None


def test_the_board_stated_requirement_still_wins():
    """``experience_requirements`` is searched first and is still honoured."""
    assert (
        required_years(
            _listing(
                experience_requirements="5+ years required",
                description="Unrelated prose about the team.",
            )
        )
        == 5.0
    )
