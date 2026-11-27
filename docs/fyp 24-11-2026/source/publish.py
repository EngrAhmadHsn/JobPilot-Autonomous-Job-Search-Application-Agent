"""Build the two FYP Word editions from the neighboring text, register and art.

Usage: python source/publish.py --out <new-directory> [--only SRS|SDD]
Use refresh_word.py to populate and paginate the Word fields before distribution.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Mm, Pt, RGBColor
from PIL import Image

SRC = Path(__file__).resolve().parent
PACK = SRC.parent
BASELINE = "7190151"
FOREST, INK, MUTED, LINE, PALE, WHITE = "204B3E", "000000", "4B5B54", "A7B7AE", "E8F0EA", "FFFFFF"
SERIF, SANS = "Times New Roman", "Arial"
BODY_W = 6.04
ABSTRACT = {
    "SRS": "A candidate needs to know which jobs fit their experience, what a tailored résumé changes, and who decides whether to send it. JobPilot ranks stored listings and explains the evidence behind a match. A candidate can compare a draft with the original, correct supported text and review questions before authorizing any executable application. The requirements distinguish acceptance of a request from proof of receipt. A local test employer supports the full submission workflow. On a real employer’s site, the candidate retains control of the final action.",
    "SDD": "JobPilot keeps job listings in a shared corpus and stores candidate documents, application answers and decisions under the account that owns them. The search service ranks stored jobs; the drafting service checks proposed wording against the résumé. When a candidate authorizes an executable application, the API records the decision and queues a run. A separate worker acts within the adapter’s permissions. The design explains how an interrupted run is recovered, why a missing confirmation calls for human review, and why the real-board pilot cannot submit on the candidate’s behalf.",
}


def load(name):
    return json.loads((SRC / name).read_text(encoding="utf-8-sig"))


def element(tag, **attrs):
    x = OxmlElement("w:" + tag)
    for key, val in attrs.items():
        x.set(qn("w:" + key), str(val))
    return x


def font(obj, name=SERIF, size=12, color=INK, bold=False, italic=False):
    f = obj.font
    f.name, f.size, f.bold, f.italic = name, Pt(size), bold, italic
    f.color.rgb = RGBColor.from_string(color)
    rpr = obj._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    for k in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme", "csTheme"):
        rf.attrib.pop(qn("w:" + k), None)
    for a in ("ascii", "hAnsi", "eastAsia", "cs"):
        rf.set(qn("w:" + a), name)
    return obj


def style(d, name, face, size, color=INK, bold=False, before=0, after=0, spacing=1.3, next_=False):
    s = d.styles[name] if name in d.styles else d.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    if name != "Normal":
        s.base_style = d.styles["Normal"]
    font(s, face, size, color, bold)
    pf = s.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = spacing
    pf.keep_with_next = next_
    pf.keep_together = False
    pf.widow_control = True
    return s


def styles(d):
    style(d, "Normal", SERIF, 12, after=6, spacing=1.42)
    for lev, sz, gap in [(1, 20, 18), (2, 15, 13), (3, 12.5, 9)]:
        s = style(
            d,
            "Heading " + str(lev),
            SERIF,
            sz,
            FOREST if lev <= 2 else INK,
            True,
            gap,
            5,
            1.13,
            True,
        )
        s.paragraph_format.keep_together = True
        s.paragraph_format.page_break_before = False
        ppr = s._element.get_or_add_pPr()
        if ppr.find(qn("w:outlineLvl")) is None:
            ppr.append(element("outlineLvl", val=lev - 1))
    for a in [
        ("FYP front title", SERIF, 22, FOREST, True, 0, 9, 1.12, True),
        ("FYP label", SANS, 9, FOREST, True, 0, 7, 1.15, True),
        ("FYP subhead", SERIF, 14, INK, True, 12, 5, 1.15, True),
        ("FYP note", SERIF, 10.5, MUTED, False, 3, 8, 1.25, False),
        ("FYP table", SERIF, 10.3, INK, False, 0, 0, 1.18, False),
        ("FYP table head", SANS, 9, FOREST, True, 0, 0, 1.14, False),
        ("FYP table id", SANS, 9, FOREST, True, 0, 0, 1.19, False),
        ("FYP photo", SANS, 10, INK, False, 4, 3, 1.0, True),
        ("Caption", SERIF, 11, INK, False, 0, 8, 1.18, False),
        ("FYP small", SANS, 9, MUTED, False, 0, 0, 1.12, False),
        ("FYP header", SANS, 8.5, MUTED, False, 0, 0, 1.05, False),
        ("FYP field", SERIF, 11, INK, False, 0, 0, 1.15, False),
        ("FYP deck", SERIF, 13, INK, False, 0, 10, 1.48, False),
    ]:
        style(d, *a)
    d.styles["Caption"].font.italic = False
    d.styles["Caption"].paragraph_format.keep_together = True
    for n in (1, 2, 3):
        s = style(
            d,
            f"TOC {n}",
            SERIF,
            11 if n == 1 else 10.3,
            FOREST if n == 1 else INK,
            n == 1,
            3 if n == 1 else 0,
            2,
            1.06,
        )
        s.paragraph_format.left_indent = Inches((n - 1) * 0.19)
    t = style(d, "Table of Figures", SERIF, 10.5, INK, False, 0, 3, 1.07)
    t.paragraph_format.keep_together = True


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


def borders(p, side, clr=LINE, sz=5, space=4):
    pp = p._p.get_or_add_pPr()
    bs = element("pBdr")
    bs.append(element(side, val="single", sz=sz, space=space, color=clr))
    pp.append(bs)


def keep(p):
    p.paragraph_format.keep_with_next = True
    return p


def pad_table(table, vert=62, hori=95, rule=True):
    pr = table._tbl.tblPr
    mar = element("tblCellMar")
    for a, v in [("top", vert), ("bottom", vert), ("left", hori), ("right", hori)]:
        mar.append(element(a, w=v, type="dxa"))
    pr.append(mar)
    b = element("tblBorders")
    for a in ("top", "bottom", "start", "end", "insideH", "insideV"):
        yes = rule and a in ("top", "bottom", "insideH")
        b.append(
            element(
                a,
                val="single" if yes else "nil",
                sz=4 if a != "insideH" else 2,
                color=LINE if a != "insideH" else "D6DFD9",
            )
        )
    pr.append(b)


def grid(parent, heads, rows, ratios, *, total=BODY_W, small=False, basis=False):
    n = len(heads)
    table = parent.add_table(rows=1, cols=n)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    widths = [Inches(total * x / sum(ratios)) for x in ratios]
    pad_table(table, 45 if small else 64, 80 if small else 92)
    for i, w in enumerate(widths):
        table.columns[i].width = w
    for rid, values in enumerate([heads, *rows]):
        row = table.rows[0] if rid == 0 else table.add_row()
        trpr = row._tr.get_or_add_trPr()
        trpr.append(element("cantSplit"))
        if not rid:
            trpr.append(element("tblHeader", val="true"))
        for ci, (cell, text, wid) in enumerate(zip(row.cells, values, widths)):
            cell.width = wid
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if not rid:
                cell._tc.get_or_add_tcPr().append(
                    element("shd", val="clear", fill=PALE, color="auto")
                )
            p = cell.paragraphs[0]
            p.style = (
                "FYP table head"
                if not rid
                else "FYP table id"
                if basis and ci == 0
                else "FYP table"
            )
            parts = compact(str(text)).split("\n")
            for part_no, part in enumerate(parts):
                if part_no:
                    p = cell.add_paragraph(style="FYP table")
                    p.paragraph_format.space_before = Pt(2)
                    if basis and ci == 0:
                        font(p.add_run(part), SANS, 8.2, MUTED)
                        continue
                inline(p, part)
            if rid == 0:
                p.paragraph_format.keep_with_next = True
    return table


def compact(t):
    return t.replace("**", "").replace("<br/>", "\n").replace("<br>", "\n").strip()


def inline(p, text):
    for part in re.split(r"(`[^`]+`)", text):
        if part.startswith("`") and part.endswith("`"):
            r = p.add_run(part[1:-1])
            r.font.name = SANS
            r.font.color.rgb = RGBColor.from_string(FOREST)
        else:
            p.add_run(part)


def document_geometry(s, cover=False):
    s.page_width = Mm(210)
    s.page_height = Mm(297)
    s.left_margin = Inches(0 if cover else 1.40)
    s.right_margin = Inches(0 if cover else 0.81)
    s.top_margin = Inches(0 if cover else 0.94)
    s.bottom_margin = Inches(0 if cover else 0.88)
    s.header_distance = Inches(0.44)
    s.footer_distance = Inches(0.4)


def ppage(s, fmt, start=1):
    p = s._sectPr.find(qn("w:pgNumType"))
    if p is not None:
        s._sectPr.remove(p)
    s._sectPr.insert_element_before(
        element("pgNumType", fmt=fmt, start=start), "w:cols", "w:docGrid"
    )


def running(s, kind, front):
    s.header.is_linked_to_previous = False
    s.footer.is_linked_to_previous = False
    h = s.header.paragraphs[0]
    h.style = "FYP header"
    h.paragraph_format.tab_stops.add_tab_stop(Inches(BODY_W), WD_TAB_ALIGNMENT.RIGHT)
    font(h.add_run("JOBPILOT"), SANS, 8.7, FOREST, True)
    h.add_run("\t" + ("Software requirements" if kind == "SRS" else "Software design"))
    borders(h, "bottom", sz=4, space=5)
    p = s.footer.paragraphs[0]
    p.style = "FYP header"
    p.paragraph_format.tab_stops.add_tab_stop(Inches(BODY_W), WD_TAB_ALIGNMENT.RIGHT)
    p.add_run("Department of Computer Science  /  Final Year Project\t")
    field(p, "PAGE \\* roman" if front else "PAGE \\* Arabic", "i" if front else "1")
    ppage(s, "lowerRoman" if front else "decimal")


def cover(d, kind, meta):
    # R5 clean-white academic cover: borderless wrapper, centered identity, title before
    # the two-column metadata table. Reserve space for Word's section-end paragraph.
    section = d.sections[0]
    document_geometry(section, True)
    wrapper = d.add_table(rows=1, cols=1)
    wrapper.autofit = False
    wrapper.alignment = WD_TABLE_ALIGNMENT.CENTER
    wrapper.columns[0].width = Mm(210)
    wrapper.cell(0, 0).width = Mm(210)
    wrapper.rows[0].height = Mm(282)
    wrapper.rows[0].height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    pad_table(wrapper, 0, 1150, False)
    cell = wrapper.cell(0, 0)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(46)
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.line_spacing = 1.0
    shape = p.add_run().add_picture(str(SRC / "university-crest.jpg"), width=Inches(0.99))
    shape._inline.docPr.set("descr", "University crest from the original title page")

    def line(text, face, pt, color=INK, b=False, before=0, after=0):
        p = cell.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf = p.paragraph_format
        pf.space_before = Pt(before)
        pf.space_after = Pt(after)
        pf.line_spacing = 1.13
        font(p.add_run(text), face, pt, color, b)
        return p

    line(meta["university"], SERIF, 19, FOREST, True, 2, 3)
    line("Department of Computer Science", SANS, 10, MUTED, False, 0, 6)
    p = line("FINAL YEAR PROJECT", SANS, 10, FOREST, True, 15, 5)
    p.paragraph_format.left_indent = Inches(1.25)
    p.paragraph_format.right_indent = Inches(1.25)
    borders(p, "top", LINE, 6, 8)
    title = meta["kind"]
    size = min(30, max(23, round(158 / len(title) ** 0.5)))
    line(title, SERIF, size, INK, True, 12, 7)
    line("JobPilot", SERIF, 21, FOREST, True, 0, 2)
    line(meta["project"], SERIF, 14, INK, False, 0, 16)
    t = cell.add_table(rows=0, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    pad_table(t, 65, 95, False)
    for col, w in zip(t.columns, (1.35, 2.95)):
        col.width = Inches(w)
    for l, v in [
        ("Submitted by", meta["student"]),
        ("Roll number", meta["roll"]),
        ("Submitted to", meta["supervisor"]),
        ("Programme", meta["programme"]),
        ("Session", meta["session"].removeprefix("Session ")),
    ]:
        cells = t.add_row().cells
        for j, cc in enumerate(cells):
            cc.width = Inches((1.35, 2.95)[j])
            p = cc.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            font(
                p.add_run(l if not j else v),
                SANS if not j else SERIF,
                9.5 if not j else 12,
                MUTED if not j else INK,
                False,
            )
            if j:
                borders(p, "bottom", "C7D2CB", 3, 2)
    line("22 November 2026", SERIF, 12, INK, False, 22, 2)
    line(f"{kind}  /  FYP edition", SANS, 9, MUTED, False, 2, 0)


def front_matter(d, kind, m):
    s = d.add_section(WD_SECTION.NEW_PAGE)
    document_geometry(s)
    running(s, kind, True)
    d.add_paragraph("FRONT MATTER", style="FYP label")
    d.add_paragraph("Abstract", style="FYP front title")
    d.add_paragraph(ABSTRACT[kind], style="FYP deck")
    d.add_paragraph("Revision history", style="FYP subhead")
    hist = [[h[0], h[1], h[3]] for h in m["history"]]
    hist.append(
        [
            "22 Nov 2026",
            "FYP edition",
            "Requirements and design reconciled to JobPilot revision 7190151.",
        ]
    )
    grid(d, ["Date", "Edition", "Change"], hist, [0.16, 0.25, 0.59], small=True)
    d.add_paragraph("Document approval", style="FYP subhead")
    d.add_paragraph("Signature and date are reserved for formal review.", style="FYP note")
    grid(
        d,
        ["Printed name", "Role", "Signature", "Date"],
        [[r[1], r[2], r[0], r[3]] for r in m["approval"]],
        [0.25, 0.36, 0.24, 0.15],
        small=True,
    )
    p = d.add_paragraph("Contents", style="FYP front title")
    p.paragraph_format.page_break_before = True
    field(d.add_paragraph(style="FYP field"), 'TOC \\o "1-2" \\h \\z', "Contents")
    p = d.add_paragraph("List of figures", style="FYP front title")
    p.paragraph_format.page_break_before = True
    field(d.add_paragraph(style="FYP field"), 'TOC \\h \\z \\c "Figure"', "Figures")
    s = d.add_section(WD_SECTION.NEW_PAGE)
    document_geometry(s)
    running(s, kind, False)


class Typesetter:
    def __init__(self, d, kind, req, figs):
        self.d = d
        self.kind = kind
        self.req = req
        self.figs = figs
        self.counter = 0
        self.order = {}
        self.bookmarks = {}
        self.last_heading = ""
        self.first = True
        self.text = ""
        self.table = []
        self.mirror = {}
        self.named = {x for v in req for x in [v.get("test", "")] if x}

    def ref(self, t):
        def repl(m):
            k = m.group(1)
            return str(self.order[k])

        return re.sub(r"\{fig:([\w-]+)\}", repl, compact(t))

    def flush(self):
        if self.text:
            p = self.d.add_paragraph()
            inline(p, self.ref(self.text))
            self.text = ""
        if self.table:
            matrix = [[self.ref(v.strip()) for v in r.strip("|").split("|")] for r in self.table]
            matrix = [r for r in matrix if not all(re.fullmatch(r":?[- ]+:?", c or "-") for c in r)]
            n = len(matrix[0])
            # Give every column room for its longest unbreakable token (an
            # identifier such as application_answers must not split mid-word),
            # then distribute the remainder by typical cell length.
            capacity = 104  # approximate characters on one table line
            need, floor = [], []
            for i in range(n):
                cells = [str(row[i]) for row in matrix]
                top = sum(sorted((len(c) for c in cells), reverse=True)[:3]) / min(3, len(cells))
                longest = max((len(w) for c in cells for w in re.split(r"\s+", c) if w), default=0)
                need.append(max(top, longest + 2))
                floor.append(max(7.0, min(58.0, (longest + 2) / capacity * 100)))
            total = sum(need) or 1
            ratios = [max(floor[i], min(76.0, need[i] / total * 100)) for i in range(n)]
            grid(self.d, matrix[0], matrix[1:], ratios, small=n >= 4)
            self.table = []

    def figure(self, key, photo):
        entry = self.figs[key]
        path = (PACK / "ui" if photo else PACK / "diagrams" / "png") / (key + ".png")
        with Image.open(path) as im:
            w, h = im.size
            dpi = im.info.get("dpi", (96, 96))[0]
        # HiDPI PlantUML output may have no PNG pHYs; use a fitted figure, cap
        # tiny panels at natural 96-DPI size rather than stretching their glyphs.
        max_h = 4.9 if photo else 5.6
        limit = BODY_W if photo else min(BODY_W, w / max(dpi, 1))
        width = min(limit, max_h * w / h)
        p = self.d.add_paragraph(style="FYP photo")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        image = p.add_run().add_picture(str(path), width=Inches(width))
        image._inline.docPr.set("descr", entry["alt"])
        image._inline.docPr.set("title", entry["caption"])
        image._inline.docPr.set("name", key + ".png")
        cap = self.d.add_paragraph(style="Caption")
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        prefix = cap.add_run("Figure ")
        font(prefix, SANS, 9.5, FOREST, True)
        self.counter += 1
        mark = element("bookmarkStart", id=1000 + self.counter, name="jp_" + key.replace("-", "_"))
        cap._p.append(mark)
        field(cap, "SEQ Figure \\* ARABIC", str(self.counter))
        cap._p.append(element("bookmarkEnd", id=1000 + self.counter))
        cap.add_run(". " + entry["caption"].rstrip("."))
        if photo:
            p = self.d.add_paragraph(style="FYP note")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run(entry["provenance"])

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
            [0.17, 0.405, 0.425],
            small=True,
            basis=True,
        )

    def trace(self):
        # Each requirement retains its own row unless an adjacent item cites the
        # same design and evidence. Evidence keys keep repeated paths off the page.
        evidence = {}
        bygroup = defaultdict(list)
        for r in self.req:
            k = (r["design"], r.get("test") or "")
            bygroup[r["group"]].append((r["id"], k))
            if k[1] and k[1] not in evidence:
                evidence[k[1]] = f"E{len(evidence) + 1:02d}"
        self.d.add_paragraph(
            "Evidence keys identify a source file, a test specification or a dated evaluation. A reference to a test does not assert that it was run for this edition.",
            style="FYP note",
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
            [0.31, 0.51, 0.18],
            small=True,
        )
        self.d.add_paragraph("Evidence index", style="FYP subhead")
        self.d.add_paragraph(
            "Paths are relative to the project root at revision 7190151.", style="FYP note"
        )
        grid(
            self.d,
            ["Key", "Repository path"],
            [[k, v] for v, k in evidence.items()],
            [0.12, 0.88],
            small=True,
        )

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
            if h := re.fullmatch(r"(#{1,3})\s+(.+)", line):
                self.flush()
                level = len(h.group(1))
                title = self.ref(h.group(2))
                p = self.d.add_heading(title, level=level)
                if level == 1 and not self.first:
                    p.paragraph_format.page_break_before = True
                if level == 1:
                    self.first = False
                self.last_heading = title
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
                p.paragraph_format.left_indent = Inches(0.18)
                inline(p, self.ref(line[2:]))
                continue
            self.text += " " + line if self.text else line
        self.flush()


def build(kind, out):
    out.mkdir(exist_ok=True, parents=True)
    dest = out / (kind + ".docx")
    if dest.resolve() in [(PACK.parent / (key + ".docx")).resolve() for key in ("SRS", "SDD")]:
        raise ValueError("Refusing to replace the university originals.")
    d = Document()
    styles(d)
    meta = load("institution.json")[kind]
    pr = d.core_properties
    pr.title = meta["kind"] + ": " + meta["project"]
    pr.subject = "JobPilot | Final Year Project"
    pr.author = meta["student"]
    pr.keywords = "JobPilot; software engineering; final year project"
    pr.comments = ""
    settings = d.settings.element
    settings.append(element("updateFields", val="true"))
    settings.append(element("doNotAutoCompressPictures"))
    cover(d, kind, meta)
    front_matter(d, kind, meta)
    req = load("requirements.json")
    figs = load("structure-figures.json") | load("behavior-figures.json") | load("plates.json")
    b = Typesetter(d, kind, req, figs)
    b.render((SRC / (kind.lower() + ".md")).read_text(encoding="utf-8-sig"))
    d.save(dest)
    print(f"{kind}: {b.counter} figures, {len(d.tables)} tables; {dest}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", choices=["SRS", "SDD"])
    args = ap.parse_args()
    for key in [args.only] if args.only else ["SRS", "SDD"]:
        build(key, args.out)
