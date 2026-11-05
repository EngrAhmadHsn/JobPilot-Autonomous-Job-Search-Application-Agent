"""Shared circuit-breaker state (WS-18).

A breaker that lives only in one process's memory is correct for one worker
and wrong for three: worker A opens its circuit on a provider outage, worker
B keeps hammering the provider, and the operator's "the provider is down"
answer depends on which process served the request.

This store puts the durable part of a breaker's state — state, failure count,
when it opened — in the ``circuit_breakers`` table. Reads are cached by the
breaker for a couple of seconds, so the database is not on the hot path of
every outbound call. A store failure degrades to in-memory behaviour; it
never fails the provider call.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from src.db.runs import CircuitBreakerDB
from src.llm.resilience import CircuitRecord

logger = logging.getLogger(__name__)

__all__ = ["DatabaseCircuitStore"]


class DatabaseCircuitStore:
    """The ``circuit_breakers`` table, as a :class:`CircuitRecord` store."""

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory

    def _factory(self) -> sessionmaker:
        if self._session_factory is not None:
            return self._session_factory
        from src.db.session import SessionLocal

        return SessionLocal

    def load(self, name: str) -> CircuitRecord | None:
        factory = self._factory()
        with factory() as session:
            row = session.get(CircuitBreakerDB, name)
            if row is None:
                return None
            return CircuitRecord(
                state=row.state,
                failure_count=int(row.failure_count),
                opened_at_epoch=_to_epoch(row.opened_at),
            )

    def save(self, name: str, record: CircuitRecord) -> None:
        factory = self._factory()
        with factory() as session:
            _save(session, name, record)


def _save(session: Session, name: str, record: CircuitRecord) -> None:
    row = session.get(CircuitBreakerDB, name)
    if row is None:
        row = CircuitBreakerDB(
            name=name,
            state=record.state,
            failure_count=int(record.failure_count),
            opened_at=_from_epoch(record.opened_at_epoch),
        )
        session.add(row)
    else:
        row.state = record.state
        row.failure_count = int(record.failure_count)
        row.opened_at = _from_epoch(record.opened_at_epoch)
    session.commit()


def _to_epoch(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _from_epoch(value: float | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, UTC).replace(tzinfo=None)
