# JobPilot — FYP editions of the SRS and SDD

These are the final-year-project revisions of the two university documents, rebuilt
against JobPilot revision `7190151` dated 22 November 2026. The originals,
`../SRS.docx` and `../SDD.docx`, are left untouched.

## What is here

| Path | What it holds |
| --- | --- |
| `SRS.docx`, `SDD.docx` | The two Word editions, with a live contents list and figure list. |
| `SRS.pdf`, `SDD.pdf` | Rendered copies for reading and printing. |
| `diagrams/*.puml` | Editable PlantUML sources, one per engineering figure. |
| `diagrams/png/` | The rendered figures embedded in the documents. |
| `ui/` | Two dated console captures used in the SDD interface chapter. |
| `source/` | The manuscripts, requirement register, figure manifests and build scripts. |

The two documents differ in one respect worth noting: the university title pages
carry different roll numbers and different named supervisors. Both were preserved
exactly as supplied; the discrepancy is the university's to resolve.

## Regenerating

Run through the project virtual environment (`env/Scripts/python.exe` on Windows).

```bash
# 1. Redraw every figure, then check its lettering at the printed size.
PLANTUML_JAR=<path to plantuml.jar> python source/render_figures.py

# 2. Typeset both Word editions from the manuscripts.
python source/publish.py --out ../_build

# 3. Populate the contents and figure lists and export a PDF (needs Word).
python source/refresh_word.py ../_build/SRS.docx ../_build/SDD.docx \
  --word-out ../_build/final --pdf-out ../_build/pdf

# 4. Confirm the package, markers, captions and evidence paths.
python source/check_package.py --dir ../_build/final
```

`publish.py` refuses to write over the university originals. `refresh_word.py`
runs its own Word instance against a private copy, so it will not disturb a Word
session you already have open.

## Where the claims come from

Every requirement in `source/requirements.json` names a design responsibility and
one repository path — a test specification, a source module or a dated evaluation —
that a reader can inspect at revision `7190151`. A reference is a place to look,
not an assertion that the test was run for this edition. Chapter 8 of the SDD
distinguishes offline measurements, the local fake-ATS exercise and the live
preparation-only pilot, and states what each one does and does not establish.
