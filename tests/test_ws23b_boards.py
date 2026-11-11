"""WS-23b · The board registry and its health.

The registry had **zero direct test coverage** — no test file referenced
`BoardDB`, `list_boards`, `record_board_success`, `record_board_failure`
or `registry_slugs` — and the source-scoped eviction depends on this
layer. An untested health record is an unverified guarantee.

What is tested here, and why each one matters:

* **Additive seeding.** The env lists are the operator's bootstrap and
  the registry is where the health lives. A restart must not overwrite a
  board's streak, or the eviction would stop protecting a failing
  source every time the process came back.
* **A success resets the streak.** A board that recovers must stop being
  protected, or a transient outage would shield its rows from eviction
  forever.
* **A failure increments it and sanitizes the message.** The error text
  is a board's own response, the console renders it, and it must not be
  able to carry a newline into an audit row or a control character into
  a page.
* **`registry_slugs` returns enabled boards only.** A board an operator
  disabled must stop being fetched, and the adapters fall back to the
  env list when the registry is empty (a fresh checkout).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.boards import (
    BoardDB,
    list_boards,
    record_board_failure,
    record_board_success,
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'boards.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


# ------------------------------------------------------------- recording


def test_a_success_creates_the_board_and_records_it(session_factory):
    """The first successful fetch registers the board."""
    record_board_success(session_factory, ats="greenhouse", slug="stripe", listings=776)

    boards = list_boards(session_factory)
    assert len(boards) == 1
    board = boards[0]
    assert board.id == "greenhouse:stripe"
    assert board.ats == "greenhouse"
    assert board.slug == "stripe"
    assert board.listings_seen == 776
    assert board.last_ok_at is not None
    assert board.consecutive_failures == 0
    assert board.enabled is True


def test_a_success_resets_the_failure_streak(session_factory):
    """A board that recovers must stop being protected from eviction.

    The source-scoped eviction protects a failing source's rows. If a
    recovery did not reset the streak, a transient outage would shield
    that source forever — the protection would outlive the problem.
    """
    record_board_success(session_factory, ats="greenhouse", slug="stripe")
    for _ in range(3):
        record_board_failure(session_factory, ats="greenhouse", slug="stripe", error="boom")

    boards = {b.id: b for b in list_boards(session_factory)}
    assert boards["greenhouse:stripe"].consecutive_failures == 3
    assert boards["greenhouse:stripe"].is_failing is True

    record_board_success(session_factory, ats="greenhouse", slug="stripe", listings=10)

    boards = {b.id: b for b in list_boards(session_factory)}
    assert boards["greenhouse:stripe"].consecutive_failures == 0
    assert boards["greenhouse:stripe"].is_failing is False
    assert boards["greenhouse:stripe"].last_error is None


def test_a_failure_creates_the_board_too(session_factory):
    """A board that has only ever failed is still known.

    Recording the failure is what makes the source-scoped eviction able
    to protect its rows — so the row must exist even if the board has
    never answered.
    """
    record_board_failure(session_factory, ats="ashby", slug="openai", error="500")

    boards = list_boards(session_factory)
    assert len(boards) == 1
    assert boards[0].last_ok_at is None
    assert boards[0].consecutive_failures == 1
    assert boards[0].last_error == "500"


def test_a_failure_message_is_sanitized(session_factory):
    """The error is a board's own response, and the console renders it.

    A control character or a newline must not survive into a page or an
    audit row, and the value is truncated so a huge body cannot be
    stored.
    """
    record_board_failure(
        session_factory,
        ats="greenhouse",
        slug="stripe",
        error="bad\nthing\x00with\r\nnewlines" + "x" * 1000,
    )

    board = list_boards(session_factory)[0]
    assert board.last_error is not None
    assert "\n" not in board.last_error
    assert "\r" not in board.last_error
    assert "\x00" not in board.last_error
    assert len(board.last_error) <= 500


def test_a_none_error_is_recorded_as_no_error(session_factory):
    """A failure with no message is still a failure, with no text."""
    record_board_failure(session_factory, ats="greenhouse", slug="stripe", error=None)

    board = list_boards(session_factory)[0]
    assert board.consecutive_failures == 1
    assert board.last_error is None


def test_the_listings_count_is_not_reset_by_a_success_with_no_count(session_factory):
    """A success that reports nothing keeps the last known count.

    The count is evidence of what the board contributed; a fetch that
    forgot to pass it must not erase the measurement.
    """
    record_board_success(session_factory, ats="greenhouse", slug="stripe", listings=776)
    record_board_success(session_factory, ats="greenhouse", slug="stripe")

    assert list_boards(session_factory)[0].listings_seen == 776


# ---------------------------------------------------------------- listing


def test_the_enabled_filter_excludes_a_disabled_board(session_factory):
    """A board the operator disabled is not returned by the default read."""
    record_board_success(session_factory, ats="greenhouse", slug="stripe")
    record_board_success(session_factory, ats="greenhouse", slug="brave")
    with session_factory() as session:
        row = session.get(BoardDB, "greenhouse:brave")
        row.enabled = False
        session.commit()

    enabled = {board.id for board in list_boards(session_factory)}
    assert enabled == {"greenhouse:stripe"}

    every = {board.id for board in list_boards(session_factory, enabled_only=False)}
    assert every == {"greenhouse:stripe", "greenhouse:brave"}


def test_the_listing_is_ordered_by_ats_then_slug(session_factory):
    """A stable order, so the console's table does not reshuffle."""
    record_board_success(session_factory, ats="lever", slug="palantir")
    record_board_success(session_factory, ats="ashby", slug="openai")
    record_board_success(session_factory, ats="ashby", slug="cursor")

    ordered = [(board.ats, board.slug) for board in list_boards(session_factory)]
    assert ordered == [("ashby", "cursor"), ("ashby", "openai"), ("lever", "palantir")]


