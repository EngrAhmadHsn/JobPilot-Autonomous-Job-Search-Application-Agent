# Cold Search Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the first search after a server restart stop paying a 52–65 s corpus rebuild, and fix the two defects that rebuild exposes.

**Architecture:** Three independent fixes. The miner stops discarding experience bars that state a generic domain rather than a technology. A `required_years_mined` marker distinguishes "never mined" from "mined, nothing stated", so a legitimately empty bar is mined once instead of on every rebuild. A synchronous startup warm builds the artifacts before the server accepts requests, moving the once-per-process rebuild off the request path.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, Pydantic v2, pytest, FastAPI lifespan.

**Spec:** `docs/implementation/24-search-performance.md` §11 (WS-28)

## Global Constraints

- **No score changes except where the spec says so.** Task 1 deliberately changes 1,235 listings' experience bars (§11.3). Every other task must leave `overall_score` bit-identical for every listing; a task that changes it is a defect.
- **`content_version_for` must keep hashing exactly the fields the artifacts derive from** (`src/db/jobs.py`). Task 2 adds no artifact field, so it must not change the digest.
- **Migrations are reversible.** Every `op.add_column` needs a working `downgrade`.
- **The suite is run with** `cmd.exe /c "env\Scripts\python.exe -m pytest ..."`; `pytest` is not on PATH.
- **Lint gate:** `env/Scripts/python.exe -m ruff check src tests scripts` must be clean.
- **A test that never failed proves nothing.** Each task's test is written and run **before** its implementation, and the plan records the expected failure message.

## Review Focus

Inputs and conditions the spec implies but no task's happy-path test exercises. Each is pinned by the task named.

1. **A description with a bar and a *real* technology** ("3 years with Python") must still be treated as technology-specific, not as a total bar. Task 1.
2. **A listing with an empty description** (not NULL — empty string) must be mineable and must not crash the backfill. Task 1.
3. **A stored value that is exactly `0`** must be preserved, not treated as falsy-and-unset. Task 2.
4. **A database written before this migration** (every `required_years` column value NULL) must read as "never mined", not as "mined, nothing stated". Task 2.
5. **A corpus whose rebuild fails at startup** must not prevent the server from starting. Task 3.

---

### Task 1: The miner keeps bars that name a generic domain

**Files:**
- Modify: `src/matching/experience.py:145-162` (`_extract_required_years`)
- Test: `tests/test_ws28_experience_bars.py` (create)

**Interfaces:**
- Consumes: `_TECH_CONTEXT_RE`, `_years_in_sentence`, `MAX_REQUIRED_YEARS` from `src/matching/experience.py` (all exist).
- Produces: `_GENERIC_DOMAIN_NOUNS: frozenset[str]` in `src/matching/experience.py`; the unchanged public signature `required_years(job: JobListing) -> float | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ws28_experience_bars.py`:

```python
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
    """`experience_requirements` is searched first and is still honoured."""
    assert (
        required_years(
            _listing(
                experience_requirements="5+ years required",
                description="Unrelated prose about the team.",
            )
        )
        == 5.0
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws28_experience_bars.py -q"`

