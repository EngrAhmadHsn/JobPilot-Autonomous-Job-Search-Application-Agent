"""Edit the tailored content **into** the uploaded résumé (WS-31).

**The problem.** ``render_tailored_docx`` (``src/resume/render.py``) throws the
candidate's document away: it opens a new ``Document()`` and writes the content
out with the project's own idea of a résumé — ``Title`` for the name,
``Heading 1`` for sections, ``List Bullet`` for bullets, a fixed section order.
Whatever the candidate actually formatted is gone from the deliverable.

**This module edits instead.** The candidate's own file is opened, the wording
the tailoring changed is replaced inside the paragraphs that already carry it,
and everything else is left exactly as it was: the fonts, the section order, the
section headings, the custom sections, the margins, the header, the footer, the
logo. The document is the **shape**; the tailoring is the **content**.

Three rules make that safe:

1. **Matching is by identity, never by similarity.** A tailored experience entry
   is matched to the original entry with the same company and title — a match the
   factuality validator already guarantees exists. A bullet is matched to the
   *n*-th bullet of its entry. No fuzzy matching, no diffing, no "closest
   paragraph": a wrong match here edits the wrong sentence of a real résumé.
2. **A paragraph that cannot be edited safely is not edited.** A paragraph whose
   ``text`` includes content outside its runs (a hyperlink, a field, a content
   control) is skipped: ``paragraph.text`` includes hyperlink text and
   ``paragraph.runs`` does not, so editing one would silently delete the link.
   Tables are skipped for the same reason — the parser never read them, so the
   editor cannot know what is in them.
3. **Everything else is reported.** ``RenderReport`` counts the edits, the
   appends and the removals, and names what was skipped and why. A whole-document
   rewrite happens only when the original genuinely cannot be edited, and the
   report says which of those happened.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.core.text import normalize
from src.resume.parser import (
    _SECTION_HEADINGS,
    _is_bullet,
    _normalize_heading,
)
from src.resume.profile import CandidateProfile
from src.resume.render import render_tailored_docx, tailored_docx_path
from src.resume.tailor import TailoredResume

logger = logging.getLogger(__name__)

__all__ = [
    "MODE_IN_PLACE",
    "MODE_REGENERATED",
    "RenderReport",
    "deliver_tailored_resume",
    "edit_docx_in_place",
    "edit_text_in_place",
]

#: The uploaded file was edited, so its formatting survived.
MODE_IN_PLACE = "in_place"
#: The uploaded file could not be used; a fresh document was generated.
MODE_REGENERATED = "regenerated"

#: What a "section" is, as far as the walk is concerned.
_KIND_HEADING = "heading"
_KIND_BULLET = "bullet"
_KIND_BODY = "body"
#: A blank paragraph (a spacer between entries). It carries no text to match and
#: must never be mistaken for an entry header — the parser drops blank lines
#: before it reads, and so does this walk.
_KIND_BLANK = "blank"

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class RenderReport(BaseModel):
    """What producing the deliverable did (WS-31).

    ``mode`` is the load-bearing field: ``in_place`` means the candidate's own
    document was edited and its formatting survived; ``regenerated`` means it
    could not be used and a fresh document was written instead. The counts let
    the console say what changed, and ``skipped``/``notes`` say what could not
    be done — so a rewrite is never presented as an edit.
    """

    mode: str = MODE_REGENERATED
    source_format: str = "none"
    edits: int = 0
    appended: int = 0
    removed: int = 0
    skipped: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def in_place(self) -> bool:
        """True when the uploaded document itself was edited."""
        return self.mode == MODE_IN_PLACE

    def note(self, message: str) -> None:
        """Record something the candidate should know (deduplicated)."""
        if message not in self.notes:
            self.notes.append(message)

    def skip(self, message: str) -> None:
        """Record something that could not be done, and why (deduplicated)."""
        if message not in self.skipped:
            self.skipped.append(message)


# -- the document's structure -------------------------------------------------


class _Para:
    """One paragraph of the source document, with the role it plays."""

    __slots__ = ("index", "kind", "section", "style_name", "text")

    def __init__(
        self,
        index: int,
        text: str,
        kind: str,
        section: str | None,
        style_name: str | None,
    ) -> None:
        self.index = index
        self.text = text
        self.kind = kind
        self.section = section
        self.style_name = style_name


def _walk_paragraphs(paragraphs: list) -> list[_Para]:
    """Classify every paragraph in document order.

    The classification uses the **parser's own** vocabulary — ``_SECTION_HEADINGS``
    and ``_is_bullet`` — on purpose: the profile this edit is applied against was
    produced by that parser from this document, so the two agree by construction
    rather than by a second set of rules that could drift.
    """
    out: list[_Para] = []
    section: str | None = None
    for index, paragraph in enumerate(paragraphs):
        text = paragraph.text.strip()
        style_name = paragraph.style.name if paragraph.style else None
        if not text:
            out.append(_Para(index, "", _KIND_BLANK, section, style_name))
            continue
        heading = _SECTION_HEADINGS.get(_normalize_heading(text))
        if heading and not _is_bullet(text, style_name):
            section = heading
            out.append(_Para(index, text, _KIND_HEADING, heading, style_name))
            continue
        kind = _KIND_BULLET if _is_bullet(text, style_name) else _KIND_BODY
        out.append(_Para(index, text, kind, section, style_name))
    return out


def _is_editable(paragraph) -> bool:
    """Whether replacing this paragraph's text would lose something.

    ``paragraph.text`` concatenates the paragraph's own runs **and its
    hyperlinks**; ``paragraph.runs`` is only the runs. When the two disagree,
    editing the runs would delete the hyperlink's visible text, so the paragraph
    is left alone. The check is a comparison, not a guess.
    """
    runs_text = "".join(run.text for run in paragraph.runs)
    return runs_text.strip() == paragraph.text.strip()


def _replace_text(paragraph, new_text: str) -> None:
    """Put *new_text* into *paragraph*, keeping its first run's formatting.

    The first run keeps its font, size, colour and emphasis, and the remaining
    runs are emptied — so the paragraph stays exactly one paragraph with exactly
    the formatting the candidate chose for its opening. A paragraph whose
    original mixed bold and plain text therefore comes back uniform; that is
    stated in the report rather than guessed at with a run-splitting heuristic
    (a wrong guess corrupts the wording's meaning).
    """
    runs = paragraph.runs
    if not runs:  # pragma: no cover - a text-bearing paragraph has a run
        paragraph.text = new_text
        return
    runs[0].text = new_text
    for run in runs[1:]:
        run.text = ""


def _clear_text(paragraph) -> None:
    """Empty a paragraph's text, keeping the paragraph itself.

    The paragraph object is kept (rather than deleted) so the document's
    spacing and following paragraphs are undisturbed — deleting a paragraph
    from a DOCX re-flows the ones around it in ways the candidate did not ask
    for.
    """
    for run in paragraph.runs:
        run.text = ""


def _entry_key(title: str, company: str) -> tuple[str, str]:
    """The identity of an experience entry, normalized on both sides."""
    return (normalize(title or ""), normalize(company or ""))


def _entry_spans(paras: list[_Para]) -> list[tuple[_Para, list[_Para]]]:
    """The experience entries of the document, as (header, bullets) pairs.

    The header is the non-bullet line that opens the entry; the bullets are the
    bullet paragraphs that follow it, up to the next header. This mirrors how
    the parser reads the section (``_parse_experience``), so the *n*-th bullet
    here is the *n*-th bullet of the profile entry the parser produced.
    """
    spans: list[tuple[_Para, list[_Para]]] = []
    current: list[_Para] | None = None
    for para in paras:
        if para.section != "experience" or para.kind == _KIND_HEADING:
            continue
        if para.kind == _KIND_BLANK:
            # A blank spacer between entries. Skipped, exactly as the parser
            # skips it — treating it as a header would open a phantom entry and
            # misalign every bullet after it.
            continue
        if para.kind == _KIND_BULLET:
            if current is not None:
                current[1].append(para)
            continue
        # A body line opens a new entry.
        current = [para, []]
        spans.append((para, current[1]))
    return spans


def _split_header_parts(text: str) -> list[str]:
    """A header line's parts, split the way the parser splits it."""
    return [p.strip() for p in re.split(r"\t|\||—|–", text) if p.strip()]


# -- the editor ---------------------------------------------------------------


class _Editor:
    """The state one in-place edit accumulates."""

    def __init__(self, source_format: str) -> None:
        self.report = RenderReport(mode=MODE_IN_PLACE, source_format=source_format)
        self.found_summary = False

    def note(self, message: str) -> None:
        if message not in self.report.notes:
            self.report.notes.append(message)

    def skip(self, message: str) -> None:
        if message not in self.report.skipped:
            self.report.skipped.append(message)


def _apply_experience(
    editor: _Editor,
    document: Any,
    paragraphs: list,
    paras: list[_Para],
    tailored: TailoredResume,
) -> None:
    """Replace each tailored entry's bullets inside the document's own entry."""
    spans = _entry_spans(paras)
    by_key: dict[tuple[str, str], tuple[_Para, list[_Para]]] = {}
    for header, bullets in spans:
        parts = _split_header_parts(header.text)
        title = parts[0] if parts else ""
        company = parts[1] if len(parts) > 1 else ""
        by_key[_entry_key(title, company)] = (header, bullets)

    unmatched: list[str] = []
    for entry in tailored.experience:
        key = _entry_key(entry.title, entry.company)
        span = by_key.get(key)
        if span is None:
            # The factuality validator guarantees the company and title exist
            # in the profile; a miss here means the document's own formatting
            # defeated the header split (an exotic separator, say). Reported,
            # never forced onto an unrelated entry.
            unmatched.append(f"{entry.title} at {entry.company}".strip())
            continue
        _header, bullets = span
        _replace_bullets(editor, document, paragraphs, bullets, entry.bullets, entry.company)

    if unmatched:
        editor.skip(
            "Could not place the tailored bullets for: "
            + "; ".join(unmatched)
            + " (their section headers did not read as an entry)"
        )


def _replace_bullets(
    editor: _Editor,
    document: Any,
    paragraphs: list,
    bullets: list[_Para],
    new_bullets: list[str],
    where: str,
) -> None:
    """Write *new_bullets* over *bullets*, appending or clearing as needed."""
    editable = [para for para in bullets if _is_editable(paragraphs[para.index])]
    if len(editable) != len(bullets):
        editor.skip(
            f"{len(bullets) - len(editable)} bullet(s) under {where} carry a "
            "hyperlink or a field and were left untouched"
        )

    for para, text in zip(editable, new_bullets, strict=False):
        paragraph = paragraphs[para.index]
        if len(paragraph.runs) > 1:
            editor.note("A bullet that mixed several text styles was rewritten in its first style")
        _replace_text(paragraph, text)
        editor.report.edits += 1

    # A tailored entry with fewer bullets than the original: empty the rest.
    # Leaving them would ship claims the tailoring deliberately dropped.
    for para in editable[len(new_bullets) :]:
        _clear_text(paragraphs[para.index])
        editor.report.removed += 1

    # More tailored bullets than the original: append the extras, copying the
    # last bullet's own paragraph style so the document's look survives.
    extra = new_bullets[len(editable) :]
    if extra and bullets:
        style_name = bullets[-1].style_name
        anchor = paragraphs[bullets[-1].index]
        for text in extra:
            _append_paragraph_after(document, anchor, text, style_name)
            editor.report.appended += 1
        editor.note(
            f"{len(extra)} bullet(s) for {where} had no original paragraph and were appended"
        )


def _append_paragraph_after(document: Any, anchor: Any, text: str, style_name: str | None) -> None:
    """Add a paragraph after *anchor*, copying its style.

    python-docx has no insert-after, so the new paragraph is appended at the end
    of the document and then moved with the underlying XML — ``addnext`` puts it
    exactly after the anchor, which keeps it inside the section it belongs to.
    The document is passed explicitly because ``paragraph._parent`` is the body,
    not the document, and ``add_paragraph``/``styles`` live on the document.
    """
    new = document.add_paragraph(text)
    if style_name:
        try:
            new.style = document.styles[style_name]
        except KeyError:  # pragma: no cover - a style that vanished
            pass
    anchor._p.addnext(new._p)


def _apply_summary(
    editor: _Editor,
    document: Any,
    paragraphs: list,
    paras: list[_Para],
    tailored: TailoredResume,
) -> None:
    """Replace the document's own summary paragraph with the tailored one."""
    summary_paras = [
        para
        for para in paras
        if para.section == "summary" and para.kind != _KIND_HEADING and para.text
    ]
    if not summary_paras:
        # No summary heading: insert one after the header block, so the
        # tailored summary is not silently dropped.
        _insert_summary(editor, document, paragraphs, paras, tailored)
        return
    first = summary_paras[0]
    if not _is_editable(paragraphs[first.index]):
        editor.skip("The summary paragraph carries a hyperlink or a field and was left untouched")
        return
    editor.found_summary = True
    _replace_text(paragraphs[first.index], tailored.summary.strip())
    editor.report.edits += 1


def _insert_summary(
    editor: _Editor,
    document: Any,
    paragraphs: list,
    paras: list[_Para],
    tailored: TailoredResume,
) -> None:
    """Add the tailored summary when the document has no summary section."""
    from src.resume.render import HEADING_SUMMARY

    if not tailored.summary.strip():
        return
    # The header block: the body paragraphs before the first heading.
    header_paras = [p for p in paras if p.kind != _KIND_HEADING and p.text]
    anchor_index = header_paras[-1].index if header_paras else None
    if anchor_index is None:
        editor.skip("The document has no header block to insert a summary into")
        return
    anchor = paragraphs[anchor_index]
    heading = document.add_paragraph(HEADING_SUMMARY, style="Heading 1")
    anchor._p.addnext(heading._p)
    # ``addnext`` puts the heading first; the summary paragraph follows it.
    body = document.add_paragraph(tailored.summary.strip())
    heading._p.addnext(body._p)
    editor.report.appended += 2
    editor.note("The résumé had no summary section, so a summary was added under its own heading")


def _apply_skills(
    editor: _Editor, paragraphs: list, paras: list[_Para], tailored: TailoredResume
) -> None:
    """Filter the document's own skills lines to the tailored selection.

    The document's skills lines are the shape (``Category: a, b, c``); the
    tailored selection says which of those items survive. An item the candidate
    kept is never added, and the category lines the document already had are
    never rewritten into a different format.
    """
    selected = {normalize(skill) for skill in tailored.highlighted_skills}
    if not selected:
        return
    skill_paras = [
        para
        for para in paras
        if para.section == "skills" and para.kind != _KIND_HEADING and para.text
    ]
    if not skill_paras:
        editor.skip(
            "The résumé has no skills section, so the tailored skills were not written into it"
        )
        return

    kept_any = False
    for para in skill_paras:
        paragraph = paragraphs[para.index]
        if not _is_editable(paragraph):
            editor.skip("A skills line carries a hyperlink or a field and was left untouched")
            continue
        text = para.text
        if ":" in text:
            category, _, items = text.partition(":")
            parsed = [item.strip() for item in items.split(",") if item.strip()]
        else:
            category, parsed = "", [item.strip() for item in text.split(",") if item.strip()]
        kept = [item for item in parsed if normalize(item) in selected]
        if not kept:
            # Every skill on this line was dropped from the tailoring. The line
            # stays (its category may be referenced elsewhere) but is emptied.
            _clear_text(paragraph)
            editor.report.removed += 1
            continue
        kept_any = True
        rebuilt = f"{category.strip()}: {', '.join(kept)}" if category.strip() else ", ".join(kept)
        _replace_text(paragraph, rebuilt)
        editor.report.edits += 1

    if not kept_any:
        editor.note(
            "None of the résumé's own skills lines matched the tailored skills, "
            "so the skills section was left as the candidate wrote it"
        )


# -- the two formats ----------------------------------------------------------


def edit_docx_in_place(
    tailored: TailoredResume,
    profile: CandidateProfile,
    source_path: Path,
    out_path: Path,
) -> RenderReport:
    """Edit a ``.docx`` résumé in place and return what happened (WS-31).

    The source file is **never written to**: a new document is opened from it and
    saved to *out_path*.
    """
    from docx import Document

    document = Document(str(source_path))
    editor = _Editor(source_format=".docx")
    paragraphs = list(document.paragraphs)
    paras = _walk_paragraphs(paragraphs)

    if document.tables:
        editor.skip(
            f"{len(document.tables)} table(s) were left untouched; text inside a "
            "table is not edited in place"
        )

    _apply_summary(editor, document, paragraphs, paras, tailored)
    _apply_skills(editor, paragraphs, paras, tailored)
    _apply_experience(editor, document, paragraphs, paras, tailored)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out_path))
    logger.info(
        "Tailored resume edited in place",
        extra={
            "edits": editor.report.edits,
            "appended": editor.report.appended,
            "removed": editor.report.removed,
        },
    )
    return editor.report


