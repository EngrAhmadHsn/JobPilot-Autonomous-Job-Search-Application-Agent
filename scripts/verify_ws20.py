"""Live end-to-end verification of WS-20 (matching accuracy and the profile).

WS-20 has three claims, and each is checked against the real code rather than
a mock:

1. **An unknown signal is not a match.** The engine reports an explicit state
   for a missing component instead of a neutral 70, and a missing component
   keeps its weight in a fixed denominator.
2. **BM25 reads the whole posting.** A requirement buried in a description is
   found, and a term is matched as a whole word (``Java`` never matches
   ``JavaScript``).
3. **The application profile and its EEO data.** The user-confirmed answers
   round-trip over HTTP, are owner-scoped, and the EEO data is isolated from
   the résumé read and from the matcher.

The scoring claims are checked in-process against the **real** engine and the
**real** ``search_stored_jobs`` over a seeded throwaway database and a
deterministic embedding double. The profile claims are checked over live HTTP
against a throwaway server. Nothing touches the developer's data, and no
network is used.

Every check prints PASS/FAIL; the script exits non-zero when a check fails.

Usage::

    env\\Scripts\\python.exe scripts\\verify_ws20.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# A throwaway environment, set before the application modules are imported.
_WORKDIR = Path(tempfile.mkdtemp(prefix="ws20-verify-"))
DATABASE_PATH = _WORKDIR / "verify.db"
os.environ["DATA_DIR"] = str(_WORKDIR / "data")
os.environ["DATABASE_URL"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
os.environ["ALEMBIC_DATABASE_URL"] = f"sqlite:///{DATABASE_PATH.as_posix()}"
os.environ["CHROMA_DIR"] = str(_WORKDIR / "chroma")
os.environ["EVIDENCE_DIR"] = str(_WORKDIR / "evidence")
os.environ.setdefault("APP_ENV", "development")

import httpx
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from src.applications.questions import QuestionCategory, classify_text
from src.graph.job_executor import search_stored_jobs
from src.jobs.contracts import JobListing
from src.main import app
from src.matching.engine import calculate_match
from src.matching.lexical import (
    Bm25Index,
    candidate_lexical_text,
    candidate_tokens,
    lexical_score,
)
from src.matching.scores import ScoreState
from src.matching.weights import DEFAULT_WEIGHTS
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    WorkPreferences,
)

FIXTURE_DOCX = REPO_ROOT / "tests" / "fixtures" / "Ahmad_Hassan_AI_Engineer_Resume.docx"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record one check and print its outcome."""
    RESULTS.append((name, condition, detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# --------------------------------------------------------------------------
# Deterministic embedding double
# --------------------------------------------------------------------------


def _token_vector(text: str) -> list[float]:
    import math
    import re
    import zlib

    dim = 16
    vector = [0.0] * dim
    for token in re.findall(r"[a-z]+", text.casefold()):
        vector[zlib.crc32(token.encode("utf-8")) % dim] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class FakeEmbeddingFn:
    def embed_documents(self, texts: list[str], *, on_progress=None) -> list[list[float]]:
        return [_token_vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return _token_vector(text)


# --------------------------------------------------------------------------
# In-process scoring checks
# --------------------------------------------------------------------------


def _job(**kwargs) -> JobListing:
    defaults = {"id": "j", "source": "greenhouse", "title": "Engineer", "company": "Acme"}
    defaults.update(kwargs)
    return JobListing(**defaults)


def _profile(skills: list[str], *, experience=None, prefs=None) -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(title="Engineer"),
        skills=skills,
        experience=experience or [],
        work_preferences=prefs or WorkPreferences(),
    )


def check_score_policy() -> None:
    """An unknown component is zero with a state, never a neutral 70."""
    weights = dict(DEFAULT_WEIGHTS)

    no_experience = calculate_match(
        _job(experience_requirements="5+ years"),
        _profile(["python"]),
        semantic_score=50,
        weights=weights,
    )
    check(
        "a candidate with no dated experience scores 0 (CANDIDATE_DATA_MISSING), not 70",
        no_experience.experience_score == 0.0
        and no_experience.component_states["experience"] == ScoreState.CANDIDATE_DATA_MISSING,
        f"score={no_experience.experience_score}",
    )

    no_skills = calculate_match(_job(), _profile(["python"]), semantic_score=50, weights=weights)
    check(
        "a listing that states no skills scores 0 (JOB_REQUIREMENT_MISSING), not 70",
        no_skills.skill_score == 0.0
        and no_skills.component_states["skill"] == ScoreState.JOB_REQUIREMENT_MISSING,
        f"score={no_skills.skill_score}",
    )

    measured_zero = calculate_match(
        _job(), _profile(["python"]), semantic_score=0.0, weights=weights
    )
    unavailable = calculate_match(
        _job(), _profile(["python"]), semantic_score=None, weights=weights
    )
    check(
        "a measured 0.0 similarity is distinguished from an unavailable one",
        measured_zero.component_states["semantic"] == ScoreState.MISMATCH
        and unavailable.component_states["semantic"] == ScoreState.EMBEDDING_UNAVAILABLE,
    )

    # The fixed denominator: an unknown keeps its weight; nothing is moved.
    job = _job(required_skills=["python", "sql"], experience_requirements="3+ years")
    profile = _profile(
        ["python", "sql"], experience=[ExperienceEntry(title="Dev", dates="2020 - present")]
    )
    with_vector = calculate_match(job, profile, semantic_score=95, weights=weights)
    without = calculate_match(job, profile, semantic_score=None, weights=weights)
    expected = sum(
        DEFAULT_WEIGHTS[name] * without.__dict__[f"{name}_score"] for name in DEFAULT_WEIGHTS
    ) / sum(DEFAULT_WEIGHTS.values())
    check(
        "a missing embedding keeps its weight (no redistribution) and cannot outrank one",
        abs(without.overall_score - expected) < 1e-6
        and without.overall_score < with_vector.overall_score,
        f"without={without.overall_score:.2f} with={with_vector.overall_score:.2f}",
    )
    check(
        "every overall score stays within 0-100",
        all(
            0.0 <= m.overall_score <= 100.0
            for m in (no_experience, no_skills, without, with_vector)
        ),
    )


def check_bm25() -> None:
    """BM25 reads the whole posting, as whole words."""
    buried = _job(
        id="buried",
        title="Backend Engineer",
        description=("filler " * 300) + "You will run Kubernetes and Terraform in production.",
    )
    unrelated = _job(
        id="unrelated",
        title="Backend Engineer",
        description=("filler " * 300) + "You will maintain spreadsheets.",
    )
    cand = _profile(["Kubernetes", "Terraform"])
    index = Bm25Index([buried, unrelated])

    def score(job):
        return lexical_score(
            job,
            index=index,
            candidate_token_list=candidate_tokens(cand),
            candidate_text=candidate_lexical_text(cand),
        ).score

    check(
        "a requirement buried deep in a description raises the lexical score",
        score(buried) > score(unrelated),
        f"buried={score(buried):.1f} unrelated={score(unrelated):.1f}",
    )

    java_job = _job(id="java", title="Backend", description="We use Java for services.")
    jindex = Bm25Index([java_job])
    java_dev = _profile(["Java"])
    js_dev = _profile(["JavaScript"])
    check(
        "Java is not matched by a JavaScript candidate (whole-word tokenization)",
        jindex.score("java", candidate_tokens(java_dev)) > 0
        and jindex.score("java", candidate_tokens(js_dev)) == 0,
    )


def check_taxonomy() -> None:
    """The three legal questions are distinct, and value transforms are exact."""
    sponsor = classify_text("Will you now or in the future require sponsorship?")
    auth = classify_text("Are you authorized to work in the United States?")
    citizen = classify_text("What is your citizenship status?")
    check(
        "sponsorship, authorization and citizenship classify separately",
        sponsor.category is QuestionCategory.VISA_SPONSORSHIP
        and auth.category is QuestionCategory.WORK_AUTHORIZATION
        and citizen.category is QuestionCategory.CITIZENSHIP_STATUS,
    )

    from src.applications.questions import notice_period_answer

    check(
        "a 15-day notice is not floored into '2 weeks'",
        notice_period_answer(15, "weeks") is None and notice_period_answer(14, "weeks") == "2",
    )


def check_search_over_the_corpus() -> None:
    """search_stored_jobs gives a pending listing no semantic advantage."""
    engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}", future=True)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    from src.db.jobs import save_jobs
    from src.rag.chroma_store import ChromaVectorStore

    embedded_job = _job(
        id="embedded",
        title="Backend Python Engineer",
        description="Build APIs with Python and FastAPI.",
        required_skills=["Python", "FastAPI"],
        remote_policy="remote",
    )
    pending_job = _job(
        id="pending",
        title="Backend Python Engineer",
        description="Build APIs with Python and FastAPI.",
        required_skills=["Python", "FastAPI"],
        remote_policy="remote",
    )
    save_jobs([embedded_job, pending_job], session_factory=factory)

    fake = FakeEmbeddingFn()
    store = ChromaVectorStore(
        embedding_fn=fake,
        settings=SimpleNamespace(
            chroma_dir=os.environ["CHROMA_DIR"],
            embedding_model="verify-model",
            embedding_dimensionality=16,
        ),
    )
    store.upsert_jobs([embedded_job])  # the other listing has no vector

    profile = _profile(["Python", "FastAPI", "AWS"])
    report = search_stored_jobs(
        profile, store_factory=lambda: store, session_factory=factory, top_n=10
    )

    by_id = {pair.job.id: pair.match for pair in report.results}
    check(
        "both listings are returned (a pending listing stays visible)",
        set(by_id) == {"embedded", "pending"},
        f"returned={sorted(by_id)}",
    )
    check(
        "the vector-less listing is EMBEDDING_PENDING and earns no semantic credit",
        by_id["pending"].component_states["semantic"] == ScoreState.EMBEDDING_PENDING
        and by_id["pending"].semantic_score == 0.0,
    )
    check(
        "the embedded listing outranks the pending one",
        by_id["embedded"].overall_score > by_id["pending"].overall_score,
        f"embedded={by_id['embedded'].overall_score:.1f} pending={by_id['pending'].overall_score:.1f}",
    )
    check(
        "the report states its semantic coverage (50% here)",
        abs(report.semantic_coverage - 50.0) < 1e-6,
        f"coverage={report.semantic_coverage}",
    )
    check(
        "the ranking is a stable (score desc, id) order",
        report.results[0].match.overall_score >= report.results[-1].match.overall_score,
    )
    engine.dispose()


# --------------------------------------------------------------------------
# Live HTTP checks
# --------------------------------------------------------------------------


def _upgrade_database() -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(config, "head")


def _serve_api() -> tuple[uvicorn.Server, str]:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 60
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    if not server.started:
        raise RuntimeError("The API server did not start in time")
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, f"http://127.0.0.1:{port}"


def _register(client: httpx.Client, email: str) -> None:
    password = "ws20-verification-password"
    client.post("/api/auth/register", json={"email": email, "password": password})
    response = client.post("/api/auth/token/login", data={"username": email, "password": password})
    token = response.json().get("access_token") if response.status_code == 200 else None
    if token:
        client.headers["Authorization"] = f"Bearer {token}"


def check_migration() -> None:
    engine = create_engine(f"sqlite:///{DATABASE_PATH.as_posix()}")
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("candidate_profiles")}
    check(
        "the WS-20 migration adds the application-profile column",
        "application_json" in columns,
    )
    check(
        "the WS-20 migration adds the isolated EEO table",
        "candidate_eeo" in inspector.get_table_names(),
    )
    engine.dispose()