Expected: 6 failures in `test_a_domain_bar_is_a_total_bar`, all `assert None == 7.0` (or the case's value); the technology and empty-description cases pass already.

- [ ] **Step 3: Add the generic-domain set and use it**

In `src/matching/experience.py`, above `_TECH_CONTEXT_RE`:

```python
#: Nouns that describe a *domain* a candidate works in, not a technology they
#: operate. A bar stated against one of these is the total bar: "7+ years of
#: sales experience" asks for seven years of being a salesperson, while
#: "3 years with Python" is a bar on one tool.
#:
#: WS-28. The technology rule used to fire on any noun, so it swallowed these
#: and reported "the listing states no bar" for 1,145 listings that plainly
#: state one (measured on the 8,558-listing corpus).
_GENERIC_DOMAIN_NOUNS = frozenset(
    {
        "a", "an", "the", "any", "this", "that",
        "experience", "work", "working",
        "sales", "support", "software", "engineering", "operations",
        "client", "clients", "customer", "customers", "account", "accounts",
        "product", "products", "project", "projects", "program", "programs",
        "people", "team", "teams", "management", "leadership",
        "industry", "professional", "related", "relevant", "similar", "prior",
        "full", "general", "business", "technical", "commercial",
        "solution", "solutions", "service", "services", "field",
    }
)
```

Then in `_extract_required_years`, replace the technology check:

```python
        # Skip a technology-specific bar: it is not the total requirement.
        # A domain noun is not a technology — see _GENERIC_DOMAIN_NOUNS.
        tech_bar = _TECH_CONTEXT_RE.search(sentence)
        if tech_bar:
            noun = tech_bar.group("tech").strip().casefold()
            if noun not in _GENERIC_DOMAIN_NOUNS:
                continue
        general.append(years)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws28_experience_bars.py -q"`

Expected: 12 passed.

- [ ] **Step 5: Run the existing experience and matching suites**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws20_experience.py tests/test_matching.py tests/test_ws23_corpus.py -q"`

Expected: all pass except `test_ws23_corpus.py::test_the_remotive_filter_is_client_side` if the documented DNS flake fires; note it and re-run that one test to confirm.

- [ ] **Step 6: Commit**

```bash
git add src/matching/experience.py tests/test_ws28_experience_bars.py
git commit -m "fix: a bar stated against a domain is the total bar, not a technology bar (ws-28)"
```

---

### Task 2: A mined-and-empty bar stops being re-mined

**Files:**
- Modify: `src/db/jobs.py` (add `required_years_mined`; set it in `merge_jobs`)
- Modify: `src/matching/corpus_cache.py:210-220` (read the marker)
- Create: `migrations/versions/<rev>_ws28_required_years_mined.py`
- Modify: `tests/test_migrations.py` (add the column to `JOBS_COLUMNS`)
- Test: `tests/test_ws28_required_years_marker.py` (create)

**Interfaces:**
- Consumes: `_mined_required_years(listing) -> float | None` (`src/db/jobs.py`), `required_years(job)` (Task 1's corrected miner).
- Produces: `JobDB.required_years_mined: Mapped[bool]`; `merge_jobs` sets it `True` for every row it writes.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ws28_required_years_marker.py`:

```python
"""WS-28 · NULL cannot mean two things.

`jobs.required_years` is NULL both for a row written before WS-23b and for a
row that was mined and states no bar. The read path re-mines both, which is
20.6 s of every cold start. A separate marker says which is which.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


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


def test_a_written_row_is_marked_mined(factory):
    """`merge_jobs` is the only writer, so it always sets the marker."""
    from src.db.jobs import JobDB, merge_jobs

    with factory() as session:
        merge_jobs(session, [_listing()])
        session.commit()
    with factory() as session:
        assert session.get(JobDB, "test:1").required_years_mined is True


def test_a_mined_row_with_no_bar_keeps_its_null_value(factory):
    """The marker is the record of the attempt; the value stays honest."""
    from src.db.jobs import JobDB, merge_jobs

    with factory() as session:
        merge_jobs(session, [_listing(description="No numbers here.")])
        session.commit()
    with factory() as session:
        row = session.get(JobDB, "test:1")
        assert row.required_years is None
        assert row.required_years_mined is True


def test_a_zero_bar_is_preserved(factory):
    """`0` is a real bar (an intern listing), not 'nothing stated'."""
    from src.db.jobs import JobDB, merge_jobs

    with factory() as session:
        merge_jobs(session, [_listing(description="0 years of experience required.")])
        session.commit()
    with factory() as session:
        row = session.get(JobDB, "test:1")
        assert row.required_years == 0.0
        assert row.required_years_mined is True


def test_an_unmarked_row_is_still_mined(factory):
    """A database written before this migration must read as 'never mined'."""
    from src.db.jobs import JobDB
    from src.matching.corpus_cache import get_corpus_artifacts

    with factory() as session:
        session.add(
            JobDB(
                id="legacy:1",
                source="legacy",
                source_job_id="1",
                title="Engineer",
                company="Acme",
                description="Minimum 6 years of engineering experience.",
                required_years=None,
                required_years_mined=False,
            )
        )
        session.commit()

    artifacts = get_corpus_artifacts(session_factory=factory)
    assert artifacts.required_years["legacy:1"] == 6.0


def test_a_marked_row_states_no_bar_and_is_not_mined(factory):
    """The 20.6 s: a marked row must never reach the miner."""
    from src.db.jobs import JobDB
    from src.matching import corpus_cache

    with factory() as session:
        # The description *does* state a bar; the marker says it was already
        # decided. If the read path re-mines, it will return 6.0 and this
        # assertion catches it.
        session.add(
            JobDB(
                id="mined:1",
                source="mined",
                source_job_id="1",
                title="Engineer",
                company="Acme",
                description="Minimum 6 years of engineering experience.",
                required_years=None,
                required_years_mined=True,
            )
        )
        session.commit()

    corpus_cache.clear_corpus_cache()
    artifacts = corpus_cache.get_corpus_artifacts(session_factory=factory)
    assert artifacts.required_years["mined:1"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws28_required_years_marker.py -q"`

Expected: `AttributeError: type object 'JobDB' has no attribute 'required_years_mined'` in the first four tests; the last test fails on the same attribute.

- [ ] **Step 3: Add the column, set it in the writer, read it in the cache**

In `src/db/jobs.py`, after `required_years`:

```python
    #: Whether ``required_years`` has been decided for this row (WS-28).
    #:
    #: ``required_years`` is NULL in two different situations: the row was
    #: written before WS-23b (so nothing was ever mined), or it was mined and
    #: the listing states no bar. The read path used to treat both as
    #: "never mined" and re-mine them, which cost 20.6 s of every cold start
    #: on the 8,558-listing corpus. This marker makes the two distinguishable
    #: so a decided row is decided once.
    #:
    #: Default false because that is the truth for every existing row: they
    #: were written before the marker existed, and nothing recorded a decision.
    required_years_mined: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
```

In `merge_jobs`, add beside `required_years=mined_years`:

```python
            required_years_mined=True,
```

In `src/matching/corpus_cache.py`, replace the `required_years` comprehension:

```python
        # WS-28: a row whose bar has been decided is not re-mined — including
        # one whose correct answer is "no bar". A row from before the marker
        # (``required_years_mined`` false) is still mined, so an un-migrated
        # corpus scores correctly.
        required_years={
            job.id: (
                stored_years.get(job.id)
                if mined_flags.get(job.id)
                else required_years(job)
            )
            for job in jobs
        },
```

and beside `stored_years`:

```python
    mined_flags: dict[str, bool] = {row.id: bool(row.required_years_mined) for row in rows}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws28_required_years_marker.py -q"`

Expected: 5 passed.

- [ ] **Step 5: Write the migration**

Run: `cmd.exe /c "env\Scripts\python.exe -m alembic revision -m 'ws28 required years mined'"`, then write it:

```python
def upgrade() -> None:
    """Add the marker that distinguishes 'never mined' from 'no bar'."""
    op.add_column(
        "jobs",
        sa.Column(
            "required_years_mined",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Rows that already carry a value have obviously been decided.
    op.execute("UPDATE jobs SET required_years_mined = true WHERE required_years IS NOT NULL")


def downgrade() -> None:
    """Drop the marker; ``required_years`` keeps its values."""
    op.drop_column("jobs", "required_years_mined")
```

- [ ] **Step 6: Run the migration tests**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_migrations.py -q"`

Expected: all pass. If `JOBS_COLUMNS` is asserted as an exact set, add `"required_years_mined"` to it.

- [ ] **Step 7: Commit**

```bash
git add src/db/jobs.py src/matching/corpus_cache.py migrations/versions tests/test_migrations.py tests/test_ws28_required_years_marker.py
git commit -m "fix: a bar that was decided is decided once, not once per rebuild (ws-28)"
```

---

### Task 3: The corpus artifacts are built before the server serves

**Files:**
- Modify: `src/main.py:43-70` (add the warm beside `_warm_local_embeddings`)
- Test: `tests/test_ws28_startup_warm.py` (create)

**Interfaces:**
- Consumes: `get_corpus_artifacts(*, session_factory=None, limit=None) -> CorpusArtifacts` (`src/matching/corpus_cache.py`), `get_limits().max_corpus_listings` (`src/security/limits.py`).
- Produces: `_warm_corpus_artifacts() -> None` in `src/main.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ws28_startup_warm.py`:

```python
"""WS-28 · The rebuild happens once per process, before the first request.

The artifacts cache is per-process, so the first search after a restart paid
the whole 52–65 s rebuild. Warming at startup moves that cost to a moment when
the server is not serving, and is strictly better than doing it during a
request.
"""

from __future__ import annotations

import pytest


def test_the_warm_builds_the_artifacts(monkeypatch):
    """The warm populates the same cache key a search will look up."""
    from src.matching import corpus_cache

    corpus_cache.clear_corpus_cache()
    called = {}

    def fake(*, session_factory=None, limit=None):
        called["limit"] = limit
        return "artifacts"

    monkeypatch.setattr(corpus_cache, "get_corpus_artifacts", fake)

    from src.main import _warm_corpus_artifacts

    _warm_corpus_artifacts()

    assert called["limit"] is not None, "the warm must honour the corpus cap"


def test_a_failed_warm_does_not_stop_startup(monkeypatch):
    """A corpus the warm cannot read must not prevent the server starting."""
    from src.matching import corpus_cache

    def boom(*, session_factory=None, limit=None):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(corpus_cache, "get_corpus_artifacts", boom)

    from src.main import _warm_corpus_artifacts

    _warm_corpus_artifacts()  # must not raise
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws28_startup_warm.py -q"`

Expected: `ImportError: cannot import name '_warm_corpus_artifacts' from 'src.main'`.

- [ ] **Step 3: Implement the warm and call it from the lifespan**

In `src/main.py`, after `_warm_local_embeddings`:

```python
def _warm_corpus_artifacts() -> None:
    """Build the corpus artifacts before the first search asks for them.

    WS-28. The artifacts cache is per-process, so the first search after a
    restart paid the whole rebuild — measured at 52–65 s on the
    8,558-listing corpus, while every later search hit the cache in 0.15 s.
    The rebuild has to happen exactly once either way; doing it here moves it
    to a moment when nothing is waiting for it.

    A failure is logged and swallowed. The warm is an optimisation: a corpus
    that cannot be read yet (a locked database, a migration not finished)
    must not stop the server, and the first search will simply pay the
    rebuild as it did before.
    """
    from src.matching.corpus_cache import get_corpus_artifacts
    from src.security.limits import get_limits

    try:
        artifacts = get_corpus_artifacts(limit=get_limits().max_corpus_listings)
        logger.info("Corpus artifacts warmed up (%d listings)", len(artifacts.jobs))
    except Exception:
        logger.exception("Corpus artifacts warm-up failed; the first search will rebuild them")
```

and in `lifespan`, beside the embedding warm:

```python
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    _warm_local_embeddings()
    _warm_corpus_artifacts()
    yield
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cmd.exe /c "env\Scripts\python.exe -m pytest tests/test_ws28_startup_warm.py -q"`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_ws28_startup_warm.py
git commit -m "perf: the corpus rebuild happens at startup, not inside the first search (ws-28)"
```

---

### Task 4: Measure the result and record it

**Files:**
- Modify: `docs/implementation/24-search-performance.md` (§11.7, a results section)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Re-mine the corpus**

Run: `cmd.exe /c "env\Scripts\python.exe -m alembic upgrade head"` then `cmd.exe /c "env\Scripts\python.exe scripts/backfill_required_years.py"`.

Expected: the script reports how many rows gained a value. The stored values are still the output of the *old* miner, so also run the re-mine described in §11.3 — the plan's Task 2 migration marks existing non-NULL rows as decided; a row whose value the corrected miner changes must be updated. Use:

```bash
cmd.exe /c "env\Scripts\python.exe - <<'PY'
# Re-mine every row the corrected miner disagrees with, and record the delta.
PY"
```

Record the count of changed values before and after.

- [ ] **Step 2: Measure a cold and a warm search**

Start the server, then time three searches. Expected: the first is ~3–5 s (the rebuild happened at startup), and the rest are ~3 s.

- [ ] **Step 3: Write §11.7 with the measured numbers**

Table: first-search-after-restart, second, third, and the corpus re-mine delta.

- [ ] **Step 4: Commit**

```bash
git add docs/implementation/24-search-performance.md
git commit -m "docs: what the cold-search fix measured (ws-28)"
```
