"""WS-31 tests: the tailored résumé is edited into the candidate's own file.

The promise under test is **format preservation**: a real ``.docx`` with a
distinctive font, its own section order and extra sections comes back with all
of them intact, and only the wording the tailoring changed is different. The
plain-text path gets the same treatment line by line.

What is also pinned, because it is where this could go wrong:

* a paragraph carrying a hyperlink is **not** edited (editing its runs would
  delete the link's visible text);
* a table is left alone;
* a missing or unreadable upload regenerates the document **and says so** — a
  rewrite is never presented as an edit;
* fewer/more tailored bullets than the original are handled and counted.
"""

from __future__ import annotations

from pathlib import Path

from src.resume.edit import (
    MODE_IN_PLACE,
    MODE_REGENERATED,
    RenderReport,
    deliver_tailored_resume,
    edit_docx_in_place,
    edit_text_in_place,
)
from src.resume.parser import parse_resume
from src.resume.profile import (
    CandidateProfile,
    ExperienceEntry,
    PersonalInformation,
    ProjectEntry,
)
from src.resume.tailor import TailoredExperience, TailoredResume

DISTINCTIVE_FONT = "Georgia"
DISTINCTIVE_SIZE = 13


def _profile() -> CandidateProfile:
    return CandidateProfile(
        personal_information=PersonalInformation(
            name="Ahmad Hassan",
            title="AI Engineer",
            email="ahmad@example.com",
            location="Berlin, Germany",
        ),
        summary="AI engineer building agent systems.",
        skills=["Python", "LangGraph", "FastAPI", "Docker"],
        skill_categories={
            "Languages": ["Python"],
            "Frameworks": ["LangGraph", "FastAPI", "Docker"],
        },
        experience=[
            ExperienceEntry(title="AI Engineer", company="Agentic Labs", dates="2020-2023"),
        ],
        projects=[ProjectEntry(name="Autonomous Job Agent", bullets=["Agent system"])],
    )


def _tailored(*, bullets: list[str] | None = None, skills: list[str] | None = None):
    return TailoredResume(
        summary="AI engineer with agent-platform depth in Python and LangGraph.",
        highlighted_skills=skills if skills is not None else ["Python", "LangGraph"],
        experience=[
            TailoredExperience(
                company="Agentic Labs",
                title="AI Engineer",
                bullets=(
                    bullets
                    if bullets is not None
                    else [
                        "Built agent pipelines with LangGraph",
                        "Shipped REST APIs with FastAPI",
                    ]
                ),
            )
        ],
        projects=[],
        cover_letter="Cover letter.",
    )


def _build_source_docx(path: Path) -> Path:
    """A résumé with a distinctive look the editor must preserve.

    Deliberately unlike the renderer's own output: its own section order
    (Skills before Summary), a custom "Volunteering" section, the Georgia font
    at 13pt on every run, and a separator line the renderer never writes.
    """
    from docx import Document
    from docx.shared import Pt

    document = Document()
    style = document.styles["Normal"]
    style.font.name = DISTINCTIVE_FONT
    style.font.size = Pt(DISTINCTIVE_SIZE)

    def add(text: str, *, bold: bool = False, bullet: bool = False, heading: bool = False):
        paragraph = document.add_paragraph(text, style="List Bullet" if bullet else None)
        for run in paragraph.runs:
            run.font.name = DISTINCTIVE_FONT
            run.font.size = Pt(DISTINCTIVE_SIZE)
            run.bold = bold
        if heading:
            # Marked by style name alone: the parser recognises headings by
            # their *text*, so any style at all works here.
            paragraph.style = document.styles["Heading 2"]
        return paragraph

    add("AHMAD HASSAN", bold=True)
    add("AI Engineer | ahmad@example.com | Berlin, Germany")
    add("—— separators are formatting too ——")
    # Skills before Summary: the renderer's own order is the opposite.
    add("Technical Skills", heading=True)
    add("Languages: Python, Go")
    add("Frameworks: LangGraph, FastAPI, Docker")
    add("Professional Summary", heading=True)
    add("AI engineer building agent systems.")
    add("Experience", heading=True)
    add("AI Engineer | Agentic Labs | 2020-2023")
    add("Built agent pipelines", bullet=True)
    add("Maintained legacy services", bullet=True)
    add("Education", heading=True)
    add("BSc Computer Science", heading=False)
    add("Technical University of Berlin")
    add("Volunteering", heading=True)
    add("Taught weekend coding classes")
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path


