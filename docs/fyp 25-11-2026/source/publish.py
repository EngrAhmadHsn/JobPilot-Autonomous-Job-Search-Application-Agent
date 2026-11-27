"""Typeset the two FYP Word editions on the university originals' theme.

Each edition is built over a private copy of the corresponding university
document, so the style set, theme fonts, numbering definitions, page geometry
and cover lettering are the ones the university supplied. The build only replaces
the body: Times New Roman 12 pt justified text, 16/14/13/12 pt black headings,
11 pt italic captions, 10 pt table text with the originals' grey header fill, and
the originals' A4 margins with roman front matter and arabic body page numbers.

Usage: python source/publish.py --out <new-directory> [--only SRS|SDD]
Use refresh_word.py to populate and paginate the Word fields before distribution.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from shutil import copyfile
from tempfile import NamedTemporaryFile

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from PIL import Image

SRC = Path(__file__).resolve().parent
PACK = SRC.parent
BASELINE = "7190151"

# Page width inside the originals' margins: A4 (210 mm) less 1.5 in + 0.75 in.
BODY_W = 6.02
# Body and heading text take Times New Roman 12 pt from the originals' docDefaults,
# so no run formatting is needed for ordinary prose. Only these faces differ.
MONO = "Courier New"
BLACKLETTER = "Old English Text MT"
HEADER_FILL = "D9D9D9"  # the originals' table header shading

ABSTRACT = {
    "SRS": "A candidate needs to know which jobs fit their experience, what a tailored résumé changes, and who decides whether to send it. JARVIS ranks stored listings and explains the evidence behind a match. A candidate can compare a draft with the original, correct supported text and review questions before authorizing any executable application. The requirements distinguish acceptance of a request from proof of receipt. A local test employer supports the full submission workflow. On a real employer’s site, the candidate retains control of the final action.",
    "SDD": "JARVIS keeps job listings in a shared corpus and stores candidate documents, application answers and decisions under the account that owns them. The search service ranks stored jobs; the drafting service checks proposed wording against the résumé. When a candidate authorizes an executable application, the API records the decision and queues a run. A separate worker acts within the adapter’s permissions. The design explains how an interrupted run is recovered, why a missing confirmation calls for human review, and why the real-board pilot cannot submit on the candidate’s behalf.",
}


def load(name):
    return json.loads((SRC / name).read_text(encoding="utf-8-sig"))


def element(tag, **attrs):
    x = OxmlElement("w:" + tag)
    for key, val in attrs.items():
        x.set(qn("w:" + key), str(val))
    return x


def set_run(run, *, size=None, bold=None, italic=None, font=None):
    """Apply explicit run formatting on top of the paragraph style."""
    if font:
        run.font.name = font
        rf = run._element.get_or_add_rPr().find(qn("w:rFonts"))
        for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
            rf.set(qn("w:" + attr), font)
        for attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
            rf.attrib.pop(qn("w:" + attr), None)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    return run


def paragraph(
    d,
    text="",
    *,
    style=None,
    align=None,
    size=None,
    bold=None,
    italic=None,
    font=None,
    before=0,
    after=0,
    spacing=None,
    indent=None,
    tab=None,
):
    p = d.add_paragraph(style=style) if style else d.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    if before is not None:
        pf.space_before = Pt(before)
    if after is not None:
        pf.space_after = Pt(after)
    if spacing is not None:
        pf.line_spacing = spacing
    if indent is not None:
        pf.left_indent = Inches(indent)
    if tab is not None:
        pf.tab_stops.add_tab_stop(Inches(tab), WD_TAB_ALIGNMENT.LEFT)
    if text:
        set_run(p.add_run(text), size=size, bold=bold, italic=italic, font=font)
    return p


def field(p, code, text=""):
    p.add_run()._r.append(element("fldChar", fldCharType="begin"))
    r = p.add_run()
    i = element("instrText")
    i.set(qn("xml:space"), "preserve")
    i.text = " " + code + " "
    r._r.append(i)
    p.add_run()._r.append(element("fldChar", fldCharType="separate"))
    p.add_run(text)
    p.add_run()._r.append(element("fldChar", fldCharType="end"))


def table_rules(table):
    """Full single black grid, as every table in the university originals uses."""
    pr = table._tbl.tblPr
    mar = element("tblCellMar")
    for side, w in (("top", 30), ("bottom", 30), ("left", 90), ("right", 90)):
        mar.append(element(side, w=w, type="dxa"))
    pr.append(mar)
    borders = element("tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        borders.append(element(side, val="single", sz=4, space=0, color="auto"))
    pr.append(borders)


def grid(parent, heads, rows, ratios, *, total=BODY_W, basis=False):
    """Table text is the originals' 10 pt; a header cell is bold over grey."""
    n = len(heads)
    table = parent.add_table(rows=1, cols=n)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    widths = [Inches(total * x / sum(ratios)) for x in ratios]
    table_rules(table)
    for i, w in enumerate(widths):
        table.columns[i].width = w
    for rid, values in enumerate([heads, *rows]):
        row = table.rows[0] if rid == 0 else table.add_row()
        trpr = row._tr.get_or_add_trPr()
        trpr.append(element("cantSplit"))
        if rid == 0:
            trpr.append(element("tblHeader", val="true"))
        for ci, (cell, text, wid) in enumerate(zip(row.cells, values, widths)):
            cell.width = wid
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if rid == 0:
                cell._tc.get_or_add_tcPr().append(
                    element("shd", val="clear", fill=HEADER_FILL, color="auto")
                )
            p = cell.paragraphs[0]
            p.style = "Table Text"
            for part_no, part in enumerate(str(text).split("\n")):
                if part_no:
                    p = cell.add_paragraph(style="Table Text")
                inline(p, part, bold=rid == 0)
            if rid == 0:
                p.paragraph_format.keep_with_next = True
    # Two neighbouring tables must never touch: Word merges adjacent w:tbl
    # elements into one on save, which silently fuses a Processing step table
    # with the requirements grid that follows it. A hair-thin paragraph keeps
    # them separate without a visible gap.
    spacer = parent.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(0)
    spacer.paragraph_format.line_spacing = Pt(4)
    return table


