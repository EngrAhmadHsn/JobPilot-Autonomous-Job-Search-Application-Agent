"""WS-22 · verified visa-sponsorship lookup (Phase B5).

The claim under test is narrow: **the register is a source of facts, and the
verdict never says more than the register supports.** So the tests cover

- normalization (which must not erase identity),
- import (header detection, per-year idempotency, per-employer aggregation),
- the three verdicts and their wording — in particular that "not found" is
  phrased about *our registers* and never about the company,
- the empty-register case, which is ``no_data`` and not ``not_found``,
- and the enrichment: the finding rides on the match result without touching
  a single score.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.db.base import Base
from src.db.sponsors import SOURCE_UK, SOURCE_USCIS, VisaSponsorDB
from src.matching.sponsors import (
    SPONSOR_NO_DATA,
    SPONSOR_NOT_FOUND,
    SPONSOR_VERIFIED,
    import_sponsor_csv,
    lookup_companies,
    lookup_company,
    normalize_company,
)

USCIS_CSV = """Fiscal Year,Employer (Petitioner) Name,City,State,Initial Approval,Initial Denial,Continuing Approval,Continuing Denial
2024,ACME AI INC,San Francisco,CA,10,1,40,2
2024,ACME AI INC,New York,NY,5,0,20,1
2024,Agentic Labs LLC,London,,3,0,,0
2023,ACME AI INC,San Francisco,CA,8,0,30,1
2024,Unrelated Corp,,,1,0,0,0
"""

UK_CSV = """Organisation Name,Town/City,County,Type & Rating,Route
Agentic Labs Ltd,London,,Worker (A rating),Skilled Worker
Sponsorly Services Limited,Manchester,,Worker (A rating),Skilled Worker
"""


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{(tmp_path / 'sponsors.db').as_posix()}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, autoflush=False, autocommit=False)() as db:
        yield db


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# -- normalization ------------------------------------------------------------


class TestNormalization:
    def test_legal_suffixes_are_dropped(self) -> None:
        assert normalize_company("Acme AI Inc.") == "acme ai"
        assert normalize_company("Acme AI LLC") == "acme ai"
        assert normalize_company("Acme AI Limited") == "acme ai"

    def test_identity_words_are_kept(self) -> None:
        """Stripping "Group"/"Technologies" would merge unrelated employers."""
        assert normalize_company("Acme Technologies Inc") == "acme technologies"
        assert normalize_company("Acme Group Ltd") == "acme group"

    def test_punctuation_and_case_do_not_matter(self) -> None:
        assert normalize_company("ACME AI, INC.") == normalize_company("acme  ai inc")
        assert normalize_company("Acme-AI") == "acme ai"

    def test_an_empty_name_normalizes_to_empty(self) -> None:
        assert normalize_company("") == ""
        assert normalize_company("  Inc. ") == ""


# -- import -------------------------------------------------------------------


class TestImport:
    def test_it_reads_the_uscis_export_and_aggregates_per_employer(
        self, session: Session, tmp_path: Path
    ) -> None:
        report = import_sponsor_csv(session, SOURCE_USCIS, _write(tmp_path, "us.csv", USCIS_CSV))
        assert report.rows_read == 5
        # (employer, year) pairs: acme 2024, acme 2023, agentic labs 2024,
        # unrelated 2024.
        assert report.employers == 4
        assert report.years == [2023, 2024]

        rows = list(
            session.execute(
                select(VisaSponsorDB).where(
                    VisaSponsorDB.name_normalized == "acme ai", VisaSponsorDB.year == 2024
                )
            ).scalars()
        )
        assert len(rows) == 1
        # Both worksite rows were summed.
        assert rows[0].approvals == 10 + 40 + 5 + 20
        assert rows[0].denials == 1 + 2 + 0 + 1
        assert rows[0].country == "US"

    def test_a_reimport_of_the_same_year_replaces_it(
        self, session: Session, tmp_path: Path
    ) -> None:
        path = _write(tmp_path, "us.csv", USCIS_CSV)
        first = import_sponsor_csv(session, SOURCE_USCIS, path)
        second = import_sponsor_csv(session, SOURCE_USCIS, path)
        # 2023 holds one employer and 2024 holds three — and the second
        # import replaced them rather than duplicating them.
        assert first.employers == second.employers == 4
        assert len(session.execute(select(VisaSponsorDB.id)).all()) == 4

    def test_a_reimport_replaces_only_the_years_it_carries(
        self, session: Session, tmp_path: Path
    ) -> None:
        import_sponsor_csv(session, SOURCE_USCIS, _write(tmp_path, "us.csv", USCIS_CSV))
        # A file for 2024 alone: the 2023 row must survive it.
        corrected = USCIS_CSV.replace("2024,Unrelated Corp,,,1,0,0,0\n", "")
        annual = _write(tmp_path, "us-2024.csv", corrected)
        import_sponsor_csv(session, SOURCE_USCIS, annual)
        assert lookup_company(session, "Unrelated Corp").status == SPONSOR_NOT_FOUND
        assert lookup_company(session, "ACME AI INC").status == SPONSOR_VERIFIED
        # The 2023 row is still there: the import touched 2024 only.
        years = {
            row[0]
            for row in session.execute(
                select(VisaSponsorDB.year).where(VisaSponsorDB.name_normalized == "acme ai")
            ).all()
        }
        assert years == {2023, 2024}

    def test_it_reads_the_uk_register(self, session: Session, tmp_path: Path) -> None:
        report = import_sponsor_csv(session, SOURCE_UK, _write(tmp_path, "uk.csv", UK_CSV))
        assert report.employers == 2
        verdict = lookup_company(session, "Agentic Labs Ltd")
        assert verdict.status == SPONSOR_VERIFIED
        assert "UK Home Office" in verdict.note
        assert SOURCE_UK in verdict.sources

    def test_a_file_with_no_employer_column_is_refused(
        self, session: Session, tmp_path: Path
    ) -> None:
        path = _write(tmp_path, "bad.csv", "some,other,headers\n1,2,3\n")
        with pytest.raises(ValueError, match="no employer"):
            import_sponsor_csv(session, SOURCE_USCIS, path)

    def test_an_unknown_register_is_refused(self, session: Session, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Unknown sponsor register"):
            import_sponsor_csv(session, "somewhere_else", _write(tmp_path, "x.csv", USCIS_CSV))

    def test_an_empty_file_is_a_no_op(self, session: Session, tmp_path: Path) -> None:
        report = import_sponsor_csv(session, SOURCE_USCIS, _write(tmp_path, "empty.csv", ""))
        assert report.employers == 0


# -- verdicts -----------------------------------------------------------------


class TestVerdicts:
    def test_an_employer_in_the_register_is_verified(
        self, session: Session, tmp_path: Path
    ) -> None:
        import_sponsor_csv(session, SOURCE_USCIS, _write(tmp_path, "us.csv", USCIS_CSV))
        verdict = lookup_company(session, "ACME AI, Inc.")
        assert verdict.status == SPONSOR_VERIFIED
        assert verdict.verified is True
        assert verdict.year == 2024
        assert verdict.approvals == 75
        assert "USCIS H-1B Employer Data Hub" in verdict.note
        assert "FY2024" in verdict.note

    def test_an_employer_not_in_the_register_says_so_about_the_register(
        self, session: Session, tmp_path: Path
    ) -> None:
        import_sponsor_csv(session, SOURCE_USCIS, _write(tmp_path, "us.csv", USCIS_CSV))
        verdict = lookup_company(session, "Some Tiny Startup")
        assert verdict.status == SPONSOR_NOT_FOUND
        assert verdict.verified is False
        # The wording rule: the note is about our data, never about the company.
        assert "No entry found in the imported sponsorship registers" in verdict.note
        assert "does not sponsor" not in verdict.note.lower()
        assert "not a sponsor" not in verdict.note.lower()

    def test_an_empty_register_is_no_data_not_not_found(self, session: Session) -> None:
        verdict = lookup_company(session, "Anything Ltd")
        assert verdict.status == SPONSOR_NO_DATA
        assert verdict.note is None

    def test_the_lookup_is_exact_not_fuzzy(self, session: Session, tmp_path: Path) -> None:
        """A near-miss must not become a false 'verified'."""
        import_sponsor_csv(session, SOURCE_USCIS, _write(tmp_path, "us.csv", USCIS_CSV))
        assert lookup_company(session, "Acme AI Systems").status == SPONSOR_NOT_FOUND

    def test_the_batch_lookup_keys_on_the_input_string(
        self, session: Session, tmp_path: Path
    ) -> None:
        import_sponsor_csv(session, SOURCE_USCIS, _write(tmp_path, "us.csv", USCIS_CSV))
        verdicts = lookup_companies(session, ["ACME AI INC", "Nope Inc", "Agentic Labs LLC"])
        assert verdicts["ACME AI INC"].status == SPONSOR_VERIFIED
        assert verdicts["Nope Inc"].status == SPONSOR_NOT_FOUND
        assert verdicts["Agentic Labs LLC"].status == SPONSOR_VERIFIED

    def test_both_registers_can_confirm_the_same_employer(
        self, session: Session, tmp_path: Path
    ) -> None:
        import_sponsor_csv(session, SOURCE_USCIS, _write(tmp_path, "us.csv", USCIS_CSV))
        import_sponsor_csv(session, SOURCE_UK, _write(tmp_path, "uk.csv", UK_CSV))
        verdict = lookup_company(session, "Agentic Labs")
        assert verdict.status == SPONSOR_VERIFIED
        assert set(verdict.sources) == {SOURCE_UK, SOURCE_USCIS}
        # The USCIS row carries counts, so it is the one reported.
        assert "USCIS" in verdict.note


# -- the enrichment changes no score -----------------------------------------


class TestEnrichmentLeavesScoringAlone:
    def test_attaching_a_verdict_does_not_touch_a_single_score(
        self, session: Session, tmp_path: Path
    ) -> None:
        from src.matching.contracts import JobMatchResult
        from src.matching.sponsors import attach_sponsor_status

        import_sponsor_csv(session, SOURCE_USCIS, _write(tmp_path, "us.csv", USCIS_CSV))

        match = JobMatchResult(
            overall_score=71.5,
            semantic_score=60.0,
            skill_score=80.0,
            experience_score=70.0,
            seniority_score=65.0,
            location_score=90.0,
            preference_score=75.0,
            role_score=55.0,
            evidence_coverage=88.0,
        )
        before = match.model_dump()

        attach_sponsor_status(session, [match], ["ACME AI INC"])

        assert match.sponsor_status == SPONSOR_VERIFIED
        assert match.sponsor_note and "USCIS" in match.sponsor_note
        after = match.model_dump()
        for field, value in before.items():
            if field in ("sponsor_status", "sponsor_note"):
                continue
            assert after[field] == value, f"{field} changed"

    def test_no_register_means_no_data_on_every_match(self, session: Session) -> None:
        from src.matching.contracts import JobMatchResult
        from src.matching.sponsors import attach_sponsor_status

        match = JobMatchResult(
            overall_score=50.0,
            semantic_score=0.0,
            skill_score=0.0,
            experience_score=0.0,
            seniority_score=0.0,
            location_score=0.0,
            preference_score=0.0,
        )
        attach_sponsor_status(session, [match], ["Acme"])
        assert match.sponsor_status == SPONSOR_NO_DATA
        assert match.sponsor_note is None