def _line_kind(line: str) -> str:
    """The role a plain-text line plays, using the parser's own rule."""
    text = line.strip()
    if not text:
        return _KIND_BLANK
    if _SECTION_HEADINGS.get(_normalize_heading(text)):
        return _KIND_HEADING
    return _KIND_BULLET if _is_bullet(text, None) else _KIND_BODY


def _bullet_marker(line: str) -> str:
    """The marker a text bullet starts with, so an edit keeps it."""
    match = re.match(r"^(\s*[-•·]\s*)", line)
    return match.group(1) if match else re.match(r"^(\s*)", line).group(1)


def edit_text_in_place(
    tailored: TailoredResume,
    profile: CandidateProfile,
    source_path: Path,
    out_path: Path,
) -> RenderReport:
    """Edit a ``.txt`` / ``.md`` résumé in place and return what happened (WS-31).

    A plain-text résumé is edited line by line: blank lines, separators, markers
    and any section the tailoring did not change all survive verbatim. The
    candidate's format for a text file **is** its line structure, so keeping it
    is the whole point — including its line-ending convention, which is read
    and written with ``newline=""`` so Windows cannot rewrite a file that
    arrived with LF endings.
    """
    source_path = Path(source_path)
    # Read untranslated: universal-newline translation would hide whether the
    # file used LF or CRLF, and the answer has to survive the round trip.
    with source_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        raw = handle.read()
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    editor = _Editor(source_format=source_path.suffix.lower() or ".txt")

    # (start, end_inclusive, section) per section, in document order.
    sections: list[tuple[int, int, str]] = []
    current: str | None = None
    start = 0
    for index, line in enumerate(lines):
        if _line_kind(line) == _KIND_HEADING:
            if current is not None:
                sections.append((start, index - 1, current))
            current = _SECTION_HEADINGS[_normalize_heading(line.strip())]
            start = index + 1
    if current is not None:
        sections.append((start, len(lines) - 1, current))

    edits: list[tuple[int, str]] = []

    for start, end, section in sections:
        block = lines[start : end + 1]
        if section == "summary":
            _edit_text_summary(editor, block, start, tailored, edits)
        elif section == "skills":
            _edit_text_skills(editor, block, start, tailored, edits)
        elif section == "experience":
            _edit_text_experience(editor, block, start, tailored, edits)

    for index, text in edits:
        lines[index] = text

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # The line ending is part of the candidate's format: a file written with
    # LF comes back with LF even on Windows, where ``write_text`` would
    # otherwise translate every newline to CRLF. ``newline=""`` disables that.
    ending = newline if raw.endswith(("\n", "\r")) or not raw else ""
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(newline.join(lines) + ending)
    logger.info("Tailored resume edited in place (text)", extra={"edits": editor.report.edits})
    return editor.report


