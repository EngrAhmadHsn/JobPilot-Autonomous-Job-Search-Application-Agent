from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.settings import get_settings


def ensure_sqlite_parent_dir(url: str) -> None:
    """Create the parent directory of a SQLite file database if missing.

    SQLite creates the database *file* on first connect, but not intermediate
    directories, so a default URL like ``sqlite:///./data/app.db`` fails on a
    fresh checkout until ``data/`` exists. Non-SQLite URLs and in-memory
    databases are ignored. No-op when the parent already exists.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return
    path_part = url[len(prefix) :].split("?")[0]  # drop URI query params
    if not path_part or path_part.startswith(":memory:"):
        return
    parent = Path(path_part).parent
    if str(parent) in ("", "."):
        return
    parent.mkdir(parents=True, exist_ok=True)


settings = get_settings()
ensure_sqlite_parent_dir(settings.database_url)
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a database session scoped to one request.

    Routers use ``db: Session = Depends(get_db)`` instead of opening sessions
    inline, so session lifetime is tied to the request lifecycle.

    Exception: the application submit node (``src/graph/nodes.py``) opens its
    own ``SessionLocal()`` when it is called outside a request — a run of the
    graph on its own has no request-scoped session to inherit. When the API
    calls it, the request's session is handed over and the node uses that one
    (WS-07).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