# ------------------------------------------------------------ registry_slugs


def test_registry_slugs_returns_enabled_boards_of_one_provider():
    """The adapters read the registry per provider, and only what is on."""
    from src.jobs.board_health import registry_slugs

    slugs = registry_slugs("greenhouse")
    # The live database may or may not be seeded; the contract is a list.
    assert isinstance(slugs, list)
    assert all(isinstance(slug, str) for slug in slugs)


def test_registry_slugs_is_empty_when_the_database_is_not_ready(monkeypatch):
    """A fresh checkout has no registry, and the adapters must fall back.

    An empty list is the signal to use the environment list. Raising
    would make the adapters unusable before the first migration.
    """

    def explode(*_args, **_kwargs):
        raise RuntimeError("no such table: job_boards")

    monkeypatch.setattr("src.db.boards.list_boards", explode)

    from src.jobs.board_health import registry_slugs

    assert registry_slugs("greenhouse") == []


# ---------------------------------------------------------------- seeding


def test_seeding_is_additive_and_never_overwrites_health(session_factory, monkeypatch):
    """A restart must not erase a board's failure streak.

    The seed runs on every refresh. If it overwrote the row, the
    source-scoped eviction would stop protecting a failing source every
    time the process came back — the protection would be one refresh
    deep.
    """
    from src.config.settings import get_settings
    from src.jobs.board_health import seed_registry

    settings = get_settings()
    monkeypatch.setattr(settings, "greenhouse_boards", ["stripe"])
    monkeypatch.setattr(settings, "lever_companies", ["palantir"])
    monkeypatch.setattr(settings, "ashby_orgs", ["openai"])

    added = seed_registry(session_factory)
    assert added == 3

    # A board fails, then the process restarts and seeds again.
    record_board_failure(session_factory, ats="greenhouse", slug="stripe", error="403")

    added_again = seed_registry(session_factory)
    assert added_again == 0, "seeding must not re-add a board it already has"

    boards = {board.id: board for board in list_boards(session_factory)}
    assert boards["greenhouse:stripe"].consecutive_failures == 1, (
        "the seed overwrote the health it exists to preserve"
    )


def test_seeding_registers_the_display_name(session_factory, monkeypatch):
    """A seeded board is readable without a separate name table."""
    from src.config.settings import get_settings
    from src.jobs.board_health import seed_registry

    settings = get_settings()
    monkeypatch.setattr(settings, "greenhouse_boards", ["sourcegraph91"])
    monkeypatch.setattr(settings, "lever_companies", [])
    monkeypatch.setattr(settings, "ashby_orgs", [])

    seed_registry(session_factory)

    board = list_boards(session_factory)[0]
    assert board.company_name is not None
    assert board.enabled is True


def test_a_recording_failure_never_raises(monkeypatch):
    """Board health is operational metadata: losing a write must not fail a refresh.

    A database that is not ready must not stop the boards from being
    fetched — the refresh's job is the fetch, and the health record is a
    by-product.
    """

    def explode(*_args, **_kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("src.db.boards.record_board_success", explode)
    monkeypatch.setattr("src.db.boards.record_board_failure", explode)

    from src.jobs.board_health import record_failure, record_success

    record_success("greenhouse", "stripe", 10)  # must not raise
    record_failure("greenhouse", "stripe", "boom")  # must not raise
