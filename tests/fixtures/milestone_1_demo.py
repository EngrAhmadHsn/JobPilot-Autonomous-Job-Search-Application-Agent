"""Milestone 1 demonstration script (WS-04).

Demonstrates the first working milestone end-to-end through the real
pipeline:

    Resume -> CandidateProfile -> Search Jobs -> Normalize -> Deduplicate
    -> Persist -> Hybrid Match -> Top 10 -> Explanation

Offline mode (default) is fully deterministic: the search runs against a
fixture JobSource and a FakeEmbeddingFn-backed Chroma store in a temp dir, so
no network, no API key, no quota is involved.

    python tests/fixtures/milestone_1_demo.py           # offline (default)
    python tests/fixtures/milestone_1_demo.py --live    # real sources + embeddings

--live uses the production registry (Greenhouse/Lever/Remotive public APIs,
politely rate-limited) and the real gemini-embedding-2 vector store; it needs
LLM_API_KEY in .env and makes real network + API calls.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Runnable both as a script and as a module: put the repo root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.db.jobs
import src.db.matches
import src.db.profiles  # noqa: F401
from src.db.base import Base
from src.graph.job_executor import run_job_search
from src.resume.parser import parse_resume
from src.resume.profile import CandidateProfile

RESUME_PATH = Path(__file__).resolve().parent / "Ahmad_Hassan_AI_Engineer_Resume.docx"


def _print_report(profile: CandidateProfile, report, mode: str) -> None:
    print("=" * 72)
    print(f"MILESTONE 1 DEMONSTRATION ({mode})")
    print("=" * 72)

    print("\n[1] Parsed resume")
    print(
        f"    Candidate: {profile.personal_information.name} — {profile.personal_information.title}"
    )
    print(f"    Skills:    {', '.join(profile.skills[:10])}")

    print("\n[2] Pipeline stats")
    print(
        f"    found={report.stats.found}  dropped={report.stats.dropped}  "
        f"deduped={report.stats.deduped}  persisted={report.stats.persisted}"
    )
    if report.source_errors:
        print(f"    source errors (tolerated): {report.source_errors}")
    if report.degraded:
        print("    degraded mode: semantic scoring unavailable")

    print(f"\n[3] Ranked top {len(report.results)} (hybrid match, per-component explanations)")
    if not report.results:
        print("    (no results)")
        return
    for rank, pair in enumerate(report.results, start=1):
        job, match = pair.job, pair.match
        print(
            f"\n    #{rank:>2}  {match.overall_score:5.1f}/100  {job.title} @ {job.company} "
            f"[{job.source}]"
        )
        for chunk in _wrap(match.explanation, indent=10):
            print(chunk)


def _wrap(text: str, indent: int, width: int = 100) -> list[str]:
    import textwrap

    return textwrap.wrap(
        text, width=width, initial_indent=" " * indent, subsequent_indent=" " * indent
    )


def run_offline() -> int:
    profile = parse_resume(str(RESUME_PATH))

    from tests.fixtures.fake_embeddings import make_store
    from tests.fixtures.fake_source import FakeJobSource

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    # ignore_cleanup_errors: chromadb keeps segment files open on Windows,
    # so best-effort temp cleanup may fail after the run (harmless leftovers).
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as chroma_tmp:
        report = run_job_search(
            profile,
            sources={"fixture": FakeJobSource()},
            store_factory=lambda: make_store(Path(chroma_tmp) / "chroma"),
            session_factory=sessionmaker(autocommit=False, autoflush=False, bind=engine),
        )

    _print_report(profile, report, mode="offline fixture source + fake embeddings")
    engine.dispose()
    return 0 if report.results else 1


def run_live() -> int:
    if not _live_ready():
        print(
            "--live requires LLM_API_KEY in .env (real gemini-embedding-2 calls) "
            "and network access to the job boards.",
            file=sys.stderr,
        )
        return 2

    profile = parse_resume(str(RESUME_PATH))
    # Production path: real registry sources, real Chroma store, real SessionLocal.
    report = run_job_search(profile)
    _print_report(profile, report, mode="LIVE: real sources + gemini-embedding-2")
    return 0 if report.results else 1


def _live_ready() -> bool:
    from src.config.settings import get_settings

    return bool(get_settings().llm_api_key)


def main(argv: list[str]) -> int:
    if "--live" in argv:
        return run_live()
    return run_offline()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
