"""WS-22 · the two-way PII mask (Phase B3).

The claim this file exists to make true is narrow and testable:

> **The prompt a tailoring run sends contains no candidate identity, and the
> answer comes back with the real values restored.**

So the central test captures the prompt with a fake generator and greps it
for every identity string the profile carried. Around it sit the unit tests
that make the mask itself trustworthy: determinism, longest-first masking,
the third-party sweep over listing text, and the handling of a placeholder
the model mangled (drop the sentence, record the violation, ship nothing).
"""

from __future__ import annotations

from src.jobs.contracts import JobListing
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    ProjectEntry,
)
from src.resume.tailor import (
    TailoredExperience,
    TailoredProject,
    TailoredResume,
    tailor_resume,
)
from src.security.pii import PiiVault, build_vault_for_profile

NAME = "Ada Lovelace"
EMAIL = "ada.lovelace@example.com"
PHONE = "+44 7700 900123"
LINKEDIN = "linkedin.com/in/ada-lovelace"
GITHUB = "github.com/ada-lovelace"

PROFILE = CandidateProfile(
    personal_information=PersonalInformation(
        name=NAME,
        email=EMAIL,
        phone=PHONE,
        # A résumé prints its profile links in free text, not in dedicated
        # fields — which is exactly why the vault sweeps the prompt text
        # instead of trusting the structured identity fields alone.
        website=LINKEDIN,
    ),
    location="London",
    experience=[ExperienceEntry(title="AI Engineer", company="Agentic Labs", years=5)],
    skills=["python", "langgraph", "pydantic"],
    projects=[
        ProjectEntry(
            name="Autonomous Job Agent",
            bullets=["Agentic job system", f"Source and notes: {GITHUB}"],
        )
    ],
)

# A listing that carries a *recruiter's* address and a tracking link — third
# party identity that must not reach the provider through our prompt either.
JOB = JobListing(
    id="job-1",
    source="greenhouse",
    title="AI Engineer",
    company="Acme AI",
    required_skills=["python", "langgraph"],
    description=(
        "Questions? Write to talent@acme.example or see "
        "https://acme.example/careers/12345 for details."
    ),
    application_url="https://acme.example/careers/12345",
)


def _generator(captured: list[str], **overrides):
    """A fake model that records the prompt it was handed."""

    def generate(prompt, schema):
        captured.append(prompt)
        return TailoredResume(
            summary=overrides.get("summary") or "AI engineer with 5 years of experience.",
            highlighted_skills=overrides.get("highlighted_skills") or ["python", "langgraph"],
            experience=overrides.get("experience")
            or [
                TailoredExperience(
                    company="Agentic Labs",
                    title="AI Engineer",
                    bullets=["Built autonomous agent pipeline with LangGraph"],
                )
            ],
            projects=overrides.get("projects")
            or [TailoredProject(name="Autonomous Job Agent", bullets=["Built agent pipeline"])],
            cover_letter=overrides.get("cover_letter") or "I am excited about the role.",
        )

    return generate


# -- the vault itself ---------------------------------------------------------


