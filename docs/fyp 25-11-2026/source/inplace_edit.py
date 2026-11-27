"""Replace text inside copies of the university SRS/SDD without changing layout.

Paragraph style, table structure, fields, image slots, section breaks, headers,
footers and the cover are left exactly as they are. Only the text of selected
paragraphs and table cells is rewritten; a missing key is left alone.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.table import Table


def replace_paragraph(p, text):
    """Put text in the first run and clear the rest, keeping all run formatting."""
    runs = p.runs
    if not runs:
        p.add_run(text)
        return
    runs[0].text = text
    for r in runs[1:]:
        r.text = ""


def set_cell(cell, text):
    ps = cell.paragraphs
    replace_paragraph(ps[0], text)
    for p in ps[1:]:
        replace_paragraph(p, "")


def edit(docx: Path, out: Path, edits: dict):
    doc = Document(docx)
    changed = 0
    paragraph_edits = edits["paragraphs"]
    # Keys may be a paragraph index (string integer) or the exact original text.
    for i, p in enumerate(doc.paragraphs):
        key = str(i)
        if key in paragraph_edits:
            replace_paragraph(p, paragraph_edits[key])
            changed += 1
            continue
        text = p.text.strip()
        if text and text in paragraph_edits:
            replace_paragraph(p, paragraph_edits[text])
            changed += 1
    for ti, table in enumerate(doc.tables):
        spec = edits.get("tables", {}).get(str(ti))
        if not spec:
            continue
        for ri, row in enumerate(table.rows):
            for ci, cell in enumerate(row.cells):
                key = (str(ri), str(ci))
                if key in spec:
                    set_cell(cell, spec[key])
                    changed += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return changed


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("docx", type=Path)
    a.add_argument("edits", type=Path)
    a.add_argument("--out", type=Path, required=True)
    args = a.parse_args()
    import json

    n = edit(args.docx, args.out, json.loads(args.edits.read_text(encoding="utf-8")))
    print(f"{args.out}: {n} text replacements")