# -- the docx editor ----------------------------------------------------------


class TestDocxInPlace:
    def test_the_tailored_wording_lands_in_the_document(self, tmp_path: Path) -> None:
        source = _build_source_docx(tmp_path / "in.docx")
        out = tmp_path / "out.docx"
        report = edit_docx_in_place(_tailored(), _profile(), source, out)

        assert report.mode == MODE_IN_PLACE
        assert report.source_format == ".docx"
        assert report.edits >= 3  # summary + 2 bullets

        from docx import Document

        text = "\n".join(p.text for p in Document(str(out)).paragraphs)
        assert "Built agent pipelines with LangGraph" in text
        assert "Shipped REST APIs with FastAPI" in text
        assert "AI engineer with agent-platform depth" in text
        # The originals that were replaced are gone.
        assert "Built agent pipelines\n" not in text
        assert "Maintained legacy services" not in text

    def test_the_candidates_formatting_survives(self, tmp_path: Path) -> None:
        """The whole point: fonts, sizes, section order and extra sections."""
        source = _build_source_docx(tmp_path / "in.docx")
        out = tmp_path / "out.docx"
        edit_docx_in_place(_tailored(), _profile(), source, out)

        from docx import Document

        edited = Document(str(out))
        paragraphs = [p for p in edited.paragraphs if p.text.strip()]
        texts = [p.text for p in paragraphs]

        # The section order is the document's, not the renderer's.
        assert texts.index("Technical Skills") < texts.index("Professional Summary")
        # The custom section and the separator line the renderer never writes.
        assert "Volunteering" in texts
        assert "Taught weekend coding classes" in texts
        assert any("separators are formatting too" in t for t in texts)

        # Every run kept the document's font and size.
        for paragraph in paragraphs:
            for run in paragraph.runs:
                if run.text.strip():
                    assert run.font.name == DISTINCTIVE_FONT, paragraph.text
                    assert run.font.size.pt == DISTINCTIVE_SIZE, paragraph.text

    def test_a_bullet_keeps_its_paragraph_style(self, tmp_path: Path) -> None:
        source = _build_source_docx(tmp_path / "in.docx")
        out = tmp_path / "out.docx"
        edit_docx_in_place(_tailored(), _profile(), source, out)

        from docx import Document

        edited = Document(str(out))
        rewritten = next(
            p for p in edited.paragraphs if p.text == "Built agent pipelines with LangGraph"
        )
        assert "List" in rewritten.style.name

    def test_the_skills_lines_are_filtered_to_the_tailored_selection(self, tmp_path: Path) -> None:
        source = _build_source_docx(tmp_path / "in.docx")
        out = tmp_path / "out.docx"
        # Docker and Go were in the résumé but not in the tailoring.
        edit_docx_in_place(_tailored(skills=["Python", "FastAPI"]), _profile(), source, out)

        from docx import Document

        text = "\n".join(p.text for p in Document(str(out)).paragraphs)
        assert "Languages: Python" in text
        assert "Go" not in text
        # FastAPI survives; Docker, which the tailoring dropped, does not.
        assert "Frameworks: FastAPI" in text
        assert "Docker" not in text
        # The document's own category names are the shape and stay.
        assert "Languages:" in text and "Frameworks:" in text

    def test_fewer_tailored_bullets_empties_the_leftovers(self, tmp_path: Path) -> None:
        source = _build_source_docx(tmp_path / "in.docx")
        out = tmp_path / "out.docx"
        report = edit_docx_in_place(
            _tailored(bullets=["Only one bullet now"]), _profile(), source, out
        )

        assert report.removed == 1
        from docx import Document

        text = "\n".join(p.text for p in Document(str(out)).paragraphs)
        assert "Only one bullet now" in text
        # The stale claim is not left behind.
        assert "Maintained legacy services" not in text

    def test_more_tailored_bullets_are_appended(self, tmp_path: Path) -> None:
        source = _build_source_docx(tmp_path / "in.docx")
        out = tmp_path / "out.docx"
        report = edit_docx_in_place(
            _tailored(bullets=["One", "Two", "Three"]), _profile(), source, out
        )

        assert report.appended == 1
        from docx import Document

        text = "\n".join(p.text for p in Document(str(out)).paragraphs)
        assert "Three" in text

    def test_a_hyperlink_paragraph_is_not_edited(self, tmp_path: Path) -> None:
        """Editing a paragraph with a link would delete the link's text."""
        source = _build_source_docx(tmp_path / "in.docx")

        # Give the summary paragraph a real hyperlink, so paragraph.text and
        # paragraph.runs disagree.
        import docx
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        from docx.oxml.ns import qn

        document = docx.Document(str(source))
        paragraph = next(
            p for p in document.paragraphs if p.text.startswith("AI engineer building")
        )
        part = paragraph.part
        relationship_id = part.relate_to("https://example.com", RT.HYPERLINK, is_external=True)
        hyperlink = paragraph._p.makeelement(qn("w:hyperlink"), {qn("r:id"): relationship_id})
        import copy

        for run in paragraph.runs:
            hyperlink.append(copy.deepcopy(run._r))
        paragraph._p.clear_content() if hasattr(paragraph._p, "clear_content") else None
        for child in list(paragraph._p):
            if child.tag == qn("w:r"):
                paragraph._p.remove(child)
        paragraph._p.append(hyperlink)
        document.save(str(source))

        out = tmp_path / "out.docx"
        report = edit_docx_in_place(_tailored(), _profile(), source, out)

        assert any("hyperlink" in item for item in report.skipped)
        # The linked paragraph's text is intact in the output.
        edited_text = "\n".join(p.text for p in docx.Document(str(out)).paragraphs)
        assert "AI engineer building agent systems." in edited_text

    def test_a_table_is_left_untouched(self, tmp_path: Path) -> None:
        source = _build_source_docx(tmp_path / "in.docx")
        from docx import Document

        document = Document(str(source))
        document.add_table(rows=1, cols=2)
        document.save(str(source))

        out = tmp_path / "out.docx"
        report = edit_docx_in_place(_tailored(), _profile(), source, out)

        assert any("table" in item for item in report.skipped)
        assert len(Document(str(out)).tables) == 1

    def test_the_source_file_is_never_written_to(self, tmp_path: Path) -> None:
        source = _build_source_docx(tmp_path / "in.docx")
        before = source.read_bytes()
        edit_docx_in_place(_tailored(), _profile(), source, tmp_path / "out.docx")
        assert source.read_bytes() == before

    def test_the_edited_file_still_parses(self, tmp_path: Path) -> None:
        """The deliverable must remain machine-readable, as WS-05 required."""
        source = _build_source_docx(tmp_path / "in.docx")
        out = tmp_path / "out.docx"
        edit_docx_in_place(_tailored(), _profile(), source, out)

        reparsed = parse_resume(str(out))
        assert reparsed.personal_information.name == "Ahmad Hassan"
        assert reparsed.personal_information.email == "ahmad@example.com"
        assert "Python" in reparsed.skills
        assert reparsed.experience[0].company == "Agentic Labs"
        assert any("LangGraph" in b for b in reparsed.experience[0].bullets)