class TestTheVault:
    def test_it_masks_and_restores_exactly(self) -> None:
        # The vault production builds: the structured identity fields plus a
        # sweep of the text going into the prompt (where a résumé keeps its
        # profile links).
        vault = build_vault_for_profile(PROFILE, texts=(PROFILE.model_dump_json(),))
        text = f"{NAME} can be reached at {EMAIL} or {PHONE}; profiles: {LINKEDIN}, {GITHUB}."
        masked = vault.mask(text)

        for secret in (NAME, EMAIL, PHONE, LINKEDIN, GITHUB):
            assert secret not in masked
        assert "[[NAME]]" in masked
        assert vault.restore_text(masked) == text

    def test_the_identity_fields_alone_do_not_carry_free_text_links(self) -> None:
        """add_identity is the structured half; the sweep is the other half.

        Pinned as a test because it is the reason the sweep exists: a
        profile link that lives in a bullet is invisible to the structured
        fields.
        """
        structured_only = PiiVault()
        structured_only.add_identity(PROFILE.personal_information)
        assert structured_only.mask(GITHUB) == GITHUB

    def test_the_tokens_are_deterministic(self) -> None:
        first = build_vault_for_profile(PROFILE)
        second = build_vault_for_profile(PROFILE)
        target = f"{NAME} / {EMAIL} / {GITHUB}"
        assert first.mask(target) == second.mask(target)

    def test_a_longer_value_is_masked_before_a_shorter_one(self) -> None:
        vault = PiiVault()
        vault.add("LINK", "github.com/ada")
        vault.scan_text("see github.com/ada/projects")
        masked = vault.mask("see github.com/ada/projects")
        assert "github.com/ada" not in masked
        assert vault.restore_text(masked) == "see github.com/ada/projects"

    def test_it_sweeps_third_party_identity_from_listing_text(self) -> None:
        vault = build_vault_for_profile(PROFILE, texts=(JOB.description,))
        masked = vault.mask(JOB.description)
        assert "talent@acme.example" not in masked
        assert "acme.example" not in masked
        assert "[[" in masked

    def test_it_does_not_eat_legitimate_brackets(self) -> None:
        vault = build_vault_for_profile(PROFILE)
        text = "Used [Python] and [SQL] on [AWS]."
        assert vault.mask(text) == text
        assert vault.residual_tokens(text) == []
        assert vault.strip_residual_tokens(text) == (text, [])

    def test_a_short_value_is_not_masked_as_free_text(self) -> None:
        """A two-letter 'name' would otherwise match inside other words."""
        vault = PiiVault()
        vault.add("NAME", "Al")
        assert vault.mask("Also, Alan applied.") == "Also, Alan applied."

    def test_a_mangled_placeholder_is_reported_and_stripped(self) -> None:
        vault = build_vault_for_profile(PROFILE)
        mangled = "I am [[ NAME ]] and I ship. A second sentence stays."
        assert vault.residual_tokens(mangled)
        cleaned, removed = vault.strip_residual_tokens(mangled)
        assert cleaned == "A second sentence stays."
        assert len(removed) == 1


# -- the prompt the provider sees --------------------------------------------


class TestThePromptCarriesNoIdentity:
    def test_no_candidate_identity_reaches_the_prompt(self) -> None:
        captured: list[str] = []
        tailored = tailor_resume(PROFILE, JOB, generate=_generator(captured))

        prompt = captured[0]
        for secret in (NAME, EMAIL, PHONE, LINKEDIN, GITHUB):
            assert secret not in prompt, f"{secret!r} reached the provider"
        # The mask is present, not merely absent data.
        assert "[[NAME]]" in prompt
        # The facts the tailoring needs are still there.
        for fact in ("Agentic Labs", "AI Engineer", "python", "Autonomous Job Agent"):
            assert fact in prompt
        # And the run still produced a validated result.
        assert tailored.factuality.passed

    def test_a_recruiters_address_in_the_listing_is_masked_too(self) -> None:
        captured: list[str] = []
        tailor_resume(PROFILE, JOB, generate=_generator(captured))
        prompt = captured[0]
        assert "talent@acme.example" not in prompt
        assert "acme.example/careers/12345" not in prompt
        # The employer itself is content, not identity: it stays.
        assert "Acme AI" in prompt

    def test_the_answer_is_restored_with_the_real_values(self) -> None:
        captured: list[str] = []

        def generate(prompt, schema):
            captured.append(prompt)
            # A model echoing a token, as a real one might in prose.
            return TailoredResume(
                summary="[[NAME]] built agent pipelines.",
                highlighted_skills=["python"],
                experience=[],
                projects=[],
                cover_letter="I am [[NAME]] and I would like to apply.",
            )

        result = tailor_resume(PROFILE, JOB, generate=generate)
        assert result.tailored.summary == f"{NAME} built agent pipelines."
        assert result.tailored.cover_letter.startswith(f"I am {NAME}")
        assert "[[" not in result.tailored.summary
        assert result.factuality.passed

    def test_a_mangled_placeholder_never_ships(self) -> None:
        def generate(prompt, schema):
            return TailoredResume(
                summary="I am [[ NAME ]] and I ship things. I also build pipelines.",
                highlighted_skills=["python"],
                experience=[],
                projects=[],
                cover_letter="Fine.",
            )

        result = tailor_resume(PROFILE, JOB, generate=generate)
        assert "[[" not in result.tailored.summary
        assert result.tailored.summary == "I also build pipelines."
        assert result.factuality.passed is False
        assert any("placeholder" in violation for violation in result.factuality.violations)

    def test_the_vault_holds_no_state_between_runs(self) -> None:
        first_captured: list[str] = []
        second_captured: list[str] = []
        tailor_resume(PROFILE, JOB, generate=_generator(first_captured))
        tailor_resume(
            PROFILE,
            JOB,
            generate=_generator(second_captured, summary=f"Sent by {NAME}."),
        )
        assert first_captured[0] != ""
        assert NAME not in second_captured[0]
