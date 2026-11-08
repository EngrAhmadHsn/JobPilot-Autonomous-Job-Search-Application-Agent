"""A deterministic résumé style policy — AI jargon, weak verbs, quantification (WS-22).

**Why a policy and not a prompt tweak.** A generated résumé that reads like
every other generated résumé is a real quality problem: "leverage", "synergy",
"seamlessly", "passionate about" are the fingerprints of a model writing
filler, and a recruiter reads them as such. The reference implementation
that inspired this (JobHunter AI's ``resume_rewrite.md``) solved it with
prompt rules alone; a prompt rule is a request, not a control. This module
supplies **both halves from one source**:

1. the ban list is injected into the tailoring prompt from these constants,
   so the prompt and the checker can never drift apart;
2. the answer is analysed deterministically, and the findings travel with the
   tailoring result — including when the model ignored the rule.

**It reports; it does not rewrite.** A deterministic rewriter would have to
guess at meaning ("leverage our platform" → "use our platform" is right;
"leverage" as a noun is not). The operator sees the finding and decides — the
same division of labour as the factuality validator.

**Quantification is a nudge, never a fabrication.** The count of bullets that
carry a number is reported, and the prompt asks for numbers *the profile
supports*; a model that invents "increased revenue 40%" would be caught by
the factuality rules long before this module saw it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, Field

__all__ = [
    "BUZZWORDS",
    "PROMPT_STYLE_RULES",
    "STRONG_VERBS",
    "STYLE_CATEGORY_BUZZWORD",
    "STYLE_CATEGORY_WEAK_PHRASE",
    "WEAK_PHRASES",
    "StyleFinding",
    "StyleReport",
    "analyze_style",
    "analyze_tailored",
]

STYLE_CATEGORY_BUZZWORD = "buzzword"
STYLE_CATEGORY_WEAK_PHRASE = "weak_phrase"

#: Phrases that mark generated filler, and what to say instead. The
#: suggestions are deliberately concrete: "remove it" is the honest advice
#: for a word that carries no information.
BUZZWORDS: tuple[tuple[str, str], ...] = (
    ("leverage", "use"),
    ("utilize", "use"),
    ("synergy", "say what the two teams did together"),
    ("synergies", "say what the two teams did together"),
    ("paradigm", "say what changed"),
    ("holistic", "say what the whole covered"),
    ("seamlessly", "say what worked without friction"),
    ("cutting-edge", "name the technology"),
    ("state-of-the-art", "name the technology"),
    ("world-class", "show the evidence"),
    ("best-in-class", "show the evidence"),
    ("results-driven", "state the result"),
    ("data-driven", "name the signal you used"),
    ("dynamic environment", "describe the environment"),
    ("fast-paced environment", "describe the pace in facts"),
    ("passionate about", "say what you built"),
    ("team player", "say what you did for the team"),
    ("go-getter", "remove it"),
    ("self-starter", "remove it"),
    ("think outside the box", "name the solution"),
    ("hit the ground running", "name what you delivered first"),
    ("proven track record", "name the record"),
    ("detail-oriented", "show the detail"),
    ("game-changer", "remove it"),
    ("empower", "say who could then do what"),
    ("empowered", "say who could then do what"),
    ("robust solutions", "name what held up under what load"),
    ("value-add", "name the value"),
    ("wheelhouse", "say what you know"),
    ("ninja", "remove it"),
    ("guru", "remove it"),
)

#: Phrases that describe a job instead of an achievement.
WEAK_PHRASES: tuple[tuple[str, str], ...] = (
    ("responsible for", "led / owned / delivered"),
    ("duties included", "say what you achieved"),
    ("helped with", "say what part you did"),
    ("assisted with", "say what you did"),
    ("worked on", "built / shipped / delivered"),
    ("participated in", "say what you contributed"),
    ("involved in", "say what you owned"),
    ("tasked with", "say what you delivered"),
)

#: Verbs that carry a result. Offered as a preference, never as a rule.
STRONG_VERBS: tuple[str, ...] = (
    "led",
    "built",
    "shipped",
    "delivered",
    "designed",
    "implemented",
    "migrated",
    "automated",
    "reduced",
    "raised",
    "cut",
    "scaled",
    "debugged",
    "refactored",
    "mentored",
    "launched",
    "replaced",
    "measured",
)

#: The prompt half of the policy, built **from the constants above** so the
#: list the model is given and the list it is checked against are one list.
PROMPT_STYLE_RULES = (
    "STYLE RULES (a resume a human would write):\n"
    "- Never use these words or phrases: "
    + ", ".join(f'"{phrase}"' for phrase, _ in BUZZWORDS)
    + ".\n"
    "- Do not write these phrases: "
    + ", ".join(f'"{phrase}"' for phrase, _ in WEAK_PHRASES)
    + ".\n"
    "- Start bullets with a strong verb such as: " + ", ".join(STRONG_VERBS) + ".\n"
    "- Quantify a bullet when the profile contains the number; never invent a"
    " number, a percentage or a count that is not in the profile.\n"
)

_QUANTIFIED_RE = re.compile(r"\d")


class StyleFinding(BaseModel):
    """One phrase worth changing, and where it appeared."""

    category: str
    phrase: str
    suggestion: str
    snippet: str = Field(..., description="The sentence or bullet that carried it")


class StyleReport(BaseModel):
    """The deterministic style verdict on a piece of tailored writing.

    ``quantified_ratio`` is the share of *bullets* that carry a number — the
    one soft signal here, reported rather than judged: a résumé for a role
    with nothing measurable has a low ratio honestly.
    """

    findings: list[StyleFinding] = Field(default_factory=list)
    bullet_count: int = 0
    quantified_count: int = 0
    quantified_ratio: float = 0.0

    @property
    def clean(self) -> bool:
        """True when no banned or weak phrase was found."""
        return not self.findings


def _snippet(text: str, phrase: str) -> str:
    """The sentence (or bullet) around *phrase*, trimmed for display."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if phrase in sentence.lower():
            return sentence.strip()[:300]
    return text.strip()[:300]


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """The matcher for one banned phrase.

    Two decisions, both deliberate:

    - **Word boundaries**, so "leverage" does not fire inside "unleveraged"
      or any longer word;
    - **the common inflections**, so "leverages", "leveraged" and
      "leveraging" are the same finding as "leverage". The prompt names the
      stem, and a model told not to write "leverage" writes "leveraging" —
      a checker that only caught the base form would be checking the wrong
      thing.

    A phrase that ends in ``e`` elides it before a suffix
    ("leverage" → "leveraging", not "leverageing"), so the pattern is built
    from the stem where that applies.
    """
    stem = phrase.removesuffix("e")
    return re.compile(
        rf"(?<![\w]){re.escape(stem)}(?:e|es|ed|ing|s|d)?(?![\w])",
        re.IGNORECASE,
    )


