"""Record live job-source API payloads as test fixtures (WS-02 task 6).

Dev-time helper, never runs in CI or tests: fetches each configured source
once through the same guarded HTTP path the adapters use and writes the raw
provider JSON under ``tests/fixtures/sources/``. The MockTransport-based
adapter tests replay these files, so the normalizers are exercised against
real response shapes with zero live network in the suite.

Usage:
    python scripts/record_source_fixtures.py [--boards stripe,figma]
        [--companies leverdemo] [--remotive-query python] [--limit 8]
        [--out-dir tests/fixtures/sources]

Boards/companies default to the configured settings (GREENHOUSE_BOARDS /
LEVER_COMPANIES from .env). ``--limit`` keeps only the first N jobs per
source so committed fixtures stay small while preserving field structure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.config.settings import get_settings
from src.jobs.greenhouse_adapter import GREENHOUSE_BASE_URL
from src.jobs.http_client import SourceError, create_client, guarded_get
from src.jobs.lever_adapter import LEVER_BASE_URL
from src.jobs.remotive_adapter import REMOTIVE_BASE_URL


def _trim_jobs(payload, limit: int | None):
    """Trim a payload's job list to ``limit`` entries, preserving structure."""
    if limit is None or not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        return payload
    trimmed = dict(payload)
    trimmed["jobs"] = payload["jobs"][:limit]
    return trimmed


async def record(
    boards: list[str],
    companies: list[str],
    remotive_query: str,
    limit: int | None,
    out_dir: Path,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    recorded = 0
    async with create_client() as client:
        fetches: list[tuple[str, str, object]] = []
        for token in boards:
            fetches.append(
                (
                    "greenhouse",
                    token,
                    f"{GREENHOUSE_BASE_URL}/{token}/jobs?content=true",
                )
            )
        for company in companies:
            fetches.append(("lever", company, f"{LEVER_BASE_URL}/{company}?mode=json"))
        fetches.append(
            (
                "remotive",
                remotive_query or "all",
                f"{REMOTIVE_BASE_URL}?search={remotive_query}"
                if remotive_query
                else REMOTIVE_BASE_URL,
            )
        )

        for source, key, url in fetches:
            name = f"{source}.json"
            try:
                response = await guarded_get(client, url)
                payload = response.json()
            except (SourceError, ValueError) as exc:
                print(f"FAIL {name} ({key}): {exc}")
                continue
            if source == "remotive" or source == "greenhouse" and limit is not None:
                payload = _trim_jobs(payload, limit)
            elif source == "lever" and limit is not None and isinstance(payload, list):
                payload = payload[:limit]
            path = out_dir / name
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            size_kb = path.stat().st_size / 1024
            print(f"Wrote {path} ({size_kb:.0f} KB, key={key!r})")
            recorded += 1
    return recorded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boards", default="", help="Comma-separated Greenhouse board tokens")
    parser.add_argument("--companies", default="", help="Comma-separated Lever company slugs")
    parser.add_argument("--remotive-query", default="python", help="Remotive search term")
    parser.add_argument("--limit", type=int, default=8, help="Max jobs per source in the fixture")
    parser.add_argument(
        "--out-dir",
        default="tests/fixtures/sources",
        help="Output directory (relative to repo root)",
    )
    args = parser.parse_args()

    settings = get_settings()
    boards = (
        [b.strip() for b in args.boards.split(",") if b.strip()]
        or list(settings.greenhouse_boards)
        or ["stripe"]
    )
    companies = (
        [c.strip() for c in args.companies.split(",") if c.strip()]
        or list(settings.lever_companies)
        or ["leverdemo"]
    )
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir

    recorded = asyncio.run(record(boards, companies, args.remotive_query, args.limit, out_dir))
    return 0 if recorded else 1


if __name__ == "__main__":
    raise SystemExit(main())
