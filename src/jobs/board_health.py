"""Recording a board's health from an adapter (WS-23, Phase 5).

The adapters know two things the rest of the system does not: whether a
board answered, and how many listings it served. Recording them is what
makes the board registry useful — and what lets the eviction exclude a
failing source's rows.

The recording is deliberately **best-effort**. A board's health is
operational metadata: losing a write must never fail a refresh, and a
database that is not ready must not stop the boards from being fetched.
Every failure is logged and swallowed.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["record_failure", "record_success", "registry_slugs", "seed_registry"]


def registry_slugs(ats: str) -> list[str]:
    """The enabled boards of one provider, from the registry.

    An empty list means "the registry has nothing for this provider" —
    either because it was never seeded or because the database is not
    ready. The caller falls back to the environment list in that case,
    so a fresh checkout with no registry still works.
    """
    try:
        from src.db.boards import list_boards

        return [board.slug for board in list_boards(enabled_only=True) if board.ats == ats]
    except Exception:
        logger.debug("Could not read the board registry for %s", ats, exc_info=True)
        return []


def record_success(ats: str, slug: str, listings: int = 0) -> None:
    """Record that a board answered, and how many listings it served."""
    try:
        from src.db.boards import record_board_success

        record_board_success(ats=ats, slug=slug, listings=listings)
    except Exception:
        logger.debug("Could not record the health of %s:%s", ats, slug, exc_info=True)


def record_failure(ats: str, slug: str, error: object) -> None:
    """Record that a board failed, and why."""
    try:
        from src.db.boards import record_board_failure

        record_board_failure(ats=ats, slug=slug, error=str(error))
    except Exception:
        logger.debug("Could not record the health of %s:%s", ats, slug, exc_info=True)


def seed_registry(session_factory=None) -> int:
    """Seed the board registry from the three environment lists.

    The env lists remain the operator's bootstrap; the registry is where
    the health lives afterwards. Seeding is **additive**: a board already
    in the registry is left alone, so the registry's own state (the
    health, the display name) is not overwritten by a restart.

    Returns:
        The number of boards added.
    """
    from src.db.boards import BoardDB
    from src.db.session import SessionLocal

    factory = session_factory or SessionLocal
    try:
        from src.config.settings import get_settings

        settings = get_settings()
        candidates = (
            [("greenhouse", board) for board in settings.greenhouse_boards]
            + [("lever", company) for company in settings.lever_companies]
            + [("ashby", org) for org in settings.ashby_orgs]
        )
    except Exception:
        logger.exception("Could not read the board lists; the registry is unchanged")
        return 0

    added = 0
    try:
        with factory() as session:
            for ats, slug in candidates:
                if not slug:
                    continue
                board_id = f"{ats}:{slug}"
                if session.get(BoardDB, board_id) is not None:
                    continue
                session.add(
                    BoardDB(
                        id=board_id,
                        ats=ats,
                        slug=slug,
                        company_name=slug.replace("-", " ").replace("_", " ").title(),
                        enabled=True,
                    )
                )
                added += 1
            session.commit()
    except Exception:
        logger.exception("Could not seed the board registry")
        return 0
    if added:
        logger.info("Seeded %d boards into the registry", added)
    return added
