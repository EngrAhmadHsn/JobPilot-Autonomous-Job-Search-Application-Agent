"""WS-04 tests: job search + match API (src/api/routes/jobs.py).

The search endpoint runs against a dependency-overridden executor returning
fixture matches, so the HTTP layer is verified without network or
embeddings. The pipeline itself is covered by test_job_workflow.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.db.matches
import src.db.profiles  # noqa: F401
from src.config.settings import get_settings
from src.db.base import Base
from src.db.jobs import save_jobs
from src.db.session import get_db
from src.graph.job_executor import JobSearchReport, JobSearchStats
from src.graph.job_state import JobMatchPair
from src.main import app
from tests.fixtures.fake_source import FIXTURE_JOBS

FIXTURE_DOCX = Path(__file__).parent / "fixtures" / "Ahmad_Hassan_AI_Engineer_Resume.docx"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class RecordingExecutor:
    """Executor double returning a fixture report and recording its args."""

    def __init__(self, report: JobSearchReport) -> None:
        self._report = report
        self.calls: list[tuple] = []

    def __call__(self, profile, query, location, top_n):
        self.calls.append((profile.personal_information.name, query, location, top_n))
        return self._report


def _fixture_report(**overrides) -> JobSearchReport:
    from src.matching.engine import calculate_match
    from src.resume.profile import CandidateProfile, PersonalInformation

    profile = CandidateProfile(
        personal_information=PersonalInformation(name="Ahmad Hassan", title="AI Engineer"),
        skills=["Python", "FastAPI", "AWS"],
    )
    defaults: dict = {
        "results": [
            JobMatchPair(job=job, match=calculate_match(job, profile, semantic_score=70.0))
            for job in FIXTURE_JOBS[:2]
        ],
        "source_errors": {},
        "stats": JobSearchStats(found=4, dropped=0, deduped=2, persisted=2),
        "degraded": False,
    }
    defaults.update(overrides)
    return JobSearchReport(**defaults)


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """TestClient with a throwaway DB and upload dir."""
    engine = create_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(get_settings(), "resume_upload_dir", str(tmp_path / "uploads"))
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()
    app.dependency_overrides.pop(get_job_search_executor_dependency, None)


def get_job_search_executor_dependency():
    from src.api.routes.jobs import get_job_search_executor

    return get_job_search_executor


@pytest.fixture()
def profile_id(api: TestClient) -> str:
    """A profile uploaded through the real API (so it is persisted)."""
    with FIXTURE_DOCX.open("rb") as fh:
        response = api.post(
            "/api/resumes",
            files={"file": ("resume.docx", fh.read(), DOCX_MIME)},
        )
    assert response.status_code == 200
    return response.json()["profile_id"]


def test_search_with_overridden_executor(api: TestClient, profile_id: str) -> None:
    executor = RecordingExecutor(_fixture_report())
    from src.api.routes import jobs as jobs_route

    app.dependency_overrides[jobs_route.get_job_search_executor] = lambda: executor

    response = api.post(
        "/api/jobs/search",
        json={
            "profile_id": profile_id,
            "query": "python engineer",
            "location": "Remote",
            "top_n": 5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["profile_id"] == profile_id
    assert body["degraded"] is False
    assert body["source_errors"] == {}
    assert body["stats"]["deduped"] == 2
    assert len(body["results"]) == 2

    # The stored profile (not a fresh parse) reached the executor, with args.
    assert executor.calls == [("Ahmad Hassan", "python engineer", "Remote", 5)]

    first = body["results"][0]
    assert first["job"]["id"].startswith("fixture:")
    assert 0 <= first["match"]["overall_score"] <= 100
    assert first["match"]["explanation"]


def test_search_persists_match_rows(api: TestClient, profile_id: str) -> None:
    from src.api.routes import jobs as jobs_route

    app.dependency_overrides[jobs_route.get_job_search_executor] = lambda: RecordingExecutor(
        _fixture_report()
    )

    api.post("/api/jobs/search", json={"profile_id": profile_id})

    history = api.get(f"/api/profiles/{profile_id}/matches")
    assert history.status_code == 200
    matches = history.json()["matches"]
    assert len(matches) == 2
    assert {m["job_id"] for m in matches} == {job.id for job in FIXTURE_JOBS[:2]}
    assert all(m["scores"]["overall_score"] > 0 for m in matches)
    assert all(m["explanation"] for m in matches)
    assert all(m["created_at"] for m in matches)


def test_search_unknown_profile_404(api: TestClient) -> None:
    response = api.post("/api/jobs/search", json={"profile_id": "missing"})
    assert response.status_code == 404


def test_search_source_errors_pass_through(api: TestClient, profile_id: str) -> None:
    """A degraded report (source failures) is still HTTP 200 (plan §35)."""
    from src.api.routes import jobs as jobs_route

    report = _fixture_report(
        source_errors={"greenhouse": "RuntimeError: down"},
        degraded=True,
        results=[],
        stats=JobSearchStats(found=0, dropped=0, deduped=0, persisted=0),
    )
    app.dependency_overrides[jobs_route.get_job_search_executor] = lambda: RecordingExecutor(report)

    response = api.post("/api/jobs/search", json={"profile_id": profile_id})

    assert response.status_code == 200
    body = response.json()
    assert body["source_errors"] == {"greenhouse": "RuntimeError: down"}
    assert body["degraded"] is True
    assert body["results"] == []


def test_get_job_from_db(api: TestClient, tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}", future=True)
    save_jobs(FIXTURE_JOBS[:1], session_factory=sessionmaker(bind=engine))
    engine.dispose()

    job_id = FIXTURE_JOBS[0].id
    response = api.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    job = response.json()["job"]
    assert job["id"] == job_id
    assert job["title"] == FIXTURE_JOBS[0].title
    assert job["company"] == FIXTURE_JOBS[0].company


def test_get_unknown_job_404(api: TestClient) -> None:
    assert api.get("/api/jobs/greenhouse:nope").status_code == 404


def test_matches_history_unknown_profile_404(api: TestClient) -> None:
    assert api.get("/api/profiles/missing/matches").status_code == 404


def test_matches_history_empty_for_fresh_profile(api: TestClient, profile_id: str) -> None:
    response = api.get(f"/api/profiles/{profile_id}/matches")
    assert response.status_code == 200
    assert response.json()["matches"] == []


# ------------------------------------------------------------- FU-1 --------


class RecordingRefreshExecutor:
    """Refresh executor double returning a fixture refresh report."""

    def __init__(self, report) -> None:
        self._report = report
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self._report


def _fixture_refresh_report():
    from src.graph.job_executor import JobRefreshReport, JobRefreshStats

    return JobRefreshReport(
        stats=JobRefreshStats(
            found=12, dropped=1, deduped=10, persisted=10, embedded=9
        ),
        source_errors={"broken": "RuntimeError: down"},
        embedding_requests_planned=1,
        embedding_requests_used=1,
        quota_exhausted=False,
        degraded_embedding=False,
    )


def test_refresh_endpoint_returns_summary(api: TestClient) -> None:
    from src.api.routes import jobs as jobs_route

    executor = RecordingRefreshExecutor(_fixture_refresh_report())
    app.dependency_overrides[jobs_route.get_job_refresh_executor] = lambda: executor

    response = api.post("/api/jobs/refresh")

    app.dependency_overrides.pop(jobs_route.get_job_refresh_executor, None)
    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["persisted"] == 10
    assert body["stats"]["embedded"] == 9
    assert body["source_errors"] == {"broken": "RuntimeError: down"}
    assert body["embedding_requests_planned"] == 1
    assert body["quota_exhausted"] is False
    assert executor.calls == 1


def test_refresh_endpoint_quota_stop_passes_through(api: TestClient) -> None:
    from src.api.routes import jobs as jobs_route
    from src.graph.job_executor import JobRefreshReport, JobRefreshStats

    report = JobRefreshReport(
        stats=JobRefreshStats(found=5, dropped=0, deduped=5, persisted=5, embedded=0),
        embedding_requests_planned=3,
        embedding_requests_used=2,
        quota_exhausted=True,
    )
    app.dependency_overrides[jobs_route.get_job_refresh_executor] = (
        lambda: RecordingRefreshExecutor(report)
    )

    response = api.post("/api/jobs/refresh")

    app.dependency_overrides.pop(jobs_route.get_job_refresh_executor, None)
    assert response.status_code == 200  # a quota stop is a valid outcome
    assert response.json()["quota_exhausted"] is True


def test_search_defaults_to_store_only_executor(api: TestClient, tmp_path: Path, profile_id: str) -> None:
    """Without an override, /api/jobs/search must run the store-only path:
    persisted rows are matched, no board source is contacted."""
    from tests.fixtures.fake_embeddings import FakeEmbeddingFn, make_store

    engine = create_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    save_jobs(FIXTURE_JOBS, session_factory=factory)

    store = make_store(tmp_path / "chroma", FakeEmbeddingFn())
    store.upsert_jobs(FIXTURE_JOBS)

    import src.rag.chroma_store as chroma_module

    original = chroma_module.ChromaVectorStore
    monkey_target = lambda *args, **kwargs: store
    chroma_module.ChromaVectorStore = monkey_target
    try:
        response = api.post("/api/jobs/search", json={"profile_id": profile_id})
    finally:
        chroma_module.ChromaVectorStore = original
    engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["found"] == 0  # no sources contacted
    assert body["stats"]["stored"] == len(FIXTURE_JOBS)
    assert body["degraded"] is False
    assert len(body["results"]) == len(FIXTURE_JOBS)  # top_n clamps to corpus size