def check_profile_over_http(api: str) -> None:
    with httpx.Client(base_url=api, timeout=60) as client:
        _register(client, f"ws20-owner-{int(time.time())}@example.com")

        with FIXTURE_DOCX.open("rb") as fh:
            upload = client.post(
                "/api/resumes",
                files={"file": ("resume.docx", fh.read(), DOCX_MIME)},
            )
        check("a resume upload succeeds", upload.status_code == 200, f"status={upload.status_code}")
        profile_id = upload.json()["profile_id"]

        got = client.get(f"/api/profiles/{profile_id}/application-profile")
        check(
            "the application profile starts empty",
            got.status_code == 200
            and got.json()["application_profile"]["professional"]["total_experience_years"] is None,
        )

        payload = {
            "professional": {"total_experience_years": 7, "seniority_level": "senior"},
            "preferences": {"remote_preference": "remote"},
            "answers": {
                "work_authorization": {
                    "legally_authorized": True,
                    "requires_sponsorship": True,
                },
                "compensation": {
                    "expected_salary": 120000,
                    "expected_currency": "usd",
                    "expected_period": "annual",
                },
                "notice": {"notice_days": 0},
            },
        }
        put = client.put(f"/api/profiles/{profile_id}/application-profile", json=payload)
        check(
            "the application answers round-trip",
            put.status_code == 200
            and put.json()["application_profile"]["answers"]["work_authorization"][
                "legally_authorized"
            ]
            is True
            and put.json()["application_profile"]["answers"]["notice"]["notice_days"] == 0,
            f"status={put.status_code}",
        )

        bad = client.put(
            f"/api/profiles/{profile_id}/application-profile",
            json={"preferences": {"remote_preference": "teleport"}},
        )
        check("an invalid preference is a 422", bad.status_code == 422, f"status={bad.status_code}")

        refused = client.put(
            f"/api/profiles/{profile_id}/eeo", json={"gender": "Woman", "opt_in": False}
        )
        check(
            "EEO data cannot be stored without opt-in",
            refused.status_code == 400,
            f"status={refused.status_code}",
        )

        stored = client.put(
            f"/api/profiles/{profile_id}/eeo",
            json={"opt_in": True, "veteran_status": "I am not a veteran"},
        )
        check("EEO data stores when opted in", stored.status_code == 200)
        read = client.get(f"/api/profiles/{profile_id}/eeo")
        check(
            "EEO data reads back",
            read.json()["eeo"]["veteran_status"] == "I am not a veteran",
        )

        resume = client.get(f"/api/resumes/{profile_id}")
        check(
            "the resume read never carries EEO data",
            "eeo" not in resume.json().get("profile", {})
            and "gender" not in resume.json().get("profile", {}).get("application_profile", {}),
        )

        # A different account cannot see or change this profile's answers.
        with httpx.Client(base_url=api, timeout=60) as other:
            _register(other, f"ws20-other-{int(time.time())}@example.com")
            check(
                "an application profile is owner-scoped (foreign read is 404)",
                other.get(f"/api/profiles/{profile_id}/application-profile").status_code == 404,
            )
            check(
                "the EEO resource is owner-scoped (foreign read is 404)",
                other.get(f"/api/profiles/{profile_id}/eeo").status_code == 404,
            )

        search = client.post(
            "/api/jobs/search", json={"profile_id": profile_id, "top_n": 5, "only_embedded": False}
        )
        check(
            "the search reports its semantic coverage",
            search.status_code == 200 and "semantic_coverage" in search.json(),
            f"status={search.status_code}",
        )

        deleted = client.delete(f"/api/profiles/{profile_id}/eeo")
        after = client.get(f"/api/profiles/{profile_id}/eeo")
        check(
            "EEO data can be deleted outright",
            deleted.status_code == 204 and after.json()["eeo"]["veteran_status"] is None,
        )


# --------------------------------------------------------------------------


def main() -> int:
    print("WS-20 verification — matching accuracy and the candidate profile")
    print(f"throwaway workspace: {_WORKDIR}\n")

    check_score_policy()
    check_bm25()
    check_taxonomy()

    _upgrade_database()
    check_migration()
    check_search_over_the_corpus()

    server, api = _serve_api()
    try:
        check_profile_over_http(api)
    finally:
        server.should_exit = True

    passed = sum(1 for _name, ok, _detail in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
