"""Database model for per-user LLM provider credentials (WS-22).

**Why one row per user.** A provider key belongs to the person who pays for
it, so the owner *is* the key: ``owner_id`` is the primary key and there is
no second identifier to guess. Registering a new credential replaces the
old one — the schema has no room for a stray half-forgotten key.

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

from sqlalchemy import DateTime, String
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


class LlmCredentialDB(Base):
    """One user's registered model-provider credential."""

    __tablename__ = "llm_credentials"

    owner_id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    #: The Fernet token. Never the plaintext key; no code path writes the
    #: plaintext here.
    encrypted_key: Mapped[str] = mapped_column(String, nullable=False)
    hint: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