# -- the text editor ----------------------------------------------------------


TEXT_RESUME = """\
AHMAD HASSAN
AI Engineer | ahmad@example.com | Berlin, Germany

Technical Skills

Languages: Python, Go
Frameworks: LangGraph, FastAPI, Docker

Professional Summary

AI engineer building agent systems.
Across several teams.

Experience

AI Engineer | Agentic Labs | 2020-2023
- Built agent pipelines
- Maintained legacy services

Education

BSc Computer Science
Technical University of Berlin
"""


class TestTextInPlace:
    def test_the_wording_is_replaced_line_by_line(self, tmp_path: Path) -> None:
        source = tmp_path / "in.txt"
        source.write_text(TEXT_RESUME, encoding="utf-8")
        out = tmp_path / "out.txt"

        report = edit_text_in_place(_tailored(), _profile(), source, out)

        assert report.mode == MODE_IN_PLACE
        assert report.source_format == ".txt"
        text = out.read_text(encoding="utf-8")
        assert "- Built agent pipelines with LangGraph" in text
        assert "- Shipped REST APIs with FastAPI" in text
        assert "Maintained legacy services" not in text
        assert "AI engineer with agent-platform depth" in text

    def test_the_shape_of_the_file_survives(self, tmp_path: Path) -> None:
        """Blank lines, the heading order and the markers are the format."""
        source = tmp_path / "in.txt"
        source.write_text(TEXT_RESUME, encoding="utf-8")
        out = tmp_path / "out.txt"
        edit_text_in_place(_tailored(), _profile(), source, out)

        text = out.read_text(encoding="utf-8")
        lines = text.splitlines()
        # The document's own section order, not the renderer's.
        assert lines.index("Technical Skills") < lines.index("Professional Summary")
        # The blank lines are still there, in the same places.
        assert lines[2] == ""
        assert lines[4] == ""
        # The rewritten **bullets** kept the "-" marker the candidate used. A
        # skills line legitimately has no marker, so only the bullet block is
        # asserted here.
        bullet_lines = [line for line in lines if line.startswith("- ")]
        assert any("LangGraph" in line for line in bullet_lines)
        assert any("FastAPI" in line for line in bullet_lines)
        assert "Languages: Python" in lines  # the skills line, unmrked on purpose
        assert text.endswith("\n")

    def test_the_skills_lines_are_filtered(self, tmp_path: Path) -> None:
        source = tmp_path / "in.txt"
        source.write_text(TEXT_RESUME, encoding="utf-8")
        out = tmp_path / "out.txt"
        edit_text_in_place(_tailored(skills=["Python", "FastAPI"]), _profile(), source, out)

        text = out.read_text(encoding="utf-8")
        assert "Languages: Python" in text
        assert "Frameworks: FastAPI" in text
        assert "Go" not in text
        assert "Docker" not in text

    def test_the_result_still_parses(self, tmp_path: Path) -> None:
        source = tmp_path / "in.txt"
        source.write_text(TEXT_RESUME, encoding="utf-8")
        out = tmp_path / "out.txt"
        edit_text_in_place(_tailored(), _profile(), source, out)

        reparsed = parse_resume(str(out))
        assert reparsed.personal_information.name == "Ahmad Hassan"
        assert "Python" in reparsed.skills
        assert reparsed.experience[0].company == "Agentic Labs"

    def test_a_file_without_a_trailing_newline_keeps_that_shape(self, tmp_path: Path) -> None:
        source = tmp_path / "in.txt"
        source.write_text(TEXT_RESUME.rstrip("\n"), encoding="utf-8")
        out = tmp_path / "out.txt"
        edit_text_in_place(_tailored(), _profile(), source, out)
        assert not out.read_text(encoding="utf-8").endswith("\n")

    def test_the_line_ending_convention_survives(self, tmp_path: Path) -> None:
        """An LF file comes back LF, even on Windows.

        ``Path.write_text`` translates every ``\\n`` to ``\\r\\n`` on Windows,
        which would silently rewrite the whole document's line endings — a real
        change to the candidate's file, made by the tool that promises not to
        change their formatting. This was found by the live verification run.
        """
        source = tmp_path / "crlf.txt"
        source.write_bytes(TEXT_RESUME.replace("\n", "\r\n").encode("utf-8"))
        out = tmp_path / "crlf_out.txt"
        edit_text_in_place(_tailored(), _profile(), source, out)
        produced = out.read_bytes()
        assert b"\r\n" in produced
        # No bare LF was introduced alongside the CRLFs.
        assert produced.replace(b"\r\n", b"").count(b"\n") == 0

        lf_source = tmp_path / "lf.txt"
        lf_source.write_bytes(TEXT_RESUME.encode("utf-8"))
        lf_out = tmp_path / "lf_out.txt"
        edit_text_in_place(_tailored(), _profile(), lf_source, lf_out)
        assert b"\r\n" not in lf_out.read_bytes()

    def test_fewer_tailored_bullets_empties_the_extras(self, tmp_path: Path) -> None:
        source = tmp_path / "in.txt"
        source.write_text(TEXT_RESUME, encoding="utf-8")
        out = tmp_path / "out.txt"
        report = edit_text_in_place(_tailored(bullets=["One bullet"]), _profile(), source, out)
        # Two removals: the leftover bullet line, and the original summary's
        # second line (the summary is replaced as one block, so its
        # continuation would otherwise still carry the old claim).
        assert report.removed == 2
        text = out.read_text(encoding="utf-8")
        assert "Maintained legacy services" not in text
        assert "Across several teams." not in text
        assert "One bullet" in text

    def test_a_multi_line_summary_is_replaced_whole(self, tmp_path: Path) -> None:
        source = tmp_path / "in.txt"
        source.write_text(TEXT_RESUME, encoding="utf-8")
        out = tmp_path / "out.txt"
        edit_text_in_place(_tailored(), _profile(), source, out)

        text = out.read_text(encoding="utf-8")
        assert "AI engineer with agent-platform depth" in text
        # The old summary's second line does not survive beside the new text.
        assert "Across several teams." not in text
        assert "AI engineer building agent systems." not in text