def _edit_text_summary(
    editor: _Editor,
    block: list[str],
    offset: int,
    tailored: TailoredResume,
    edits: list[tuple[int, str]],
) -> None:
    """Replace the summary's text lines with the tailored summary."""
    body = [i for i, line in enumerate(block) if line.strip()]
    if not body:
        return
    first = body[0]
    edits.append((offset + first, tailored.summary.strip()))
    editor.report.edits += 1
    # Any continuation lines of the original summary are folded into the
    # replacement above, so they are emptied rather than left as stale text.
    for extra in body[1:]:
        edits.append((offset + extra, ""))
        editor.report.removed += 1


def _edit_text_skills(
    editor: _Editor,
    block: list[str],
    offset: int,
    tailored: TailoredResume,
    edits: list[tuple[int, str]],
) -> None:
    """Filter the text skills lines to the tailored selection."""
    selected = {normalize(skill) for skill in tailored.highlighted_skills}
    if not selected:
        return
    for i, line in enumerate(block):
        if not line.strip() or _line_kind(line) == _KIND_HEADING:
            continue
        if ":" in line:
            category, _, items = line.partition(":")
            parsed = [item.strip() for item in items.split(",") if item.strip()]
        else:
            category, parsed = "", [item.strip() for item in line.split(",") if item.strip()]
        kept = [item for item in parsed if normalize(item) in selected]
        if not kept:
            edits.append((offset + i, ""))
            editor.report.removed += 1
            continue
        rebuilt = f"{category.strip()}: {', '.join(kept)}" if category.strip() else ", ".join(kept)
        edits.append((offset + i, rebuilt))
        editor.report.edits += 1