def inline(p, text, *, bold=False, size=None):
    """Write one line, rendering `code` in 8.5 pt Courier New, as the originals do."""
    for part in re.split(r"(`[^`]+`)", text):
        if part.startswith("`") and part.endswith("`"):
            r = p.add_run(part[1:-1])
            set_run(r, font=MONO, bold=bold, size=size or 8.5)
        elif part:
            set_run(p.add_run(part), bold=bold if bold else None, size=size)


def numbering(p, num_id, ilvl=0):
    ppr = p._p.get_or_add_pPr()
    numpr = element("numPr")
    numpr.append(element("ilvl", val=ilvl))
    numpr.append(element("numId", val=num_id))
    ppr.insert_element_before(
        numpr,
        "w:suppressLineNumbers",
        "w:pBdr",
        "w:shd",
        "w:tabs",
        "w:suppressAutoHyphens",
        "w:kinsoku",
        "w:wordWrap",
        "w:overflowPunct",
        "w:topLinePunct",
        "w:autoSpaceDE",
        "w:autoSpaceDN",
        "w:bidi",
        "w:adjustRightInd",
        "w:snapToGrid",
        "w:spacing",
        "w:ind",
        "w:contextualSpacing",
        "w:mirrorIndents",
        "w:suppressOverlap",
        "w:jc",
        "w:textDirection",
        "w:textAlignment",
        "w:textboxTightWrap",
        "w:outlineLvl",
        "w:divId",
        "w:cnfStyle",
        "w:rPr",
        "w:sectPr",
        "w:pPrChange",
    )


def page_number(section, fmt, start=1):
    sect = section._sectPr
    for old in sect.findall(qn("w:pgNumType")):
        sect.remove(old)
    sect.insert_element_before(element("pgNumType", fmt=fmt, start=start), "w:cols", "w:docGrid")


def reset_references(section):
    """Drop inherited header/footer parts so each section owns its footer."""
    sect = section._sectPr
    for tag in ("w:headerReference", "w:footerReference", "w:titlePg"):
        for old in sect.findall(qn(tag)):
            sect.remove(old)