def _find(text: str, table: Iterable[tuple[str, str]], category: str) -> list[StyleFinding]:
    """The table's phrases that appear in *text* (see :func:`_phrase_pattern`)."""
    findings: list[StyleFinding] = []
    for phrase, suggestion in table:
        if _phrase_pattern(phrase).search(text):
            findings.append(
                StyleFinding(
                    category=category,
                    phrase=phrase,
                    suggestion=suggestion,
                    snippet=_snippet(text, phrase),
                )
            )
    return findings


def analyze_style(text: str) -> StyleReport:
    """Analyse one block of prose (a summary, a cover letter, a bullet)."""
    if not text or not text.strip():
        return StyleReport()
    findings = _find(text, BUZZWORDS, STYLE_CATEGORY_BUZZWORD) + _find(
        text, WEAK_PHRASES, STYLE_CATEGORY_WEAK_PHRASE
    )
    return StyleReport(findings=findings)


def analyze_tailored(tailored) -> StyleReport:
    """Analyse a whole :class:`~src.resume.tailor.TailoredResume`.

    The unit of quantification is the **bullet** (experience and projects):
    that is where achievement claims live, and a summary sentence carrying a
    number says nothing about whether the bullets do.
    """
    bullets: list[str] = []
    blocks: list[str] = [tailored.summary, tailored.cover_letter]
    for entry in tailored.experience:
        bullets.extend(entry.bullets)
    for project in tailored.projects:
        bullets.extend(project.bullets)
    blocks.extend(bullets)

    findings: list[StyleFinding] = []
    for block in blocks:
        findings.extend(analyze_style(block).findings)

    quantified = [bullet for bullet in bullets if _QUANTIFIED_RE.search(bullet)]
    total = len(bullets)
    return StyleReport(
        findings=findings,
        bullet_count=total,
        quantified_count=len(quantified),
        quantified_ratio=(len(quantified) / total) if total else 0.0,
    )