def _edit_text_experience(
    editor: _Editor,
    block: list[str],
    offset: int,
    tailored: TailoredResume,
    edits: list[tuple[int, str]],
) -> None:
    """Replace each tailored entry's bullets on the original bullet lines."""
    entries: list[tuple[str, list[int]]] = []  # header line text, bullet indices
    for i, line in enumerate(block):
        if _line_kind(line) in (_KIND_HEADING, _KIND_BLANK):
            continue
        if _line_kind(line) == _KIND_BULLET:
            if entries:
                entries[-1][1].append(i)
            continue
        entries.append((line.strip(), []))

    by_key: dict[tuple[str, str], list[int]] = {}
    for header, bullet_idx in entries:
        parts = _split_header_parts(header)
        title = parts[0] if parts else ""
        company = parts[1] if len(parts) > 1 else ""
        by_key[_entry_key(title, company)] = bullet_idx

    unmatched: list[str] = []
    for entry in tailored.experience:
        bullet_idx = by_key.get(_entry_key(entry.title, entry.company))
        if bullet_idx is None:
            unmatched.append(f"{entry.title} at {entry.company}".strip())
            continue
        for i, text in zip(bullet_idx, entry.bullets, strict=False):
            marker = _bullet_marker(block[i])
            edits.append((offset + i, f"{marker}{text}"))
            editor.report.edits += 1
        for i in bullet_idx[len(entry.bullets) :]:
            edits.append((offset + i, ""))
            editor.report.removed += 1
        extra = entry.bullets[len(bullet_idx) :]
        if extra:
            # Append after the last original bullet line. The edits list is
            # applied by index, so an append is recorded against the last
            # bullet's own line (joined) rather than a new one — a text file's
            # line count stays as the candidate wrote it.
            last = bullet_idx[-1] if bullet_idx else None
            if last is not None:
                joined = block[last].strip() + "\n" + "\n".join(f"- {text}" for text in extra)
                edits.append((offset + last, joined))
                editor.report.appended += len(extra)
                editor.note(
                    f"{len(extra)} bullet(s) for {entry.company or 'an entry'} had "
                    "no original line and were appended"
                )

    if unmatched:
        editor.skip(
            "Could not place the tailored bullets for: "
            + "; ".join(unmatched)
            + " (their section headers did not read as an entry)"
        )