def footers(section, fmt, start, *, blank_first=False):
    reset_references(section)
    section.different_first_page_header_footer = blank_first
    if blank_first:
        first = section.first_page_footer
        first.is_linked_to_previous = False
        for p in list(first.paragraphs):
            for r in list(p.runs):
                r._r.getparent().remove(r._r)
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    field(p, "PAGE", str(start) if fmt == "decimal" else "i")
    page_number(section, fmt, start)


def cover(d, kind, meta):
    """The university cover: title, crest, metadata block, programme, lettering."""
    centre = WD_ALIGN_PARAGRAPH.CENTER
    paragraph(d, meta["project"], align=centre, size=22, bold=True, before=36, after=0, spacing=1.0)
    paragraph(d, meta["kind"], align=centre, size=16, bold=True, before=4, after=0, spacing=1.0)
    p = d.add_paragraph()
    p.alignment = centre
    p.paragraph_format.space_before = Pt(60)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    picture = p.add_run().add_picture(str(SRC / "university-crest.jpg"), width=Inches(2.28))
    picture._inline.docPr.set("descr", "University crest from the original title page")

    for index, (label, value) in enumerate(
        (
            ("Submitted By", meta["student"]),
            ("Roll No", meta["roll"]),
            ("Submitted To", meta["supervisor"]),
        )
    ):
        paragraph(
            d,
            f"{label}\t{value}",
            align=WD_ALIGN_PARAGRAPH.LEFT,
            indent=0.55,
            tab=3.35,
            before=72 if index == 0 else 0,
            after=0,
            spacing=1.0,
        )

    paragraph(
        d, meta["programme"], align=centre, size=16, bold=True, before=34, after=0, spacing=1.0
    )
    paragraph(d, meta["session"], align=centre, size=16, bold=True, before=0, after=0, spacing=1.0)
    paragraph(
        d, meta["department"], align=centre, size=17, bold=True, before=82, after=0, spacing=1.0
    )
    paragraph(
        d,
        meta["university"],
        align=centre,
        size=22,
        bold=True,
        font=BLACKLETTER,
        before=6,
        after=0,
        spacing=1.0,
    )


def front_matter(d, kind, meta):
    centre = WD_ALIGN_PARAGRAPH.CENTER

    def title(text, size=16, new_page=True, after=8):
        paragraph(
            d, text, align=centre, size=size, bold=True, before=0, after=after, spacing=1.0
        ).paragraph_format.page_break_before = new_page

    title("Revision History", new_page=True)
    history = [[h[0], h[1], h[3]] for h in meta["history"]]
    history.append(
        [
            "22 Nov 2026",
            "FYP edition",
            "Requirements and design reconciled to JARVIS revision 7190151.",
        ]
    )
    grid(d, ["Date", "Edition", "Change"], history, [0.16, 0.24, 0.60])
    paragraph(d, "", after=0)
    title("Document Approval", new_page=False, after=8)
    paragraph(
        d,
        f"The following {meta['kind']} has been accepted and approved by the following people:",
        spacing=1.5,
    )
    grid(
        d,
        ["Printed name", "Role", "Signature", "Date"],
        [[a[1], a[2], a[0], a[3]] for a in meta["approval"]],
        [0.25, 0.36, 0.24, 0.15],
    )

    title("ABSTRACT", size=20, new_page=True, after=10)
    paragraph(d, ABSTRACT[kind], spacing=1.5)

    title("Table of Contents", new_page=True, after=10)
    field(d.add_paragraph(), 'TOC \\o "1-2" \\h \\z \\u', "Contents")

    title("Table of Figures", new_page=True, after=10)
    field(d.add_paragraph(), 'TOC \\h \\z \\c "Figure"', "Figures")


