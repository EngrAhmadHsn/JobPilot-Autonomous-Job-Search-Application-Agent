"""WS-02 tests: deterministic skill extraction (src/jobs/skills.py)."""

from __future__ import annotations

from src.jobs.skills import SKILL_LEXICON, extract_skills, split_required_preferred


def test_lexicon_shape():
    """Every canonical name must list itself among its aliases."""
    for canonical, aliases in SKILL_LEXICON.items():
        assert canonical in aliases, f"{canonical} missing from its own aliases"
        assert all(isinstance(alias, str) and alias for alias in aliases)


def test_extract_basic_and_order():
    text = "Requirements: Python, Kubernetes and PostgreSQL experience."
    assert extract_skills(text) == ["Python", "Kubernetes", "PostgreSQL"]


def test_extract_case_insensitive():
    assert extract_skills("we use fastapi and KUBERNETES daily") == ["FastAPI", "Kubernetes"]


def test_java_does_not_match_javascript():
    """Word boundaries: 'Java' must not fire inside 'JavaScript'."""
    assert extract_skills("Strong JavaScript and TypeScript skills") == ["JavaScript", "TypeScript"]
    assert extract_skills("Java developer") == ["Java"]


def test_aliases_canonicalize():
    assert extract_skills("k8s + postgres + js on the backend") == [
        "Kubernetes",
        "PostgreSQL",
        "JavaScript",
    ]


def test_go_and_c_do_not_false_positive_on_prose():
    """Deliberate lexicon omissions: bare 'Go', 'C', 'R' are excluded."""
    assert extract_skills("Go to market plan for the R&D team, level C") == []


def test_cplusplus_with_version_number():
    """Symbol aliases may be followed by digits: C++17, .NET 8."""
    assert "C++" in extract_skills("5+ years of C++17 in production")
    assert ".NET" in extract_skills("Experience with .NET 8 and ASP.NET")


def test_dotnet_does_not_match_aspnet():
    """'ASP.NET' is its own entry; '.NET' must not match inside it."""
    skills = extract_skills("ASP.NET developer")
    assert skills == ["ASP.NET"]


def test_no_fabrication_on_empty_text():
    assert extract_skills("") == []
    assert extract_skills(None) == []


def test_deduplication_and_first_occurrence_order():
    text = "Python first. Later Python appears again with Docker, then Python."
    assert extract_skills(text) == ["Python", "Docker"]


def test_split_required_preferred_with_section():
    jd = (
        "Senior Backend Engineer\n\n"
        "Requirements:\n"
        "- 5+ years with Python and FastAPI\n"
        "- Strong PostgreSQL and Redis experience\n\n"
        "Nice to have:\n"
        "- Rust or gRPC experience\n"
        "- Kubernetes certification is a plus\n\n"
        "Benefits: great team."
    )
    required, preferred = split_required_preferred(jd)
    assert required == ["Python", "FastAPI", "PostgreSQL", "Redis"]
    assert preferred == ["Rust", "gRPC", "Kubernetes"]


def test_split_skill_in_both_sections_is_required():
    jd = "Python role.\nPreferred: Python, Rust"
    required, preferred = split_required_preferred(jd)
    assert required == ["Python"]
    assert preferred == ["Rust"]


def test_split_without_preferred_section_all_required():
    required, preferred = split_required_preferred("Need Python and Docker.")
    assert required == ["Python", "Docker"]
    assert preferred == []


def test_split_empty():
    assert split_required_preferred("") == ([], [])
    assert split_required_preferred(None) == ([], [])


def test_split_prefers_line_start_headings_only():
    """A mid-sentence mention of 'preferred' must not split the text."""
    jd = "Python required. This is preferred by many teams."
    required, preferred = split_required_preferred(jd)
    assert required == ["Python"]
    assert preferred == []


def test_extraction_is_deterministic():
    text = "FastAPI, Python, Docker, Kubernetes, AWS"
    assert extract_skills(text) == extract_skills(text)