# -- the orchestrator ---------------------------------------------------------


class TestDeliverTailoredResume:
    def test_a_docx_upload_is_edited_in_place(self, tmp_path: Path) -> None:
        source = _build_source_docx(tmp_path / "resumes" / "prof1.docx")
        path, report = deliver_tailored_resume(
            _tailored(),
            _profile(),
            upload_path=source,
            out_dir=tmp_path / "tailored",
            profile_id="prof1",
            job_id="greenhouse:abc123",
        )
        assert report.in_place
        assert path.suffix == ".docx"
        assert path.is_file()

    def test_a_txt_upload_yields_an_edited_txt(self, tmp_path: Path) -> None:
        """A text résumé comes back as text: that IS its format."""
        source = tmp_path / "resumes" / "prof1.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(TEXT_RESUME, encoding="utf-8")
        path, report = deliver_tailored_resume(
            _tailored(),
            _profile(),
            upload_path=source,
            out_dir=tmp_path / "tailored",
            profile_id="prof1",
            job_id="greenhouse:abc123",
        )
        assert report.in_place
        assert path.suffix == ".txt"
        assert "LangGraph" in path.read_text(encoding="utf-8")

    def test_a_missing_upload_regenerates_and_says_so(self, tmp_path: Path) -> None:
        path, report = deliver_tailored_resume(
            _tailored(),
            _profile(),
            upload_path=tmp_path / "gone.docx",
            out_dir=tmp_path / "tailored",
            profile_id="prof1",
            job_id="greenhouse:abc123",
        )
        assert report.mode == MODE_REGENERATED
        assert report.source_format == "none"
        assert any("not available" in note for note in report.notes)
        assert path.suffix == ".docx"
        assert path.is_file()

    def test_no_upload_path_at_all_regenerates(self, tmp_path: Path) -> None:
        _path, report = deliver_tailored_resume(
            _tailored(),
            _profile(),
            upload_path=None,
            out_dir=tmp_path / "tailored",
            profile_id="prof1",
            job_id="greenhouse:abc123",
        )
        assert report.mode == MODE_REGENERATED
        assert report.in_place is False

    def test_an_unsupported_extension_regenerates_and_says_so(self, tmp_path: Path) -> None:
        source = tmp_path / "resumes" / "prof1.rtf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("not really rtf", encoding="utf-8")
        _path, report = deliver_tailored_resume(
            _tailored(),
            _profile(),
            upload_path=source,
            out_dir=tmp_path / "tailored",
            profile_id="prof1",
            job_id="greenhouse:abc123",
        )
        assert report.mode == MODE_REGENERATED
        assert report.source_format == ".rtf"
        assert any(".rtf" in note for note in report.notes)

    def test_a_corrupt_docx_regenerates_and_reports_the_skip(self, tmp_path: Path) -> None:
        source = tmp_path / "resumes" / "prof1.docx"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"not a zip at all")
        path, report = deliver_tailored_resume(
            _tailored(),
            _profile(),
            upload_path=source,
            out_dir=tmp_path / "tailored",
            profile_id="prof1",
            job_id="greenhouse:abc123",
        )
        assert report.mode == MODE_REGENERATED
        assert report.skipped
        # The fallback is still a valid, parseable résumé — not a failed call.
        assert parse_resume(str(path)).personal_information.name == "Ahmad Hassan"

    def test_the_report_model_defaults_are_safe(self) -> None:
        report = RenderReport()
        assert report.mode == MODE_REGENERATED
        assert report.in_place is False
        assert report.edits == 0
        assert report.skipped == []