class Typesetter:
    def __init__(self, d, kind, req, figs):
        self.d = d
        self.kind = kind
        self.req = req
        self.figs = figs
        self.counter = 0
        self.order = {}
        self.first = True
        self.text = ""
        self.table = []

    def ref(self, t):
        def repl(m):
            k = m.group(1)
            return str(self.order[k])

        return re.sub(r"\{fig:([\w-]+)\}", repl, t)

    def figure(self, key, photo):
        entry = self.figs[key]
        path = (PACK / "ui" if photo else PACK / "diagrams" / "png") / (key + ".png")
        with Image.open(path) as im:
            w, h = im.size
            dpi = im.info.get("dpi", (96, 96))[0]
        # HiDPI PlantUML output may carry no PNG pHYs; fit to the column but never
        # stretch a small panel beyond its natural 96-DPI size.
        max_h = 5.2 if photo else 5.6
        limit = BODY_W if photo else min(BODY_W, w / max(dpi, 1))
        width = min(limit, max_h * w / h)
        self.counter += 1
        p = self.d.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.keep_with_next = True
        image = p.add_run().add_picture(str(path), width=Inches(width))
        image._inline.docPr.set("descr", entry["alt"])
        image._inline.docPr.set("title", entry["caption"])
        image._inline.docPr.set("name", key + ".png")
        cap = self.d.add_paragraph(style="Caption")
        cap.add_run("Figure ")
        field(cap, "SEQ Figure \\* ARABIC", str(self.counter))
        cap.add_run("  " + entry["caption"].rstrip("."))
        if photo:
            note = self.d.add_paragraph()
            note.alignment = WD_ALIGN_PARAGRAPH.CENTER
            note.paragraph_format.space_before = Pt(0)
            note.paragraph_format.space_after = Pt(6)
            set_run(note.add_run(entry["provenance"]), size=10, italic=True)

    def requirements(self, g):
        rows = [
            (f"{r['id']}\n{r['status']}", r["requirement"], r["acceptance"])
            for r in self.req
            if int(r["group"]) == g
        ]
        if not rows:
            raise ValueError(f"Empty requirements group {g}")
        grid(
            self.d,
            ["ID / status", "Requirement", "Acceptance check"],
            rows,
            [0.16, 0.41, 0.43],
            basis=True,
        )

    def trace(self):
        # Each requirement keeps its own row unless an adjacent item cites the same
        # design and evidence. Evidence keys keep repeated paths off the page.
        evidence = {}
        bygroup = defaultdict(list)
        for r in self.req:
            k = (r["design"], r.get("test") or "")
            bygroup[r["group"]].append((r["id"], k))
            if k[1] and k[1] not in evidence:
                evidence[k[1]] = f"E{len(evidence) + 1:02d}"
        paragraph(
            self.d,
            "Evidence keys identify a source file, a test specification or a dated "
            "evaluation. A reference to a test does not assert that it was run for "
            "this edition.",
            size=10,
            italic=True,
        )
        rows = []
        for group, rr in bygroup.items():
            groups = []
            for rid, k in rr:
                if groups and groups[-1][1] == k:
                    groups[-1][0].append(rid)
                else:
                    groups.append(([rid], k))
            for ids, (design, path) in groups:
                label = ids[0] if len(ids) == 1 else f"{ids[0]} to {ids[-1]}"
                rows.append([label, design, evidence.get(path, "Not demonstrated")])
        grid(
            self.d,
            ["SRS requirement", "Design responsibility", "Evidence key"],
            rows,
            [0.30, 0.52, 0.18],
        )
        paragraph(self.d, "Evidence index", size=13, bold=True, before=12, after=6)
        paragraph(
            self.d,
            "Paths are relative to the project root at revision 7190151.",
            size=10,
            italic=True,
        )
        grid(
            self.d,
            ["Key", "Repository path"],
            [[k, v] for v, k in evidence.items()],
            [0.10, 0.90],
        )

    def flush(self):
        """Emit the pending paragraph and the pending pipe table."""
        if self.text:
            inline(self.d.add_paragraph(), self.ref(self.text))
            self.text = ""
        if self.table:
            matrix = [[self.ref(v.strip()) for v in r.strip("|").split("|")] for r in self.table]
            matrix = [r for r in matrix if not all(re.fullmatch(r":?[- ]+:?", c or "-") for c in r)]
            self.table = []
            if not matrix:
                return
            n = len(matrix[0])
            # Every column first reserves room for its longest unbreakable token (an
            # identifier such as application_answers must not split mid-word). The
            # remaining width is then shared out by typical cell length, so a narrow
            # label column never starves while long prose columns take the rest.
            capacity = 104  # approximate characters on one table line
            need, floor = [], []
            for i in range(n):
                cells = [str(row[i]) for row in matrix]
                top = sum(sorted((len(c) for c in cells), reverse=True)[:3]) / min(3, len(cells))
                longest = max((len(w) for c in cells for w in re.split(r"\s+", c) if w), default=0)
                need.append(max(top, longest + 2))
                floor.append(min(60.0, max(9.0, (longest + 2) / capacity * 100)))
            base = sum(floor)
            if base >= 96:
                ratios = [f * 96 / base for f in floor]
            else:
                spare = 100 - base
                total_need = sum(need) or 1
                ratios = [floor[i] + spare * need[i] / total_need for i in range(n)]
            grid(self.d, matrix[0], matrix[1:], ratios)

    def render(self, raw):
        for i, k in enumerate(re.findall(r"^@(?:figure|plate)\s+([\w-]+)\s*$", raw, re.M), 1):
            if k in self.order:
                raise ValueError("Duplicate figure " + k)
            self.order[k] = i
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                self.flush()
                continue
            if line.startswith("|"):
                if self.text:
                    self.flush()
                self.table.append(line)
                continue
            if self.table:
                self.flush()
            if h := re.fullmatch(r"(#{1,4})\s+(.+)", line):
                self.flush()
                level = len(h.group(1))
                title = self.ref(h.group(2))
                if level == 1:
                    title = title.upper()
                p = self.d.add_heading(title, level=level)
                if level == 1:
                    p.paragraph_format.page_break_before = not self.first
                    self.first = False
                continue
            if line.startswith("@"):
                self.flush()
                cmd, _, name = line.partition(" ")
                if cmd in ("@figure", "@plate"):
                    self.figure(name.strip(), cmd == "@plate")
                elif cmd == "@requirements":
                    self.requirements(int(name))
                elif cmd == "@trace":
                    self.trace()
                else:
                    raise ValueError(line)
                continue
            if line.startswith(("- ", "* ")):
                self.flush()
                p = self.d.add_paragraph()
                numbering(p, 1, 0)
                inline(p, self.ref(line[2:]))
                continue
            self.text += " " + line if self.text else line
        self.flush()


