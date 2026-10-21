"""Per-tenant accounting of the provider spend (WS-14 · Phase G).

**The threat.** The provider's daily quota is **platform-wide**. With
one operator, that is the right shape. With several users, one noisy
tenant can spend the whole quota and starve the others — the other
users' searches start failing with "the embedding budget is spent" and
they have no idea whose spend did it (threat T7).

**Two halves, and both matter.**

1. **Attribution.** The spend is recorded against the tenant that made
   it, so the question "who spent the quota" has an answer. Without it,
   a starvation event is invisible.
2. **A fair share.** A tenant may not spend more than its share of the
   platform's daily budget. The share is the platform budget divided by
   the number of tenants that have spent today, so a single tenant is
   unaffected — it has the whole budget — while a second tenant that
   arrives halves the first one's allowance and, more importantly, the
   budget that is left over goes to the tenant that has used less.

The counters live in the **embedding cache's** database, next to the
platform's own daily request counter. That is deliberate: the cache
database is already the durable, process-independent record of how much
provider spend has happened, and the two counters must agree.

**The tenant is a context variable.** The embedding layer is a
singleton that does not know who is calling it, so the request scope
publishes the tenant and the layer reads it. A call that happens
outside a request — a scheduled refresh, an operator script — has no
tenant and is charged to the platform, which is correct: it is the
operator's own spend.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from contextvars import ContextVar, Token

logger = logging.getLogger(__name__)

__all__ = [
    "TenantBudgetExceeded",
    "current_tenant",
    "record_spend",
    "tenant_allowance",
    "tenant_scope",
    "tenants_today",
]

#: The tenant of the request in flight, or ``None`` outside a request.
_TENANT: ContextVar[str | None] = ContextVar("tenant_owner_id", default=None)


class TenantBudgetExceeded(RuntimeError):
    """The tenant has spent its share of the provider's daily budget."""


def current_tenant() -> str | None:
    """The tenant of the request in flight, or ``None``."""
    return _TENANT.get()


@contextlib.contextmanager
def tenant_scope(owner_id: str | None) -> Iterator[str | None]:
    """Publish *owner_id* as the tenant for the duration of the block."""
    token: Token[str | None] = _TENANT.set(owner_id)
    try:
        yield owner_id
    finally:
        _TENANT.reset(token)


# -- the counters --------------------------------------------------------------


def _today() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).date().isoformat()


def record_spend(connection, owner_id: str, count: int = 1) -> None:
    """Record *count* provider calls against *owner_id*, for today."""
    if not owner_id or count <= 0:
        return
    connection.execute(
        "INSERT INTO tenant_spend (day, owner_id, count) VALUES (?, ?, ?) "
        "ON CONFLICT(day, owner_id) DO UPDATE SET count = count + excluded.count",
        (_today(), owner_id, count),
    )
    connection.commit()


def spend_today(connection, owner_id: str) -> int:
    """How many provider calls *owner_id* has made today."""
    row = connection.execute(
        "SELECT count FROM tenant_spend WHERE day = ? AND owner_id = ?",
        (_today(), owner_id),
    ).fetchone()
    return int(row[0]) if row else 0


def tenants_today(connection) -> int:
    """How many distinct tenants have spent today."""
    row = connection.execute(
        "SELECT COUNT(DISTINCT owner_id) FROM tenant_spend WHERE day = ?",
        (_today(),),
    ).fetchone()
    return int(row[0]) if row else 0


def tenant_allowance(connection, platform_budget: int) -> int:
    """How many provider calls the current tenant may still make today.

    The allowance is the platform's daily budget divided by the number
    of tenants that have spent today — at least one, so a single tenant
    has the whole budget and a second tenant halves it.

    A tenant that has not spent yet is allowed the whole remaining
    platform budget, because it cannot be the one that starved the
    others.
    """
    tenant = current_tenant()
    if not tenant:
        # Outside a request: the operator's own spend, charged to the
        # platform.
        return max(0, platform_budget)

    active = tenants_today(connection)
    spent = spend_today(connection, tenant)
    if spent == 0 and active <= 1:
        return max(0, platform_budget)

    share = max(1, platform_budget // max(1, active))
    return max(0, share - spent)
