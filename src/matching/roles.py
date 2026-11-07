"""Occupational-role classification and candidate target roles (WS-21).

The matching engine could compare *skills* but not *professions*. A Web
Developer possessed SQL and Python; a Data Analyst listing required exactly
SQL; the skill component scored 100 % and the analyst role ranked top-10 —
because nothing anywhere compared what kind of work the listing actually is.

This module is that missing signal, and it is deliberately **deterministic**:
no model is consulted, no per-pair call is made, and every classification can
be replayed from the listing's own words. It answers three questions:

1. **What role is this listing?** ``classify_job_role(job)`` — a job-family
   classification from three evidence tiers, strongest first: the *title*
   (a role is what it is called), *responsibility phrases* in the description
   (what the work actually is), and *technologies* (weak, shared, and never
   sufficient alone). A technology mention does not confer a profession: a
   listing is not a data role because it says "SQL".
2. **What roles does the candidate want?** ``resolve_candidate_targets`` —
   the user's confirmed ``target_roles`` first (authoritative, even when
   giving a classification no editor would), a labelled *inference* from the
   confirmed current title, the résumé headline, or the most recent roles
   otherwise. A target the user cleared is never silently re-inferred.
3. **How compatible are they?** ``role_relevance`` — a coarse, documented
   band table (SAME 100 / NEAR 85 / ADJACENT 65 / TANGENT 40 / WEAK 20 /
   UNRELATED 5), an ambiguity blend so a half-classified listing cannot ride
   its best reading to a high score, and a people-management penalty for a
   manager-track listing against an individual-contributor target.

The engine turns this into the eighth component (``role``) and a hard cap:
a listing whose role is WEAK or UNRELATED can never read as a match
(``ROLE_MISMATCH_CAP`` sits below the evaluation's decision threshold).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from src.jobs.contracts import JobListing
from src.resume.profile import CandidateProfile

__all__ = [
    "ROLE_FAMILIES",
    "ROLE_MISMATCH_CAP",
    "UNRELATED_ROLE_MAX",
    "CandidateTargets",
    "RoleClassification",
    "RoleRelevance",
    "classify_job_role",
    "compatibility",
    "resolve_candidate_targets",
    "role_relevance",
]

#: The families the taxonomy knows. Chosen from the corpus's own title
#: vocabulary (6 696 stored listings) rather than an abstract org chart, so
#: every family is one a real listing in this system claims to be.
ROLE_FAMILIES: tuple[str, ...] = (
    "web_development",
    "software_engineering",
    "mobile_development",
    "data_analytics",
    "data_science_ml",
    "data_engineering",
    "devops_cloud",
    "security",
    "qa_testing",
    "hardware_physical_design",
    "embedded_firmware",
    "product_management",
    "design_ux",
    "operations_program",
    "sales",
    "marketing",
    "customer_support",
    "finance_legal_compliance",
    "people_hr",
    "research",
)

#: Human labels for the explanation text and the console.
FAMILY_LABELS: dict[str, str] = {
    "web_development": "web development",
    "software_engineering": "software engineering",
    "mobile_development": "mobile development",
    "data_analytics": "data / business analytics",
    "data_science_ml": "data science / machine learning",
    "data_engineering": "data engineering",
    "devops_cloud": "devops / cloud infrastructure",
    "security": "security",
    "qa_testing": "quality / test engineering",
    "hardware_physical_design": "hardware / physical design",
    "embedded_firmware": "embedded / firmware",
    "product_management": "product management",
    "design_ux": "design / UX",
    "operations_program": "operations / program management",
    "sales": "sales",
    "marketing": "marketing",
    "customer_support": "customer support",
    "finance_legal_compliance": "finance / legal / compliance",
    "people_hr": "people / recruiting",
    "research": "research",
}

#: A role-unrelated listing can never read as a *match*: the overall score is
#: capped here, below the evaluation's decision threshold (30). The cap is
#: reported, never silent — see ``JobMatchResult.role_capped``.
ROLE_MISMATCH_CAP = 25.0

#: Role values below this are WEAK × track-modifier or UNRELATED.
UNRELATED_ROLE_MAX = 25.0

#: The band scores. One coarse table, documented as policy, not tuned
#: decimals: 100 same, 85 sibling specialization, 65 adjacent craft,
#: 40 tangent, 20 weak, 5 unrelated.
BAND_SAME = 100.0
BAND_NEAR = 85.0
BAND_ADJACENT = 65.0
BAND_TANGENT = 40.0
BAND_WEAK = 20.0
BAND_UNRELATED = 5.0

BAND_LABELS = {
    BAND_SAME: "same field",
    BAND_NEAR: "a sibling specialization",
    BAND_ADJACENT: "an adjacent field",
    BAND_TANGENT: "a tangent field",
    BAND_WEAK: "a weak relation",
    BAND_UNRELATED: "unrelated",
}

#: A manager-track listing against an individual-contributor target is a real
#: mismatch: the work is people, not craft.
MANAGER_TRACK_FACTOR = 0.5


def _pairs(*entries: tuple[str, str, float]) -> dict[tuple[str, str], float]:
    """Symmetric band table from ``(a, b, band)`` triples."""
    table: dict[tuple[str, str], float] = {}
    for a, b, band in entries:
        table[(a, b)] = band
        table[(b, a)] = band
    return table


#: The compatibility bands. Unlisted pairs default to WEAK — conservative on
#: purpose: an unconsidered pairing must not be able to lift a listing into a
#: match it has not earned. Every pair the corpus exercise made relevant is
#: listed explicitly.
_COMPATIBILITY: dict[tuple[str, str], float] = _pairs(
    # Software-adjacent craft.
    ("web_development", "software_engineering", BAND_ADJACENT),
    ("web_development", "mobile_development", BAND_TANGENT),
    ("web_development", "qa_testing", BAND_WEAK),
    ("web_development", "devops_cloud", BAND_TANGENT),
    ("web_development", "security", BAND_TANGENT),
    ("web_development", "design_ux", BAND_WEAK),
    ("web_development", "product_management", BAND_WEAK),
    ("web_development", "data_analytics", BAND_WEAK),
    ("web_development", "data_engineering", BAND_WEAK),
    ("web_development", "data_science_ml", BAND_WEAK),
    ("web_development", "customer_support", BAND_WEAK),
    ("web_development", "marketing", BAND_WEAK),
    ("web_development", "research", BAND_WEAK),
    # The named-unrelated cases from the WS-21 brief: a Web Developer and a
    # Physical Design Engineer (or a sales, finance, HR or ops role) are
    # different professions, not neighbours.
    ("web_development", "hardware_physical_design", BAND_UNRELATED),
    ("web_development", "embedded_firmware", BAND_UNRELATED),
    ("web_development", "sales", BAND_UNRELATED),
    ("web_development", "finance_legal_compliance", BAND_UNRELATED),
    ("web_development", "people_hr", BAND_UNRELATED),
    ("web_development", "operations_program", BAND_UNRELATED),
    ("software_engineering", "data_science_ml", BAND_NEAR),
    ("software_engineering", "devops_cloud", BAND_ADJACENT),
    ("software_engineering", "mobile_development", BAND_ADJACENT),
    ("software_engineering", "qa_testing", BAND_ADJACENT),
    ("software_engineering", "security", BAND_ADJACENT),
    ("software_engineering", "embedded_firmware", BAND_TANGENT),
    ("software_engineering", "data_analytics", BAND_WEAK),
    ("software_engineering", "data_engineering", BAND_TANGENT),
    ("software_engineering", "hardware_physical_design", BAND_WEAK),
    ("software_engineering", "product_management", BAND_TANGENT),
    # Data family siblings.
    ("data_analytics", "data_science_ml", BAND_NEAR),
    ("data_analytics", "data_engineering", BAND_ADJACENT),
    ("data_analytics", "product_management", BAND_TANGENT),
    ("data_analytics", "marketing", BAND_TANGENT),
    ("data_analytics", "operations_program", BAND_TANGENT),
    ("data_analytics", "finance_legal_compliance", BAND_TANGENT),
    ("data_science_ml", "data_engineering", BAND_ADJACENT),
    ("data_science_ml", "research", BAND_ADJACENT),
    ("data_engineering", "devops_cloud", BAND_TANGENT),
    # Hardware siblings.
    ("hardware_physical_design", "embedded_firmware", BAND_NEAR),
    ("hardware_physical_design", "qa_testing", BAND_TANGENT),
    # Operating the platform.
    ("devops_cloud", "security", BAND_ADJACENT),
    # Product and its neighbours.
    ("product_management", "design_ux", BAND_ADJACENT),
    ("product_management", "operations_program", BAND_TANGENT),
    ("product_management", "marketing", BAND_TANGENT),
    ("design_ux", "marketing", BAND_TANGENT),
    # Go-to-market siblings.
    ("sales", "marketing", BAND_ADJACENT),
    ("sales", "customer_support", BAND_WEAK),
    # Back office.
    ("operations_program", "customer_support", BAND_WEAK),
    ("operations_program", "finance_legal_compliance", BAND_WEAK),
    ("operations_program", "people_hr", BAND_WEAK),
)


def compatibility(a: str, b: str) -> float:
    """The band between two families (symmetric; unlisted pairs are WEAK)."""
    if a == b:
        return BAND_SAME
    return _COMPATIBILITY.get((a, b), BAND_WEAK)


def band_label(value: float) -> str:
    """A human phrase for a compatibility value."""
    for band in (BAND_SAME, BAND_NEAR, BAND_ADJACENT, BAND_TANGENT, BAND_WEAK, BAND_UNRELATED):
        if value >= band:
            return BAND_LABELS[band]
    return BAND_LABELS[BAND_UNRELATED]


def _pattern(phrase: str) -> re.Pattern[str]:
    """A word-boundary matcher for a normalized phrase."""
    return re.compile(rf"\b{re.escape(phrase)}\b")


def _normalize(text: str) -> str:
    """Casefold and flatten separators so 'full-stack' matches 'full stack'."""
    return re.sub(r"[-_/]+", " ", text.casefold())


def _compile(
    entries: tuple[tuple[str, str, float], ...],
) -> tuple[tuple[re.Pattern[str], str, float], ...]:
    return tuple((_pattern(phrase), family, weight) for phrase, family, weight in entries)


# --------------------------------------------------------------------------
# Signals. Three tiers, strongest first. Title = what the role is called;
# responsibility phrases = what the work is; technology = weak and shared.
# --------------------------------------------------------------------------

#: Title phrases. Weight 5 = a defining phrase ("data analyst", "physical
#: design"), 3 = a strong token ("devops", "sales"), 2 = a generic noun that
#: only classifies when nothing stronger is present ("analyst", "developer").
_TITLE_SIGNALS = _compile(
    (
        ("web developer", "web_development", 5),
        ("web engineer", "web_development", 5),
        ("frontend developer", "web_development", 5),
        ("frontend engineer", "web_development", 5),
        ("front end", "web_development", 5),
        ("web development", "web_development", 5),
        ("react developer", "web_development", 5),
        ("react engineer", "web_development", 4),
        ("full stack", "web_development", 5),
        ("shopify", "web_development", 5),
        ("wordpress", "web_development", 5),
        ("web applications developer", "web_development", 5),
        ("web application developer", "web_development", 5),
        ("ui engineer", "web_development", 4),
        ("javascript developer", "web_development", 4),
        ("software engineer", "software_engineering", 5),
        ("software developer", "software_engineering", 5),
        ("software development", "software_engineering", 4),
        ("backend", "software_engineering", 5),
        ("back end", "software_engineering", 5),
        ("api engineer", "software_engineering", 4),
        ("systems engineer", "software_engineering", 4),
        ("platform engineer", "devops_cloud", 3),
        ("infrastructure engineer", "devops_cloud", 5),
        ("site reliability", "devops_cloud", 5),
        ("devops", "devops_cloud", 5),
        ("cloud engineer", "devops_cloud", 3),
        ("sre", "devops_cloud", 5),
        ("android", "mobile_development", 5),
        ("ios", "mobile_development", 5),
        ("mobile engineer", "mobile_development", 4),
        ("mobile developer", "mobile_development", 4),
        ("flutter", "mobile_development", 4),
        ("data analyst", "data_analytics", 5),
        ("business intelligence", "data_analytics", 5),
        ("bi analyst", "data_analytics", 5),
        ("reporting analyst", "data_analytics", 5),
        ("product analyst", "data_analytics", 4),
        ("data scientist", "data_science_ml", 5),
        ("machine learning", "data_science_ml", 5),
        ("ml engineer", "data_science_ml", 5),
        ("ai engineer", "data_science_ml", 4),
        ("applied ai", "data_science_ml", 4),
        ("artificial intelligence", "data_science_ml", 3),
        ("data engineer", "data_engineering", 5),
        ("analytics engineer", "data_engineering", 4),
        ("etl", "data_engineering", 3),
        ("security engineer", "security", 5),
        ("security analyst", "security", 5),
        ("security specialist", "security", 4),
        ("appsec", "security", 4),
        ("penetration", "security", 4),
        ("soc analyst", "security", 4),
        ("security", "security", 3),
        ("physical design", "hardware_physical_design", 5),
        ("asic", "hardware_physical_design", 5),
        ("rtl", "hardware_physical_design", 5),
        ("vlsi", "hardware_physical_design", 5),
        ("design verification", "hardware_physical_design", 4),
        ("hardware engineer", "hardware_physical_design", 4),
        ("hardware", "hardware_physical_design", 2),
        ("electrical engineer", "hardware_physical_design", 4),
        ("embedded", "embedded_firmware", 5),
        ("firmware", "embedded_firmware", 5),
        ("fpga", "embedded_firmware", 4),
        ("product manager", "product_management", 5),
        ("product owner", "product_management", 4),
        ("technical product", "product_management", 4),
        ("product", "product_management", 2),
        ("ux designer", "design_ux", 5),
        ("ux engineer", "design_ux", 4),
        ("ui designer", "design_ux", 5),
        ("product designer", "design_ux", 4),
        ("brand designer", "design_ux", 4),
        ("designer", "design_ux", 3),
        ("creative", "design_ux", 3),
        ("operations manager", "operations_program", 4),
        ("operations associate", "operations_program", 4),
        ("operations", "operations_program", 3),
        ("program manager", "operations_program", 4),
        ("project manager", "operations_program", 4),
        ("business operations", "operations_program", 4),
        ("supply chain", "operations_program", 5),
        ("logistics", "operations_program", 4),
        ("account executive", "sales", 5),
        ("sales", "sales", 4),
        ("business development", "sales", 4),
        ("revenue", "sales", 3),
        ("account manager", "sales", 4),
        ("customer success", "customer_support", 4),
        ("customer support", "customer_support", 4),
        ("technical support", "customer_support", 4),
        ("support specialist", "customer_support", 4),
        ("support engineer", "customer_support", 3),
        ("marketing", "marketing", 4),
        ("growth", "marketing", 2),
        ("content", "marketing", 2),
        ("seo", "marketing", 4),
        ("social media", "marketing", 4),
        ("communications", "marketing", 3),
        ("accountant", "finance_legal_compliance", 5),
        ("finance", "finance_legal_compliance", 4),
        ("financial", "finance_legal_compliance", 4),
        ("controller", "finance_legal_compliance", 4),
        ("counsel", "finance_legal_compliance", 5),
        ("legal", "finance_legal_compliance", 4),
        ("attorney", "finance_legal_compliance", 5),
        ("paralegal", "finance_legal_compliance", 4),
        ("compliance", "finance_legal_compliance", 3),
        ("investigations", "finance_legal_compliance", 3),
        ("risk analyst", "finance_legal_compliance", 4),
        ("underwriter", "finance_legal_compliance", 4),
        ("fraud", "finance_legal_compliance", 4),
        ("recruiter", "people_hr", 5),
        ("talent", "people_hr", 3),
        ("people partner", "people_hr", 4),
        ("human resources", "people_hr", 5),
        ("research scientist", "research", 5),
        ("researcher", "research", 4),
        ("research engineer", "research", 3),
        # Generic nouns: classify only when nothing stronger is present.
        ("developer", "software_engineering", 2),
        ("engineer", "software_engineering", 1),
        ("analyst", "data_analytics", 2),
        ("scientist", "data_science_ml", 2),
    )
)

#: Technology signals, matched against the title and the structured skill
#: lists (never the description alone — a technology mention in prose is not
#: a profession). Deliberately weak per hit; two or three hits or a title
#: phrase are needed to carry a classification.
_TECH_SIGNALS = _compile(
    (
        ("react", "web_development", 1.5),
        ("next.js", "web_development", 1.5),
        ("vue", "web_development", 1.5),
        ("angular", "web_development", 1.5),
        ("svelte", "web_development", 1.5),
        ("tailwind", "web_development", 1.5),
        ("css", "web_development", 1.0),
        ("html", "web_development", 1.0),
        ("shopify", "web_development", 1.5),
        ("wordpress", "web_development", 1.5),
        ("php", "web_development", 1.0),
        ("node", "web_development", 1.0),
        ("graphql", "web_development", 1.0),
        ("django", "software_engineering", 1.5),
        ("flask", "software_engineering", 1.5),
        ("spring", "software_engineering", 1.5),
        ("rails", "software_engineering", 1.5),
        (".net", "software_engineering", 1.5),
        ("c#", "software_engineering", 1.5),
        ("java", "software_engineering", 1.0),
        ("golang", "software_engineering", 1.5),
        ("rust", "software_engineering", 1.0),
        ("kubernetes", "devops_cloud", 1.5),
        ("terraform", "devops_cloud", 1.5),
        ("ansible", "devops_cloud", 1.5),
        ("jenkins", "devops_cloud", 1.5),
        ("docker", "devops_cloud", 1.0),
        ("aws", "devops_cloud", 1.0),
        ("azure", "devops_cloud", 1.0),
        ("gcp", "devops_cloud", 1.0),
        ("swift", "mobile_development", 1.5),
        ("kotlin", "mobile_development", 1.5),
        ("android", "mobile_development", 1.5),
        ("react native", "mobile_development", 1.5),
        ("tableau", "data_analytics", 1.5),
        ("power bi", "data_analytics", 1.5),
        ("looker", "data_analytics", 1.5),
        ("excel", "data_analytics", 1.0),
        ("sql", "data_analytics", 0.75),
        ("sql", "data_engineering", 0.75),
        ("pytorch", "data_science_ml", 1.5),
        ("tensorflow", "data_science_ml", 1.5),
        ("scikit", "data_science_ml", 1.5),
        ("mlflow", "data_science_ml", 1.0),
        ("llm", "data_science_ml", 1.5),
        ("transformer", "data_science_ml", 1.0),
        ("pandas", "data_science_ml", 1.0),
        ("spark", "data_engineering", 1.5),
        ("airflow", "data_engineering", 1.5),
        ("dbt", "data_engineering", 1.5),
        ("snowflake", "data_engineering", 1.5),
        ("verilog", "hardware_physical_design", 1.5),
        ("verilog", "embedded_firmware", 1.0),
        ("vhdl", "hardware_physical_design", 1.5),
        ("cadence", "hardware_physical_design", 1.5),
        ("synopsys", "hardware_physical_design", 1.5),
        ("netlist", "hardware_physical_design", 1.5),
        ("microcontroller", "embedded_firmware", 1.5),
        ("rtos", "embedded_firmware", 1.5),
        ("fpga", "embedded_firmware", 1.5),
        ("osi", "security", 1.0),
        ("siem", "security", 1.5),
        ("iam", "security", 1.0),
        ("selenium", "qa_testing", 1.5),
        ("cypress", "qa_testing", 1.5),
        ("playwright", "qa_testing", 1.0),
        ("appium", "qa_testing", 1.0),
        ("figma", "design_ux", 1.5),
        ("sketch", "design_ux", 1.0),
        ("salesforce", "sales", 1.5),
        ("hubspot", "sales", 1.5),
        ("python", "software_engineering", 0.5),
        ("python", "data_science_ml", 0.5),
        ("python", "data_analytics", 0.5),
        ("javascript", "web_development", 1.0),
        ("typescript", "web_development", 1.0),
        ("git", "software_engineering", 0.25),
    )
)

#: Responsibility phrases from the description — what the work actually is.
#: Weight 2 each; a family's description-tier contribution is capped so one
#: keyword-stuffed paragraph cannot classify a listing by itself.
_RESPONSIBILITY_SIGNALS = _compile(
    (
        ("responsive web applications", "web_development", 2),
        ("single page applications", "web_development", 2),
        ("front-end development", "web_development", 2),
        ("cross-browser", "web_development", 2),
        ("web applications", "web_development", 1.5),
        ("distributed systems", "software_engineering", 2),
        ("microservices", "software_engineering", 2),
        ("api design", "software_engineering", 1.5),
        ("scalable backend", "software_engineering", 2),
        ("timing closure", "hardware_physical_design", 2.5),
        ("tape-out", "hardware_physical_design", 2.5),
        ("place and route", "hardware_physical_design", 2.5),
        ("physical verification", "hardware_physical_design", 2.5),
        ("logic synthesis", "hardware_physical_design", 2.5),
        ("power integrity", "hardware_physical_design", 2.5),
        ("semiconductor", "hardware_physical_design", 2),
        ("silicon", "hardware_physical_design", 2),
        ("hardware", "hardware_physical_design", 1),
        ("rtl design", "hardware_physical_design", 2.5),
        ("chip", "hardware_physical_design", 1),
        ("bare metal", "embedded_firmware", 2),
        ("device drivers", "embedded_firmware", 2),
        ("embedded systems", "embedded_firmware", 2),
        ("firmware development", "embedded_firmware", 2),
        ("dashboards", "data_analytics", 1.5),
        ("data visualization", "data_analytics", 2),
        ("reporting", "data_analytics", 1.0),
        ("business metrics", "data_analytics", 1.5),
        ("model training", "data_science_ml", 2),
        ("machine learning models", "data_science_ml", 2),
        ("fine-tune", "data_science_ml", 1.5),
        ("inference pipeline", "data_science_ml", 1.5),
        ("data pipelines", "data_engineering", 2),
        ("data warehouse", "data_engineering", 2),
        ("etl pipelines", "data_engineering", 2),
        ("infrastructure as code", "devops_cloud", 2),
        ("ci/cd pipelines", "devops_cloud", 2),
        ("on-call", "devops_cloud", 1.0),
        ("kubernetes cluster", "devops_cloud", 2),
        ("threat model", "security", 2),
        ("vulnerability management", "security", 2),
        ("penetration testing", "security", 2),
        ("security reviews", "security", 1.5),
        ("incident response", "security", 1.5),
        ("test automation", "qa_testing", 2),
        ("test plans", "qa_testing", 1.5),
        ("quality assurance", "qa_testing", 1.5),
        ("user research", "design_ux", 2),
        ("wireframes", "design_ux", 2),
        ("design system", "design_ux", 1.5),
        ("usability", "design_ux", 1.5),
        ("product roadmap", "product_management", 2.5),
        ("product requirements", "product_management", 2),
        ("backlog", "product_management", 1.5),
        ("go-to-market", "product_management", 1.5),
        ("sales quota", "sales", 2.5),
        ("prospecting", "sales", 2),
        ("pipeline generation", "sales", 2),
        ("revenue targets", "sales", 2),
        ("campaigns", "marketing", 1.5),
        ("seo strategy", "marketing", 2),
        ("content strategy", "marketing", 2),
        ("social media", "marketing", 1.5),
        ("customer inquiries", "customer_support", 2),
        ("support tickets", "customer_support", 2),
        ("customer satisfaction", "customer_support", 1.5),
        ("supply chain", "operations_program", 2),
        ("logistics", "operations_program", 1.5),
        ("capacity planning", "operations_program", 2),
        ("vendor management", "operations_program", 1.5),
        ("process improvement", "operations_program", 1.0),
        ("financial reporting", "finance_legal_compliance", 2),
        ("budgeting", "finance_legal_compliance", 1.5),
        ("forecasting", "finance_legal_compliance", 1.5),
        ("regulatory", "finance_legal_compliance", 1.5),
        ("sanctions", "finance_legal_compliance", 2),
        ("investigations", "finance_legal_compliance", 2),
        ("recruiting", "people_hr", 2),
        ("talent acquisition", "people_hr", 2),
        ("onboarding", "people_hr", 1.0),
        ("literature review", "research", 2),
        ("published research", "research", 2),
    )
)

#: The title tokens that mean "manages people", not "does the craft".
_MANAGER_TITLE_RE = re.compile(
    r"\b(manager|director|head of|vice president|vp|chief|c[hie]f officer|president)\b"
)

#: The top score a family's description tier may contribute on its own.
_DESCRIPTION_TIER_CAP = 4.0

#: The minimum score for a classification at all.
_MIN_CLASSIFICATION_SCORE = 2.0

#: Below this top-two confidence share the classification is *ambiguous* —
#: the top family is not at least ~1.4× the second reading.
_AMBIGUOUS_BELOW = 0.70


class RoleClassification(BaseModel):
    """What kind of work a listing describes, and how sure the classifier is.

    ``family`` is ``None`` when nothing recognisable fired — that is
    *unknown*, which the engine reports as a missing requirement, never as a
    low score.
    """

    family: str | None = None
    second_family: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    track: str = "unknown"  # "ic" | "manager" | "unknown"
    ambiguous: bool = False
    evidence: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return FAMILY_LABELS.get(self.family or "", self.family or "unknown")


class CandidateTargets(BaseModel):
    """The roles the candidate wants, and where the list came from.

    ``source``: ``user`` (confirmed targets), ``inferred`` (labelled
    fallback), ``cleared`` (the user explicitly emptied the field — nothing
    is re-inferred), ``none`` (nothing to go on).
    """

    families: list[str] = Field(default_factory=list)
    source: str = "none"
    raw: list[str] = Field(default_factory=list)
    track: str = "unknown"


class RoleRelevance(BaseModel):
    """One candidate×listing role comparison, ready for the engine."""

    value: float = Field(0.0, ge=0.0, le=100.0)
    band: float = 0.0
    family: str | None = None
    second_family: str | None = None
    confidence: float = 0.0
    ambiguous: bool = False
    track: str = "unknown"
    targets: list[str] = Field(default_factory=list)
    target_source: str = "none"
    evidence: list[str] = Field(default_factory=list)
    capped: bool = False
    reason: str = ""


def _family_scores(
    *,
    title: str,
    skills: str,
    description: str,
) -> dict[str, float]:
    """Score every family over the three evidence tiers."""
    scores: dict[str, float] = {}
    title_norm = _normalize(title)
    skills_norm = _normalize(skills)
    description_norm = _normalize(description)

    def add(family: str, weight: float) -> None:
        scores[family] = scores.get(family, 0.0) + weight

    for pattern, family, weight in _TITLE_SIGNALS:
        if title_norm and pattern.search(title_norm):
            add(family, weight)
    tech_caps: dict[str, float] = {}
    for pattern, family, weight in _TECH_SIGNALS:
        if (pattern.search(title_norm) or pattern.search(skills_norm)) and (
            tech_caps.get(family, 0.0) < 4.5
        ):
            add(family, weight)
            tech_caps[family] = tech_caps.get(family, 0.0) + weight
    desc_caps: dict[str, float] = {}
    for pattern, family, weight in _RESPONSIBILITY_SIGNALS:
        if (
            description_norm
            and pattern.search(description_norm)
            and desc_caps.get(family, 0.0) < _DESCRIPTION_TIER_CAP
        ):
            add(family, weight)
            desc_caps[family] = desc_caps.get(family, 0.0) + weight
    return scores


def _top_two(scores: dict[str, float]) -> tuple[tuple[str, float] | None, tuple[str, float] | None]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    first = ordered[0] if ordered else None
    second = ordered[1] if len(ordered) > 1 else None
    return first, second


def _evidence(
    title: str, skills: str, description: str, families: set[str], limit: int = 5
) -> list[str]:
    """The strongest matched phrases for the chosen families (for display)."""
    found: list[tuple[float, str]] = []
    title_norm = _normalize(title)
    skills_norm = _normalize(skills)
    description_norm = _normalize(description)
    for pattern, family, weight in _TITLE_SIGNALS:
        if family in families and pattern.search(title_norm):
            found.append((weight, pattern.pattern))
    for pattern, family, weight in _RESPONSIBILITY_SIGNALS:
        if family in families and description_norm and pattern.search(description_norm):
            found.append((weight, pattern.pattern))
    for pattern, family, weight in _TECH_SIGNALS:
        if family in families and (pattern.search(skills_norm) or pattern.search(title_norm)):
            found.append((weight, pattern.pattern))
    found.sort(key=lambda item: -item[0])
    seen: list[str] = []
    for _weight, pattern in found:
        phrase = pattern.strip(r"\b").replace("\\", "")
        if phrase not in seen:
            seen.append(phrase)
        if len(seen) >= limit:
            break
    return seen


def classify_job_role(job: JobListing) -> RoleClassification:
    """Classify one listing into a role family, deterministically."""
    title = job.title or ""
    skills = " ".join([*job.required_skills, *job.preferred_skills])
    description = job.description or ""
    scores = _family_scores(title=title, skills=skills, description=description)
    first, second = _top_two(scores)
    track = "manager" if _MANAGER_TITLE_RE.search(_normalize(title)) else "unknown"
    if first is None or first[1] < _MIN_CLASSIFICATION_SCORE:
        return RoleClassification(track=track, evidence=[])
    top_score = first[1]
    confidence = 1.0 if second is None else top_score / (top_score + second[1])
    families = {first[0]} | ({second[0]} if second else set())
    return RoleClassification(
        family=first[0],
        second_family=second[0] if second else None,
        confidence=confidence,
        track=track,
        ambiguous=confidence < _AMBIGUOUS_BELOW,
        evidence=_evidence(title, skills, description, families),
    )


def _classify_target_term(term: str) -> str | None:
    """One free-text target ("Senior Web Developer") to a family, or None."""
    text = _normalize(term)
    if not text.strip():
        return None
    scores: dict[str, float] = {}
    for pattern, family, weight in _TITLE_SIGNALS:
        if pattern.search(text):
            scores[family] = scores.get(family, 0.0) + weight
    for pattern, family, weight in _TECH_SIGNALS:
        if pattern.search(text):
            scores[family] = scores.get(family, 0.0) + weight
    first, _second = _top_two(scores)
    if first is None or first[1] < _MIN_CLASSIFICATION_SCORE:
        return None
    return first[0]


def resolve_candidate_targets(profile: CandidateProfile) -> CandidateTargets:
    """The candidate's target families: confirmed first, inference labelled.

    Priority (never mixed, so the provenance is honest):

    1. confirmed ``preferences.target_roles`` — authoritative, used as given;
    2. a *cleared* confirmed field (empty list) — nothing is re-inferred;
    3. the confirmed ``current_title``;
    4. the résumé headline;
    5. the three most recent experience titles.
    """
    app = getattr(profile, "application_profile", None)
    prefs = getattr(app, "preferences", None) if app is not None else None
    confirmed = set(getattr(app, "confirmed_fields", []) or []) if app is not None else set()
    targets = list(getattr(prefs, "target_roles", []) or []) if prefs is not None else []

    if "preferences.target_roles" in confirmed:
        if not targets:
            return CandidateTargets(source="cleared")
        families: list[str] = []
        for term in targets:
            family = _classify_target_term(term)
            if family and family not in families:
                families.append(family)
        track = "manager" if any(_MANAGER_TITLE_RE.search(_normalize(t)) for t in targets) else "ic"
        return CandidateTargets(families=families, source="user", raw=targets, track=track)

    raw: list[str] = []
    current_title = getattr(getattr(app, "professional", None), "current_title", None)
    if current_title:
        raw = [current_title]
    elif profile.personal_information.title:
        raw = [profile.personal_information.title]
    else:
        recent = [entry.title for entry in profile.experience if entry.title][-3:]
        raw = list(reversed(recent))

    families = []
    for term in raw:
        family = _classify_target_term(term)
        if family and family not in families:
            families.append(family)
    track = (
        "manager"
        if any(_MANAGER_TITLE_RE.search(_normalize(t)) for t in raw)
        else ("ic" if families else "unknown")
    )
    if not families:
        return CandidateTargets(source="none", raw=raw)
    return CandidateTargets(families=families, source="inferred", raw=raw, track=track)


def role_relevance(profile: CandidateProfile, job: JobListing) -> RoleRelevance:
    """Compare the candidate's target roles with the listing's role."""
    classification = classify_job_role(job)
    targets = resolve_candidate_targets(profile)

    if targets.source == "none":
        return RoleRelevance(
            targets=targets.raw,
            target_source="none",
            reason="the candidate has no target roles; set them to enable role matching",
        )
    if targets.source == "cleared":
        return RoleRelevance(
            target_source="cleared",
            reason="the candidate cleared their target roles; none are used",
        )
    if not targets.families:
        # Stated targets that map to no known family are treated like no
        # targets at all — a uniform zero, never a silent guess.
        return RoleRelevance(
            targets=targets.raw,
            target_source="none",
            reason="the stated target roles are not recognisable job families",
        )
    if classification.family is None:
        return RoleRelevance(
            targets=targets.raw,
            target_source=targets.source,
            track=classification.track,
            reason="the listing's role could not be classified from its title, work or technologies",
        )

    def compat_for(family: str) -> float:
        return max(compatibility(target_family, family) for target_family in targets.families)

    top_band = compat_for(classification.family)
    if classification.ambiguous and classification.second_family is not None:
        # An ambiguous listing cannot ride its best reading: the score is the
        # expected compatibility over the two readings, weighted by how sure
        # the classifier is of each.
        second_band = compat_for(classification.second_family)
        value = top_band * classification.confidence + second_band * (
            1.0 - classification.confidence
        )
    else:
        value = top_band

    if classification.track == "manager" and targets.track != "manager":
        value *= MANAGER_TRACK_FACTOR

    value = max(0.0, min(100.0, value))
    reason = ""
    if targets.source == "inferred":
        reason = (
            f"target roles inferred from {targets.raw[0]!r} "
            "(set your target roles to make this explicit)"
        )
    capped = value <= UNRELATED_ROLE_MAX
    if capped:
        mismatch = (
            f"the listing is {band_label(value)} to the candidate's targets "
            f"(classified: {FAMILY_LABELS.get(classification.family, classification.family)}); "
            f"the score is capped"
        )
        reason = f"{mismatch}; {reason}" if reason else mismatch
    elif classification.ambiguous:
        second_label = FAMILY_LABELS.get(
            classification.second_family or "", classification.second_family or "unknown"
        )
        top_label = FAMILY_LABELS.get(classification.family, classification.family)
        ambiguous_note = f"the listing's role is ambiguous (between {top_label} and {second_label})"
        reason = f"{ambiguous_note}; {reason}" if reason else ambiguous_note
    return RoleRelevance(
        value=value,
        band=top_band,
        family=classification.family,
        second_family=classification.second_family,
        confidence=classification.confidence,
        ambiguous=classification.ambiguous,
        track=classification.track,
        targets=targets.raw,
        target_source=targets.source,
        evidence=classification.evidence,
        capped=capped,
        reason=reason,
    )