def build(kind, out):
    out.mkdir(exist_ok=True, parents=True)
    dest = out / (kind + ".docx")
    template = PACK / "original-theme" / f"{kind}-original.docx"
    if dest.resolve() in [(PACK.parent / (key + ".docx")).resolve() for key in ("SRS", "SDD")]:
        raise ValueError("Refusing to replace the university originals.")
    # Build over a private copy so the original file is never touched.
    with NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        base = Path(tmp.name)
    copyfile(template, base)
    try:
        d = Document(str(base))
        body = d.element.body
        for child in list(body):
            if child.tag != qn("w:sectPr"):
                body.remove(child)

        meta = load("institution.json")[kind]
        pr = d.core_properties
        pr.title = meta["project"]
        pr.subject = "JARVIS | Final Year Project"
        pr.author = meta["student"]
        pr.keywords = "JARVIS; software engineering; final year project"
        pr.comments = ""
        settings = d.settings.element
        settings.append(element("updateFields", val="true"))
        settings.append(element("doNotAutoCompressPictures"))

        cover(d, kind, meta)
        front_matter(d, kind, meta)

        # Close the roman front matter and open the arabic body.
        d.add_section(WD_SECTION.NEW_PAGE)
        footers(d.sections[0], "lowerRoman", 1, blank_first=True)
        footers(d.sections[1], "decimal", 1, blank_first=False)

        req = load("requirements.json")
        figs = load("structure-figures.json") | load("behavior-figures.json") | load("plates.json")
        b = Typesetter(d, kind, req, figs)
        b.render((SRC / (kind.lower() + ".md")).read_text(encoding="utf-8-sig"))
        d.save(dest)
        print(f"{kind}: {b.counter} figures, {len(d.tables)} tables; {dest}")
    finally:
        base.unlink(missing_ok=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", choices=["SRS", "SDD"])
    args = ap.parse_args()
    for key in [args.only] if args.only else ["SRS", "SDD"]:
        build(key, args.out)