# -- the only entry point the pipeline calls ----------------------------------


def deliver_tailored_resume(
    tailored: TailoredResume,
    profile: CandidateProfile,
    *,
    upload_path: str | Path | None,
    out_dir: Path,
    profile_id: str,
    job_id: str,
) -> tuple[Path, RenderReport]:
    """Produce the deliverable, editing the candidate's own file when possible.

    This is the one function the pipeline calls. It tries the in-place editor
    first and falls back to the from-scratch renderer, **reporting** which
    happened and why:

    - the upload is missing → nothing to edit;
    - the file cannot be opened → nothing to trust;
    - an unsupported extension → no editor for it.

    In each case the delivered file is a correctly rendered résumé — the fallback
    is not a degraded mode, it is the WS-05 renderer — but the report says
    ``regenerated``, so a rewrite is never presented to the candidate as an edit
    of their own document.

    Args:
        tailored: The validated tailored content.
        profile: The candidate profile the content came from.
        upload_path: The résumé the profile was parsed from, if it is still there.
        out_dir: The directory the deliverable is written to.
        profile_id, job_id: Used for the file name.

    Returns:
        The written path and the report describing how it was produced.
    """
    source = Path(upload_path) if upload_path else None
    suffix = source.suffix.lower() if source is not None else ""
    target = tailored_docx_path(profile_id, job_id, out_dir)

    if source is None or not source.is_file():
        report = RenderReport(mode=MODE_REGENERATED, source_format="none")
        report.note(
            "The uploaded résumé is not available, so a freshly formatted "
            "document was generated instead of editing yours"
        )
        _render_new(tailored, profile, target)
        return target, report

    # The deliverable keeps the candidate's format: a text résumé comes back as
    # text, which is what "edit in place" means for that file.
    if suffix in (".txt", ".md"):
        target = target.with_suffix(suffix)
        try:
            report = edit_text_in_place(tailored, profile, source, target)
        except Exception as exc:  # noqa: BLE001 - an uneditable file is reported
            logger.warning("In-place text edit failed: %s", exc)
            report = RenderReport(mode=MODE_REGENERATED, source_format=suffix)
            report.note(
                "Your résumé could not be edited in place, so a freshly "
                "formatted document was generated instead"
            )
            report.skipped.append(f"the original file could not be edited: {type(exc).__name__}")
            _render_new(tailored, profile, target)
        return target, report

    if suffix == ".docx":
        try:
            report = edit_docx_in_place(tailored, profile, source, target)
        except Exception as exc:  # noqa: BLE001 - an uneditable file is reported
            logger.warning("In-place DOCX edit failed: %s", exc)
            report = RenderReport(mode=MODE_REGENERATED, source_format=suffix)
            report.note(
                "Your résumé could not be edited in place, so a freshly "
                "formatted document was generated instead"
            )
            report.skipped.append(f"the original file could not be edited: {type(exc).__name__}")
            _render_new(tailored, profile, target)
        return target, report

    report = RenderReport(mode=MODE_REGENERATED, source_format=suffix or "none")
    report.note(
        f"A {suffix or 'unknown'}-format résumé cannot be edited in place, so a "
        "freshly formatted document was generated instead"
    )
    _render_new(tailored, profile, target)
    return target, report


def _render_new(tailored: TailoredResume, profile: CandidateProfile, target: Path) -> None:
    """The WS-05 renderer, used as the reported fallback."""
    render_tailored_docx(tailored, profile, target)
