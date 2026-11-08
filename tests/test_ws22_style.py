"""WS-22 · the deterministic résumé style policy (Phase B4).

Two halves have to hold together, and they are tested together:

- the **analyzer** finds what it says it finds (buzzwords, weak phrases, the
  quantified-bullet ratio) and does not fire on ordinary prose;
- the **prompt** the model is given carries the same list the answer is
  checked against — one source, so the two can never drift.

The last test in the file is the interesting one for the feature's honesty:
a tailored result that used the banned words comes back **with findings**,
not silently rewritten. The policy reports; the operator decides.
"""

from __future__ import annotations

from src.jobs.contracts import JobListing
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    ProjectEntry,
)
from src.resume.style import (
    BUZZWORDS,
    PROMPT_STYLE_RULES,
    STYLE_CATEGORY_BUZZWORD,
    STYLE_CATEGORY_WEAK_PHRASE,
    WEAK_PHRASES,
    analyze_style,
    analyze_tailored,
)
from src.resume.tailor import (
    SYSTEM_RULES,
    TailoredExperience,
    TailoredProject,
    TailoredResume,
    tailor_resume,
)

PROFILE = CandidateProfile(
    personal_information=PersonalInformation(name="Ada Lovelace", email="ada@example.com"),
    experience=[ExperienceEntry(title="AI Engineer", company="Agentic Labs", years=5)],
    skills=["python", "langgraph"],
    projects=[ProjectEntry(name="Autonomous Job Agent", bullets=["Agentic job system"])],
)

JOB = JobListing(
    id="job-1",
    source="greenhouse",
    title="AI Engineer",
    company="Acme AI",
    required_skills=["python"],
)


class TestTheAnalyzer:
    def test_it_finds_a_buzzword_and_says_what_to_write_instead(self) -> None:
        report = analyze_style("I leverage synergy to empower the team.")
        phrases = {finding.phrase for finding in report.findings}
        assert {"leverage", "synergy", "empower"} <= phrases
        leverage = next(f for f in report.findings if f.phrase == "leverage")
        assert leverage.category == STYLE_CATEGORY_BUZZWORD
        assert leverage.suggestion == "use"
        assert leverage.snippet

    def test_it_finds_a_weak_phrase(self) -> None:
        report = analyze_style("Responsible for the platform and worked on migrations.")
        phrases = {finding.phrase for finding in report.findings}
        assert "responsible for" in phrases
        assert "worked on" in phrases
        assert all(
            f.category == STYLE_CATEGORY_WEAK_PHRASE
            for f in report.findings
            if f.phrase in {"responsible for", "worked on"}
        )

    def test_it_does_not_fire_on_ordinary_prose(self) -> None:
        report = analyze_style(
            "Led a team of four and shipped the payments migration, cutting p95 latency 38%."
        )
        assert report.clean

    def test_it_respects_word_boundaries_and_catches_inflections(self) -> None:
        # The left boundary holds: a longer word that merely ends in the stem
        # is not the banned phrase.
        assert "leverage" not in {
            f.phrase for f in analyze_style("Unleveraged data cut costs.").findings
        }
        # The inflections are the same finding — a model told not to write
        # "leverage" writes "leveraging", and that must still be caught.
        for variant in ("Leverages data.", "Leveraged data.", "Leveraging data."):
            assert "leverage" in {f.phrase for f in analyze_style(variant).findings}, variant

    def test_it_counts_quantified_bullets(self) -> None:
        resume = TailoredResume(
            summary="Engineer.",
            highlighted_skills=["python"],
            experience=[
                TailoredExperience(
                    company="Agentic Labs",
                    title="AI Engineer",
                    bullets=[
                        "Cut p95 latency 38%",
                        "Mentored two engineers",
                        "Shipped 12 releases",
                    ],
                )
            ],
            projects=[TailoredProject(name="Autonomous Job Agent", bullets=["Built a pipeline"])],
            cover_letter="Hello.",
        )
        report = analyze_tailored(resume)
        assert report.bullet_count == 4
        assert report.quantified_count == 2
        assert report.quantified_ratio == 0.5

    def test_an_empty_resume_yields_an_empty_report(self) -> None:
        report = analyze_tailored(
            TailoredResume(
                summary="",
                highlighted_skills=[],
                experience=[],
                projects=[],
                cover_letter="",
            )
        )
        assert report.bullet_count == 0
        assert report.quantified_ratio == 0.0
        assert report.clean


class TestThePromptAndTheCheckerAgree:
    def test_every_banned_phrase_is_in_the_prompt_rules(self) -> None:
        for phrase, _ in BUZZWORDS:
            assert f'"{phrase}"' in PROMPT_STYLE_RULES
        for phrase, _ in WEAK_PHRASES:
            assert f'"{phrase}"' in PROMPT_STYLE_RULES

    def test_the_tailoring_prompt_carries_the_style_rules(self) -> None:
        assert "STYLE RULES" in SYSTEM_RULES
        captured: list[str] = []

        def generate(prompt, schema):
            captured.append(prompt)
            return TailoredResume(
                summary="Engineer.",
                highlighted_skills=["python"],
                experience=[],
                projects=[],
                cover_letter="Hello.",
            )

        tailor_resume(PROFILE, JOB, generate=generate)
        prompt = captured[0]
        assert "STYLE RULES" in prompt
        assert '"leverage"' in prompt
        assert '"responsible for"' in prompt
        # The quantification rule must not invite a fabricated number.
        assert "never invent" in prompt


class TestThePolicyReportsRatherThanRewrites:
    def test_a_jargon_ridden_answer_is_reported_not_silently_changed(self) -> None:
        def generate(prompt, schema):
            return TailoredResume(
                summary="A results-driven engineer who leverages synergy.",
                highlighted_skills=["python"],
                experience=[
                    TailoredExperience(
                        company="Agentic Labs",
                        title="AI Engineer",
                        bullets=["Responsible for the platform"],
                    )
                ],
                projects=[],
                cover_letter="I am passionate about dynamic environments.",
            )

        result = tailor_resume(PROFILE, JOB, generate=generate)

        # The text is delivered as the model wrote it (factuality permitting)…
        assert "leverage" in result.tailored.summary.lower()
        assert result.tailored.experience[0].bullets == ["Responsible for the platform"]
        # …and the style report says exactly what is wrong with it.
        phrases = {finding.phrase for finding in result.style.findings}
        assert {"leverage", "results-driven", "synergy", "responsible for"} <= phrases
        assert result.style.clean is False
        assert all(finding.suggestion for finding in result.style.findings)
