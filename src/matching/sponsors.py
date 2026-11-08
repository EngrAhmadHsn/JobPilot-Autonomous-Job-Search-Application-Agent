"""Verified visa-sponsorship lookup from official registers (WS-22).

**Why this module exists.** "Does this employer sponsor visas?" is a factual
question that language models answer with confident guesswork. Two
governments publish the answer as data:

- the **USCIS H-1B Employer Data Hub** — a yearly CSV export of every
  employer that filed H-1B petitions, with approval and denial counts;
- the **UK Home Office register** of licensed sponsors — the organisations
  licensed to sponsor Skilled Worker and Temporary Worker visas.

The reference project that inspired this feature used those registers to
"elevate verified sponsors and demote unverified ones" in its score. **That
half is deliberately not implemented here.** Absence from a partial register
is not evidence against a company, and folding it into a score would present
an opinion as a measurement. What this module does instead is *verify and
inform*: a status, a register-scoped note, and a badge the operator can read.

**The wording rule.** Every note is about the **register**, never about the
company. "Listed in the USCIS H-1B Employer Data Hub (FY2024: 132
approvals)" is a fact. "Does not sponsor visas" would be a claim this data
cannot support — the register records filings, not policy — so the negative
finding is always phrased as "no entry found in the imported registers",
which is a statement about our data and nothing else.

**Matching is deliberately conservative.** Names are compared after
normalization (lower-cased, punctuation removed, legal suffixes dropped) and
must match **exactly**. Fuzzy matching would raise the rate of false
"verified" results, and a false positive here is a factual claim made to a
candidate about an employer — the one direction this feature must not fail
in. A missed match is a missing badge; a wrong match is a lie.
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.db.sponsors import (
    COUNTRY_OF_SOURCE,
    SOURCE_UK,
    SOURCE_USCIS,
    VisaSponsorDB,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SPONSOR_NOT_FOUND",
    "SPONSOR_NO_DATA",
    "SPONSOR_VERIFIED",
    "ImportReport",
    "SponsorVerdict",
    "import_sponsor_csv",
    "lookup_companies",
    "lookup_company",
    "normalize_company",
]

#: The verdict states.
SPONSOR_VERIFIED = "verified"
SPONSOR_NOT_FOUND = "not_found"
SPONSOR_NO_DATA = "no_data"

#: Corporate forms that carry no identity, stripped before comparing names.
#: Deliberately limited to legal forms: words like "Group", "Technologies" or
#: "Solutions" do carry identity, and stripping them would make two unrelated
#: employers compare equal.
_LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "llp",
        "lp",
        "ltd",
        "limited",
        "plc",
        "corp",
        "corporation",
        "co",
        "gmbh",
        "ag",
        "sa",
        "sas",
        "sarl",
        "srl",
        "spa",
        "bv",
        "nv",
        "oy",
        "ab",
        "as",
        "aps",
        "pte",
        "kk",
        "doo",
        "sro",
        "zoo",
    }
)


def normalize_company(name: str) -> str:
    """Reduce a company name to the form the register is keyed on.

    Lower-case, punctuation (including the hyphen, which employers write
    inconsistently) to spaces, legal suffixes dropped from the end,
    whitespace collapsed. ``&`` and ``+`` are kept because they are part of
    a name — ``Barnes & Noble`` is not ``Barnes and Noble`` to a register.
    Deterministic and offline: the same name always reduces to the same key,
    on import and on lookup.
    """
    text = (name or "").strip().lower()
    text = re.sub(r"[^\w\s&+]", " ", text)
    text = text.replace("_", " ")
    words = [word for word in text.split() if word]
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


@dataclass(frozen=True)
class SponsorVerdict:
    """What the imported registers say about one company — and nothing more."""

    status: str
    note: str | None = None
    sources: tuple[str, ...] = ()
    year: int | None = None
    approvals: int | None = None
    denials: int | None = None

    @property
    def verified(self) -> bool:
        """True only for a positive, register-backed finding."""
        return self.status == SPONSOR_VERIFIED


#: The verdict for a deployment that has imported nothing. Not "not found":
#: an empty register is not evidence of anything.
_NO_DATA = SponsorVerdict(status=SPONSOR_NO_DATA)

_SOURCE_LABELS = {
    SOURCE_USCIS: "the USCIS H-1B Employer Data Hub",
    SOURCE_UK: "the UK Home Office register of licensed sponsors",
}


def _note_for(row: VisaSponsorDB) -> str:
    """The register-scoped note for a match (never a claim about the company).

    Only the year and the counts are reported. The register's own extra
    columns (a US worksite city, a UK route) are not put in the sentence: a
    note a candidate reads should say what the finding is, and the row keeps
    the detail for anyone who wants it.
    """
    label = _SOURCE_LABELS.get(row.source, row.source)
    parts: list[str] = []
    if row.year is not None:
        parts.append(f"FY{row.year}")
    if row.approvals is not None:
        detail = f"{row.approvals} approvals"
        if row.denials is not None:
            detail += f", {row.denials} denials"
        parts.append(detail)
    suffix = f" ({', '.join(parts)})" if parts else ""
    return f"Listed in {label}{suffix}."


# -- import -------------------------------------------------------------------


@dataclass
class ImportReport:
    """What one CSV import did."""

    source: str
    rows_read: int = 0
    employers: int = 0
    years: list[int] = field(default_factory=list)
    path: str = ""

    def describe(self) -> str:
        year_text = ", ".join(str(year) for year in self.years) or "no year column"
        return (
            f"{self.source}: read {self.rows_read} row(s) for {self.employers} "
            f"employer(s) [{year_text}]"
        )


def _header_index(headers: Sequence[str]) -> dict[str, int]:
    """Map normalized header names to their column index."""
    return {
        re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_"): i
        for i, header in enumerate(headers)
    }


def _pick(index: dict[str, int], *candidates: str) -> int | None:
    """The first candidate column that exists, by exact or substring match."""
    for candidate in candidates:
        if candidate in index:
            return index[candidate]
    for candidate in candidates:
        for name, position in index.items():
            if candidate in name:
                return position
    return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _sum_counts(*values: int | None) -> int | None:
    """Sum the present counts; ``None`` when the row carried none of them."""
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def import_sponsor_csv(session: Session, source: str, path: str | Path) -> ImportReport:
    """Import one official CSV export into ``visa_sponsors``.

    The column names are detected rather than pinned: both registers have
    changed their export shape between years, and a loader that insists on
    one exact header set breaks the first time it matters. Rows for a
    ``(source, year)`` are replaced, so re-importing a corrected file is
    idempotent.

    Raises:
        ValueError: the file has no recognisable employer column, or the
            source is not one of the known registers.
    """
    if source not in (SOURCE_USCIS, SOURCE_UK):
        raise ValueError(f"Unknown sponsor register {source!r}")

    report = ImportReport(source=source, path=str(path))
    rows: list[dict] = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            headers = next(reader)
        except StopIteration:
            return report
        index = _header_index(headers)
        name_at = _pick(
            index, "employer_petitioner_name", "employer", "organisation_name", "organization_name"
        )
        if name_at is None:
            raise ValueError(
                f"{Path(path).name}: no employer/organisation column found in {headers!r}"
            )
        year_at = _pick(index, "fiscal_year", "year")
        # The USCIS export splits each count into an *initial* and a
        # *continuing* column; both are approvals (or denials) against the
        # same employer, so they are read separately and summed. A register
        # that carries a single count column still works: the first _pick
        # that matches wins and the second is None.
        approvals_at = _pick(index, "initial_approval", "approval", "approvals")
        continuing_approvals_at = _pick(index, "continuing_approval")
        denials_at = _pick(index, "initial_denial", "denial", "denials")
        continuing_denials_at = _pick(index, "continuing_denial")
        city_at = _pick(index, "city", "town_city", "town")
        state_at = _pick(index, "state")
        route_at = _pick(index, "route", "type_rating")

        def cell(row: Sequence[str], position: int | None) -> str | None:
            if position is None or position >= len(row):
                return None
            value = row[position].strip()
            return value or None

        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            report.rows_read += 1
            name_raw = cell(row, name_at)
            if not name_raw:
                continue
            year = _to_int(cell(row, year_at))
            detail_parts = [
                part
                for part in (cell(row, route_at), cell(row, city_at), cell(row, state_at))
                if part
            ]
            approvals = _sum_counts(
                _to_int(cell(row, approvals_at)),
                _to_int(cell(row, continuing_approvals_at)),
            )
            denials = _sum_counts(
                _to_int(cell(row, denials_at)),
                _to_int(cell(row, continuing_denials_at)),
            )
            rows.append(
                {
                    "name_normalized": normalize_company(name_raw),
                    "name_raw": name_raw,
                    "source": source,
                    "country": COUNTRY_OF_SOURCE.get(source, ""),
                    "year": year,
                    "approvals": approvals,
                    "denials": denials,
                    "detail": ", ".join(detail_parts)[:200] or None,
                }
            )

    if not rows:
        return report

    # Replace per (source, year) so a re-import is idempotent. The USCIS
    # export can hold several rows per employer (per worksite city); they
    # are summed per employer below.
    years = sorted({int(row["year"]) for row in rows if row["year"] is not None})
    if years:
        session.execute(
            delete(VisaSponsorDB).where(
                VisaSponsorDB.source == source, VisaSponsorDB.year.in_(years)
            )
        )
    else:
        session.execute(delete(VisaSponsorDB).where(VisaSponsorDB.source == source))

    aggregated: dict[tuple[str, int | None], dict] = {}
    for row in rows:
        key = (row["name_normalized"], row["year"])
        current = aggregated.get(key)
        if current is None:
            aggregated[key] = dict(row)
            continue
        for field_name in ("approvals", "denials"):
            value = row.get(field_name)
            if value is None:
                continue
            current[field_name] = (current.get(field_name) or 0) + value

    for row in aggregated.values():
        session.add(VisaSponsorDB(**row))
    session.commit()

    report.employers = len(aggregated)
    report.years = years
    logger.info("Imported sponsor register: %s", report.describe())
    return report


# -- lookup -------------------------------------------------------------------


def _verdict_from_rows(rows: Sequence[VisaSponsorDB]) -> SponsorVerdict:
    """The verdict for the rows that matched one normalized company name."""
    if not rows:
        return _NO_DATA
    # Prefer the row that carries counts (USCIS), then the newest year.
    ordered = sorted(
        rows,
        key=lambda row: (row.approvals is not None, row.year or 0),
        reverse=True,
    )
    best = ordered[0]
    return SponsorVerdict(
        status=SPONSOR_VERIFIED,
        note=_note_for(best),
        sources=tuple(sorted({row.source for row in rows})),
        year=best.year,
        approvals=best.approvals,
        denials=best.denials,
    )


_NOT_FOUND_NOTE = (
    "No entry found in the imported sponsorship registers "
    "(USCIS H-1B Employer Data Hub / UK Home Office)."
)


def lookup_companies(session: Session, companies: Iterable[str]) -> dict[str, SponsorVerdict]:
    """Verdicts for many companies in one query, keyed by the input string.

    The batch form exists because both callers (a search result, a matches
    list) look up dozens of companies at once, and a query per company would
    make the enrichment the slowest part of the response.
    """
    normalized = {company: normalize_company(company) for company in companies if company}
    keys = sorted({key for key in normalized.values() if key})
    if not keys:
        return {company: _NO_DATA for company in normalized}

    rows = list(
        session.execute(
            select(VisaSponsorDB).where(VisaSponsorDB.name_normalized.in_(keys))
        ).scalars()
    )
    if not rows:
        # No register imported at all, or nothing matched: those are different
        # answers, and saying which one is the point of the module.
        any_register = session.execute(select(VisaSponsorDB.id).limit(1)).first() is not None
        verdict = _NO_DATA if not any_register else None
        if verdict is not None:
            return {company: verdict for company in normalized}
        return {
            company: SponsorVerdict(status=SPONSOR_NOT_FOUND, note=_NOT_FOUND_NOTE)
            for company in normalized
        }

    by_key: dict[str, list[VisaSponsorDB]] = {}
    for row in rows:
        by_key.setdefault(row.name_normalized, []).append(row)

    verdicts: dict[str, SponsorVerdict] = {}
    for company, key in normalized.items():
        matched = by_key.get(key)
        if matched:
            verdicts[company] = _verdict_from_rows(matched)
        else:
            verdicts[company] = SponsorVerdict(status=SPONSOR_NOT_FOUND, note=_NOT_FOUND_NOTE)
    return verdicts


def lookup_company(session: Session, company: str) -> SponsorVerdict:
    """The verdict for one company (the batch lookup with one input)."""
    return lookup_companies(session, [company]).get(company, _NO_DATA)


# -- API-side enrichment ------------------------------------------------------
#
# These helpers live here rather than in the route module for a reason the
# isolation matrix enforces: a route may name a table only through a known
# model in a `select(Model)` shape, and it may not call `.get(...)` on
# anything (the checker cannot tell `db.get(Model, key)` from `dict.get(key)`).
# Both rules exist because they caught real evasions; the enrichment therefore
# belongs in the layer that already owns the register lookup.


def companies_for_job_ids(session: Session, job_ids: Sequence[str]) -> dict[str, str]:
    """The company of each job id, in one query over the shared corpus."""
    if not job_ids:
        return {}
    from sqlalchemy import select

    from src.db.jobs import JobDB

    rows = session.execute(
        select(JobDB).with_only_columns(JobDB.id, JobDB.company).where(
            JobDB.id.in_(sorted(set(job_ids)))
        )
    ).all()
    return {row[0]: row[1] for row in rows if row[1]}


def attach_sponsor_status(session: Session, matches: Sequence, companies: Sequence[str]) -> None:
    """Attach the sponsorship finding to freshly scored matches (WS-22).

    One batched lookup for the whole result set. A deployment with no register
    imported gets ``no_data`` on every match — which is the honest answer, and
    the reason it is not reported as "not found".
    """
    if not matches:
        return
    verdicts = lookup_companies(session, companies)
    for match, company in zip(matches, companies, strict=False):
        verdict = verdicts.get(company)
        if verdict is None:
            continue
        match.sponsor_status = verdict.status
        match.sponsor_note = verdict.note


def sponsor_fields_for_jobs(
    session: Session, job_ids: Sequence[str]
) -> dict[str, tuple[str | None, str | None]]:
    """(status, note) for **every** requested job id, for read-time enrichment.

    The persisted match rows carry scores, not companies, so the finding is
    computed here from the shared corpus and the register — always fresh: a
    register imported this morning is reflected in a match computed last month.

    Every requested id appears in the result; one with no verdict maps to
    ``(None, None)``. That is deliberate rather than convenient: the route
    reads the mapping with ``fields[job_id]`` and therefore needs no
    conditional and no ``.get()`` — and the isolation matrix forbids a
    ``.get(<name>)`` call in a route module, because it cannot tell a dict
    lookup from ``db.get(Model, key)``.
    """
    fields: dict[str, tuple[str | None, str | None]] = {
        job_id: (None, None) for job_id in job_ids
    }
    if not job_ids:
        return fields
    companies = companies_for_job_ids(session, job_ids)
    verdicts = lookup_companies(session, companies.values())
    for job_id, company in companies.items():
        verdict = verdicts.get(company)
        if verdict is not None:
            fields[job_id] = (verdict.status, verdict.note)
    return fields
