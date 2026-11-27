# JARVIS — FYP editions of the SRS and SDD (25 November 2026 edition)

These are the final-year-project revisions of the two university documents, rebuilt
against JARVIS revision `7190151` dated 22 November 2026. They are typeset on the
university documents' own theme: each edition is built over a private copy of its
original, so the style set, theme fonts, numbering definitions, page geometry and
cover lettering are the ones the university supplied. The university originals,
`docs/SRS.docx` and `docs/SDD.docx`, are left untouched; byte-identical copies are
kept in `original-theme/` so that a reader can compare a sentence with what it
replaced without leaving this folder.

## What is here

| Path | What it holds |
| --- | --- |
| `SRS.docx`, `SDD.docx` | The two Word editions, with a live contents list and figure list. |
| `SRS.pdf`, `SDD.pdf` | Rendered copies for reading and printing. |
| `diagrams/*.puml` | Thirty-one editable PlantUML sources, one per engineering figure. |
| `diagrams/png/` | The rendered figures embedded in the documents. |
| `diagrams/_theme.puml` | The monochrome Times New Roman print theme applied to every figure. |
| `ui/` | Four dated console captures used in the SDD interface chapter. |
| `original-theme/` | The two university documents exactly as supplied. The build reads their styles, theme, numbering and fonts, and keeps the copy for comparison. |
| `source/` | The manuscripts, requirement register, figure manifests and build scripts. |

The two documents differ in one respect worth noting: the university title pages
carry different roll numbers and different named supervisors. Each edition keeps its
own cover identity from `source/institution.json`, so both are preserved exactly as
supplied. The discrepancy is the university's to resolve, not this edition's.

## How the documents are typeset

`source/publish.py` copies `original-theme/SRS-original.docx` or
`SDD-original.docx`, clears the body and writes the new text back into that package.
`word/styles.xml`, `word/theme/theme1.xml`, `word/numbering.xml` and
`word/fontTable.xml` are therefore the university's own parts, not reconstructions.
Consequently the documents carry the originals' typography:

- Times New Roman 12 pt, justified, 1.5 line spacing with 9 pt before and after a
  paragraph, exactly as the originals' `docDefaults` sets it.
- Headings at 16, 14, 13 and 12 pt bold in black. First-level headings are centred
  and set in capitals, again as the originals do.
- Captions 11 pt italic and centred; table text 10 pt; inline code 8.5 pt Courier
  New, the size the SDD original uses for code.
- Tables on a full single black grid with the originals' `D9D9D9` header fill and a
  bold header row.
- A4 pages with the originals' margins (1.5 in left, 0.75 in right, 1.2 in top,
  0.6 in bottom), roman numerals through the front matter, arabic numerals from
  page one of the body, and no running header.
- The cover as the originals compose it: a 22 pt title, 16 pt subtitle, the crest,
  the tabbed `Submitted By` / `Roll No` / `Submitted To` block, the 16 pt programme
  and session, the 17 pt department and the 22 pt Old English Text MT university
  name.

One deliberate alignment: the supplied SRS sets `Document Approval` at body size
while `Revision History` is 16 pt. Both, and the contents and figure-list titles,
now share the single 16 pt front-matter heading, with the abstract at 20 pt.

The printed figure column is 6.02 in, which is A4 less the originals' margins.

## How much the editions carry

The brief was to keep the originals' detail and add the current system's, not to
compress. The manuscripts are therefore longer than the originals:
`source/srs.md` is about 100,000 characters against the original's 64,000, and
`source/sdd.md` about 113,000 against 52,000. The SRS edition runs to 70 pages
with 46 tables (the original: 43 pages, 31 tables) and the SDD to 86 pages with 14
tables. Structure restored from the originals and corrected rather than rewritten
includes the SRS definitions table (51 rows), the numbered references, the four
external-interface sections with an 84-row endpoint inventory, the eleven
functional-requirement areas in the originals' Introduction / Inputs / Processing /
Outputs / Error handling shape, eight per-use-case tables, nine class descriptions,
and the SDD's design rationale, data dictionary, sixteen component descriptions,
the screen-objects table and the appendix route tables.

A reader comparing a sentence with the original should expect some claims to have
changed on purpose: where an original statement no longer matches the code, the
edition states the code's behaviour. One example worth naming, because older notes
in the repository still repeat the stale figure: the local embedding model reads at
most 16,000 characters per text, measured in `src/llm/embeddings.py`, not the
8,000 that note records.

## How the figures were redrawn

Every engineering figure was redrawn in PlantUML using `diagrams/_theme.puml`, a
monochrome theme that matches the university templates: Times New Roman, black
lines, no shadow. Where PlantUML has no dedicated notation for a view the documents
need, the figure is a clearly labelled equivalent (for example the logical
entity-relationship view and the console navigation map). The specialist views sit
in the SDD appendix, and the real console captures stay in `ui/`, separate from the
diagrams.

`source/render_figures.py` renders at 192 DPI and refuses to publish a figure whose
lettering would print below 7 pt in the 6.02-inch column. That gate is why several
figures are split or shortened rather than one dense page.

## Regenerating

Run through the project virtual environment (`env/Scripts/python.exe` on Windows),
from the repository root.

```bash
# 1. Redraw every figure, then check its lettering at the printed size.
PLANTUML_JAR=<path to plantuml.jar> ./env/Scripts/python.exe \
  "docs/fyp 25-11-2026/source/render_figures.py"

# 2. Typeset both Word editions from the manuscripts.
./env/Scripts/python.exe "docs/fyp 25-11-2026/source/publish.py" --out _build

# 3. Populate the contents and figure lists and export a PDF (needs Word).
./env/Scripts/python.exe "docs/fyp 25-11-2026/source/refresh_word.py" \
  _build/SRS.docx _build/SDD.docx --word-out _build/final --pdf-out _build/pdf

# 4. Confirm the package, markers, captions and evidence paths.
./env/Scripts/python.exe "docs/fyp 25-11-2026/source/check_package.py" \
  --dir _build/final
```

`publish.py` refuses to write over the university originals. `refresh_word.py`
runs its own Word instance against a private copy, so it will not disturb a Word
session you already have open.

`source/` also retains the in-place utilities (`inplace_edit.py`,
`replace_figures.py`, `_build_srs_edits.py`, `_build_sdd_edits.py`). They rewrite
selected paragraphs and image slots inside a copy of the originals while leaving its
layout, fields and cover alone. They are not part of the build above; they exist for
a reader who needs the revised text written back into the university layout rather
than rebuilt.

## Where the claims come from

Every requirement in `source/requirements.json` names a design responsibility and
one repository path — a test specification, a source module or a dated evaluation —
that a reader can inspect at revision `7190151`. A reference is a place to look, not
an assertion that the test was run for this edition. Chapter 8 of the SDD
distinguishes the offline ranking fixture, the local fake-ATS exercise and the live
preparation-only pilot, and states what each one establishes and what it does not.

Three boundaries hold throughout the pair:

- A 202 response proves the API accepted a request. It does not prove that a form was
  filled, a button pressed or a receipt obtained.
- The local fake ATS is the only target where a complete submission and its
  verification were exercised.
- No live employer has received an application from this system. On a real board the
  adapter prepares the form and hands the browser to a person; it holds no submit
  capability, so the stop is enforced by the permission model rather than by a prompt.

Work present in the tree after `7190151` is named in SRS §3.9 and SDD §8.3 and is
outside this baseline.