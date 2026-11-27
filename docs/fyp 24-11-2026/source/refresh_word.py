"""Refresh Word fields on a disposable generated draft and export an inspection PDF.

Requires Microsoft Word and pywin32. Never opens the university originals or attaches
itself to the user's running Word instance. Both output directories must be supplied.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tempfile
from zipfile import ZipFile

from lxml import etree
import win32com.client


def keep_field_updates(source: Path, target: Path):
    """Word saves correct cached pages but clears its update-on-open flag."""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with ZipFile(source) as src, ZipFile(target, "w") as out:
        for part in src.infolist():
            data = src.read(part.filename)
            if part.filename == "word/settings.xml":
                root = etree.fromstring(data)
                node = root.find(ns + "updateFields")
                if node is None:
                    node = etree.Element(ns + "updateFields")
                    after = next(
                        (
                            child
                            for child in root
                            if etree.QName(child).localname
                            in ("footnotePr", "endnotePr", "compat", "rsids")
                        ),
                        None,
                    )
                    if after is None:
                        root.append(node)
                    else:
                        after.addprevious(node)
                node.set(ns + "val", "true")
                data = etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
            out.writestr(part, data)


def refresh(source: Path, word_out: Path, pdf_out: Path):
    source = source.resolve()
    word_out = word_out.resolve()
    pdf_out = pdf_out.resolve()
    if source.stem not in ("SRS", "SDD") or source.suffix.lower() != ".docx":
        raise ValueError("Expected a generated SRS.docx or SDD.docx.")
    masters = Path(__file__).resolve().parents[2]
    if source.parent == masters or word_out == masters or source.parent == word_out:
        raise ValueError(
            "Use a separate draft directory; never refresh the university original in place."
        )
    word_out.mkdir(parents=True, exist_ok=True)
    pdf_out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jobpilot-fyp-word-") as temp:
        f = Path(temp) / source.name
        shutil.copyfile(source, f)
        app = win32com.client.DispatchEx("Word.Application")
        app.DisplayAlerts = 0
        app.Visible = False
        doc = None
        try:
            app.AutomationSecurity = 3
            app.Options.UpdateLinksAtOpen = False
            app.Options.UpdateFieldsAtPrint = False
            doc = app.Documents.Open(
                str(f),
                ConfirmConversions=False,
                ReadOnly=False,
                AddToRecentFiles=False,
                Visible=False,
            )
            doc.ActiveWindow.View.Type = 3
            doc.Fields.Update()
            for _ in range(2):
                doc.Repaginate()
                for coll in (doc.TablesOfContents, doc.TablesOfFigures):
                    for i in range(1, coll.Count + 1):
                        coll.Item(i).Update()
                doc.Repaginate()
                for coll in (doc.TablesOfContents, doc.TablesOfFigures):
                    for i in range(1, coll.Count + 1):
                        coll.Item(i).UpdatePageNumbers()
            print(
                f"{source.stem}: {doc.ComputeStatistics(2)} Word pages, {doc.InlineShapes.Count} inline images; contents={doc.TablesOfContents.Count}, figure lists={doc.TablesOfFigures.Count}",
                flush=True,
            )
            # Print only the document; do not include comments/revision balloons.
            pdf = Path(temp) / (source.stem + ".pdf")
            doc.ExportAsFixedFormat(
                str(pdf), 17, False, 0, 0, 1, 1, 0, True, True, 1, True, True, False
            )
            doc.Save()
            doc.Close(0)
            doc = None
            keep_field_updates(f, word_out / source.name)
            shutil.copyfile(pdf, pdf_out / pdf.name)
        finally:
            if doc is not None:
                doc.Close(0)
            app.Quit(0)


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("draft", type=Path, nargs="+")
    a.add_argument("--word-out", required=True, type=Path)
    a.add_argument("--pdf-out", required=True, type=Path)
    args = a.parse_args()
    for doc in args.draft:
        refresh(doc, args.word_out, args.pdf_out)
