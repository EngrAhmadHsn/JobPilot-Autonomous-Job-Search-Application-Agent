"""Database model for official visa-sponsorship registers (WS-22).

**Reference data, not user data.** This table holds rows imported from
official government publications — the US USCIS H-1B Employer Data Hub and
the UK Home Office register of licensed sponsors. It is deliberately **not**
owner-scoped: it is the same public list for every account, like ``jobs``.

**Where the rows come from.** An operator imports an official CSV export with
``scripts/import_visa_sponsors.py``. The platform never fetches these files at
request time, and no row is ever invented: a company that is not in the table
is reported as "no entry found in the imported registers" — a statement about
the register, never about the company.

Rows are replaced per ``(source, year)`` on re-import, so loading a newer
year's export is idempotent.
"""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

#: The registers this table can hold.
SOURCE_USCIS = "uscis_h1b"
SOURCE_UK = "uk_home_office"
SOURCES = (SOURCE_USCIS, SOURCE_UK)

#: The country each register covers, for display.
COUNTRY_OF_SOURCE = {
    SOURCE_USCIS: "US",
    SOURCE_UK: "UK",
}


class VisaSponsorDB(Base):
    """One employer entry in one official register."""

    __tablename__ = "visa_sponsors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    #: The company name reduced by the deterministic normalizer
    #: (``src.matching.sponsors.normalize_company``) — the lookup key.
    name_normalized: Mapped[str] = mapped_column(String, nullable=False, index=True)
    #: The name exactly as the register prints it, for display.
    name_raw: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str] = mapped_column(String, nullable=False)
    #: The register's year, when it has one (the USCIS export is yearly;
    #: the UK register is a point-in-time list).
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: USCIS approval/denial counts for the year. ``None`` when the register
    #: does not carry counts (UK).
    approvals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    denials: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Register-specific detail: town (UK) or worksite state count (US).
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
