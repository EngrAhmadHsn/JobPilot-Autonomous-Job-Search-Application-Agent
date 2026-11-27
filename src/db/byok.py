"""Database model for per-user LLM provider credentials (WS-22).

**Why a row per connection.** A user may hold several provider keys at once —
a Gemini key, a work Groq key, a self-hosted OpenAI-compatible endpoint — and
WS-22's follow-up lets them store, edit and remove each one. The previous
schema could not: ``owner_id`` *was* the primary key, so registering a second
provider overwrote the first. ``id`` is now the primary key and ``owner_id``
is an indexed column, so one account owns many connections without a second
user's row becoming reachable.

**Which connection is in use.** :attr:`LlmCredentialDB.activation_rank`
decides: the highest rank wins, and ties are broken by ``created_at`` (then
``id``) so the answer is always deterministic. **A new connection never
silently takes over** — it is created at rank 0, so the connection already in
use stays in use until the owner explicitly activates another one. Rows that
predate this change keep rank 0 and stay in use, which is why the upgrade
needs no data decision: nothing about an existing credential's behaviour
changes.

**What is stored.** The encrypted key (never the plaintext — see
:mod:`src.security.secrets`), the provider, the model, an optional base URL
for chat-completions endpoints, and a display hint (the last four characters)
so the owner can tell *which* key is registered without the platform being
able to read it back.

**Who may read it.** Only the owner, and never a superuser: the platform's
cross-owner audit view is a legitimate exception for audit rows and an
illegitimate one for a credential. ``src.db.access`` enforces that, and a
test proves it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

#: How much of the key is kept as a display hint. Four characters is what
#: most providers' dashboards themselves show; it identifies a key without
#: meaningfully shortening it.
HINT_CHARS = 4


def hint_of(api_key: str) -> str:
    """The display hint for *api_key* — its last four characters."""
    key = (api_key or "").strip()
    return key[-HINT_CHARS:] if len(key) >= HINT_CHARS else ""


def new_credential_id() -> str:
    """A fresh connection id.

    An opaque, unguessable value rather than a counter: the id travels in the
    URL of every per-connection route, and the routes are owner-scoped, but an
    identifier that cannot be enumerated is one less thing to get wrong.
    """
    return uuid4().hex


class LlmCredentialDB(Base):
    """One stored model-provider connection, owned by one account."""

    __tablename__ = "llm_credentials"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_credential_id)
    #: The owner. Indexed, not unique — an account may hold several
    #: connections, which is the whole point of this table now.
    owner_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    #: The Fernet token. Never the plaintext key; no code path writes the
    #: plaintext here.
    encrypted_key: Mapped[str] = mapped_column(String, nullable=False)
    hint: Mapped[str] = mapped_column(String, nullable=False, default="")
    #: Which connection is in use: the highest rank among the owner's rows.
    #: Activation raises it above every other row, so "in use" is a value
    #: rather than a flag two writers could disagree about.
    activation_rank: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
