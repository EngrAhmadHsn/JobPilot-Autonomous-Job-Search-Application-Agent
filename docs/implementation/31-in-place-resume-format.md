# WS-31 · Edit the Uploaded Résumé In Place

Status: **In progress (2026-11-13)** · Milestone: **M5** ·
Depends on: WS-05 (the tailoring pipeline, the DOCX renderer and its parser
round-trip test), WS-12 (the exact job-title check on the model's answer),
WS-22 (the style policy and the PII mask), WS-14 · Phase B (per-user storage,
where the uploaded file lives)

> **Where this starts.** A tailoring run throws the candidate's document away.
> `render_tailored_docx` (`src/resume/render.py:114`) opens a **new** `Document()`
> and writes the content out with the project's own idea of a résumé: `Title`
> style for the name, `Heading 1` for sections, `List Bullet` for bullets, and a
> fixed section order. The uploaded file is stored (`data/resumes/…`) and read
> exactly once — by the parser. Whatever the candidate actually formatted — their
> font, their section order, their spacing, their header block, the two-column
> skills table they spent an afternoon on — is gone from the deliverable.

The request (2026-11-13, verbatim):

> I would like you to try keep the resume format similar to what user upload as
> much as possible, obviously under certain circumstances you can change but if
> it is then keep the user formatting mean like edit in place instead of whole
> rewrite..

So the deliverable should be **the candidate's own file, with the tailoring
applied to it** — and a whole rewrite only when editing is not possible, which is
then reported rather than hidden.

---

## 1. What is preserved, and what changes

| Element | Today | After |
|---|---|---|
| Fonts, sizes, colours, bold/italic | lost | **preserved** — text is replaced inside the paragraph's existing runs |
| Section order and headings | rewritten to the project's order | **preserved** — the document's own headings and order, untouched |
| Margins, page setup, headers/footers, logo images | lost | **preserved** — never opened |
| Education, certifications, achievements | re-emitted from the profile | **untouched** — already in the document, already formatted; the editor does not touch what the tailoring did not change |
| Summary | rewritten | **edited in place** — the paragraph under the document's own summary heading |
| Experience bullets | rewritten whole | **edited in place**, bullet for bullet, in the document's own bullet paragraphs |
| Skills | re-emitted as `Category: a, b` lines | **filtered in place** — each of the document's own category lines keeps only the skills that survived tailoring |
| Non-content lines (gaps, separators, contact block, custom sections) | lost | **preserved** |
| Cover letter | not in the document | unchanged — still not in the document |
| Anything the tailoring removes | — | **never silently**: every in-place edit is counted in a `RenderReport` |

The deliverable **keeps the uploaded file's format**, not just its styling: a
`.docx` upload yields an edited `.docx`, a `.txt` upload an edited `.txt`. A
candidate whose résumé is plain text gets plain text back, because that *is* their
format. (The documents API already serves `.txt` and `.md` with the right
media type — `src/api/routes/documents.py:47`.)

---

## 2. The design

### 2.1 An editor, not a generator

New module `src/resume/edit.py`. The public shape:

```python
class RenderReport(BaseModel):
    mode: str            # "in_place" | "regenerated"
    source_format: str   # ".docx" | ".txt" | ".md" | "none"
    edits: int           # paragraphs/lines whose text was replaced
    appended: int        # paragraphs/lines added in the document's own style
    removed: int         # empty paragraphs left behind after a removing edit
    skipped: list[str]   # why a section or paragraph could not be edited
    notes: list[str]     # what the candidate should know (see §2.5)

def deliver_tailored_resume(
    tailored, profile, *, upload_path, out_dir, profile_id, job_id
) -> tuple[Path, RenderReport]: ...
```

`deliver_tailored_resume` is the only entry point the pipeline calls. It tries the
in-place editor; when the upload cannot be used it falls back to
`render_tailored_docx`, and **says so** in the report.

### 2.2 How a paragraph is matched

The editor re-derives the document's structure with the *parser's own*
vocabulary, because the profile it is editing against was produced by that
parser from that document. It walks the paragraphs once and records, for each:

* whether it is a heading (`src.resume.parser._SECTION_HEADINGS`, the same map
  `src/resume/ats.py::STANDARD_HEADINGS` mirrors), and which section it opens;
* whether it is a bullet (`_is_bullet`: a `List…` style, or a leading `-`/`•`/`·`)
  and which entry it belongs to;
* its paragraph index, so an edit is a *replacement*, never a rebuild.

Matching is then **by identity, never by similarity**:

| Tailored content | Matched to |
|---|---|
| experience entry | the original entry with the same company and title — a match the factuality validator already guarantees exists (`_name_known`, `_title_known`, `src/resume/tailor.py:120,134`) |
| bullet *j* of that entry | the *j*-th bullet paragraph of the original entry |
| summary | the first non-heading paragraph after the document's own summary heading |
| highlighted skill | the item inside the document's own `Category: …` skills line whose normalized form matches (`src.core.text.normalize`, the same comparison `_skill_lines` uses) |

No fuzzy matching, no diffing, no "closest paragraph". A bullet that cannot be
placed is appended rather than forced onto an unrelated paragraph, and the count
is in the report.

### 2.3 What the model is asked for changes with it

Position-wise editing only lands cleanly when the *shape* of the answer matches
the document. `SYSTEM_RULES` (`src/resume/tailor.py:36`) therefore gains a FORMAT
RULES block:

> * Rewrite the candidate's existing bullets. Do not merge two bullets into one or
>   split one into two; keep the same number of bullets under each role, in the
>   same order, unless the job makes a bullet clearly irrelevant.
> * Keep each bullet to one achievement, about the length of the original.

This is a prompt *request*, and the editor treats it as one: a count mismatch is
handled (§2.4), not assumed away. No schema change — `TailoredResume` stays
exactly as it is, so the factuality validator, the ATS analyzer and the console
are untouched by this workstream.

### 2.4 When the shape does not match

| Case | Behaviour |
|---|---|
| tailored bullets == original bullets | each bullet replaced in place |
| tailored bullets < original | the first *n* replaced, the leftover bullet paragraphs emptied (never left carrying stale claims) and counted in `removed` |
| tailored bullets > original | the first *n* replaced, the extra ones **appended** after the last bullet, copying that bullet's paragraph style |
| the editor finds no summary heading | the tailored summary is inserted after the name/title block, in the style of the document's own first body paragraph, counted in `appended` |
| a section the tailoring changed is absent from the document | appended under the document's own heading vocabulary, or — when there is no home for it — reported in `skipped` and left out of the file |

The rule behind the table: **the document is the shape, the tailoring is the
content.** The editor never reorders the candidate's sections and never invents a
heading their resume did not have.

### 2.5 Run-level formatting, and the honest limits

Replacing a paragraph's text keeps the **first run's** formatting and drops the
rest (`paragraph.runs[0].text = new; for run in paragraph.runs[1:]: run.text = ""`).
The consequence, stated rather than hidden: a bullet whose original mixed bold
and plain text comes back uniformly formatted at the first run's style. That is
the right trade — the alternative is a run-splitting heuristic that guesses where
the new text's emphasis belongs, and a wrong guess corrupts the wording's
meaning. It is recorded in `notes` when a paragraph with more than one run is
edited.

Two structural cases are refused rather than approximated, and land in `skipped`:

* **A paragraph whose text is not all in its own runs** (a hyperlink, a field, a
  content control). `paragraph.text` includes hyperlink text, `paragraph.runs`
  does not — editing one would silently delete the link text. Detected by
  comparing the two; the paragraph is left exactly as it is.
* **Text inside a table.** The `_format_risks` analyzer already reports tables as
  an ATS risk, and rewriting table cells would mean guessing at a layout the
  parser never read. Tables are left untouched and counted in `skipped`.

### 2.6 When the whole rewrite is the answer

`render_tailored_docx` is kept, unchanged, and becomes the fallback. It is used
whenever the original cannot be edited:

| Trigger | Why |
|---|---|
| the upload is missing (a profile restored from a backup, a row whose file was pruned) | nothing to edit |
| the file cannot be opened (a `.docx` that python-docx refuses) | nothing to trust |
| an unsupported extension (anything that is neither `.docx`, `.txt` nor `.md`) | no editor for it |

Each trigger produces `mode="regenerated"` and a `notes` entry naming the reason,
so the console can tell the candidate *"your original could not be edited — a
freshly formatted document was generated instead"* rather than presenting a
rewrite as an edit.

---

## 3. Execution plan

| Phase | Deliverable | Gate |
|---|---|---|
| **A** | `src/resume/edit.py`: the walk, the matching, `_docx_*` and `_text_*` editors, `RenderReport`, `deliver_tailored_resume` | the editor tests: docx formatting preserved, txt round-trip, count mismatches, hyperlink refusal, table refusal, fallback triggers |
| **B** | The FORMAT RULES prompt block; `pipeline.py` calls the orchestrator with the profile's upload path and carries the report | the pipeline test asserts the upload is edited and reports `mode="in_place"` |
| **C** | `TailoredResumeDB.render` (JSON, nullable) + migration; `TailorResponse.render`; the console panel | migration test; the API test asserts the report round-trips |
| **D** | Console: the render panel (mode, counts, notes); regenerated API types | `tsc` clean, Vitest green |
| **E** | Live verification: a real upload → tailor → download and re-parse the deliverable | recorded in §6 |

### Test matrix

| File | Covers |
|---|---|
| `tests/test_ws31_in_place_edit.py` (new) | a `.docx` upload with a distinctive font, section order and extra sections → the edited file keeps every one of them; a bullet is rephrased and the paragraph's bold/size survive; a `.txt` upload edits line-for-line and keeps blank lines and `-` markers; fewer/more tailored bullets; the missing-summary insertion; a hyperlink paragraph is skipped and unchanged; a table is skipped and unchanged; a missing upload regenerates and reports why |
| `tests/test_render.py` (extended) | the round-trip still holds for the regenerated path (it is the fallback, so it must stay correct) |
| `tests/test_tailoring_pipeline.py` (extended) | the outcome carries a `RenderReport`; with a real uploaded file the mode is `in_place` |
| `tests/test_tailoring_api.py` (extended) | `render` is in the response and in the stored record |

### Risks

| Risk | Mitigation |
|---|---|
| An in-place edit corrupts a candidate's document | the editor only ever replaces text inside paragraphs it identified by the parser's own structure; everything else — tables, links, fields, headers, images — is left untouched; the original file is never written to (the output is a new file, always) |
| The model ignores the bullet-count rule | §2.4 handles both directions and counts them; the report is on the API and in the console |
| A document whose structure defeats the walk | `mode="regenerated"` with the reason; the old renderer is the guarantee, and it still passes its round-trip test |
| The deliverable's file extension changes (`.txt` in → `.txt` out) | the documents API already maps the media types; the API field keeps its name; the path helper takes the extension |

---

## 4. Implementation status

| Item | State |
|---|---|
| §3 Phase A — the editor | **done** — `src/resume/edit.py`; both formats, the identity matching, the hyperlink/table refusals, `RenderReport`. 25 tests |
| §3 Phase B — prompt rules + pipeline wiring | **done** — `FORMAT_RULES` in `SYSTEM_RULES`; `run_tailoring(upload_path=…)` calls `deliver_tailored_resume`; `TailoringOutcome.render` |
| §3 Phase C — persistence + API | **done** — `tailored_resumes.render` (migration `7a1b2c3d4e5f`, verified by `scripts/verify_migrations.py`); `TailorResponse.render` |
| §3 Phase D — console | **done** — the "Your document" panel (mode, counts, notes, what was skipped); the download link names the real format; API types regenerated from the running server |
| §3 Phase E — live verification | **done** — 30 checks in `scripts/verify_ws30_31.py`, all passing (§6). Two real defects found and fixed |

---

## 5. What this workstream does not cover

1. **PDF uploads.** The upload validator accepts `.docx`, `.txt` and `.md`
   (`src/api/validation.py:29`); a PDF has no parser and therefore no editor.
   Unchanged.
2. **A visual diff of the edits.** The report counts edits; it does not preview
   which words changed. The console shows the tailored content beside the
   report, which is where a reviewer reads the wording today.
3. **Restoring the original's character-level emphasis.** §2.5 — the first run's
   formatting is kept. A run-level aligner is a bigger feature than this
   workstream, and a wrong one is worse than a uniform one.
4. **Editing the education, certifications and achievements sections.** The
   tailoring does not change them, so the editor does not touch them — which is
   precisely the preservation the request asks for.
5. **A summary section the résumé does not have.** It is added under its own
   heading (§2.4), which is the one place the editor writes a heading the
   candidate did not. Counted in `appended` and noted in `notes`; a résumé
   without a summary has nothing for the tailored summary to replace.

---

## 6. Live verification (2026-11-13)

`env\Scripts\python.exe scripts\verify_ws30_31.py` — **52/52 checks**, of which
30 are WS-31's. The run uploads a real `.docx` it writes itself (Georgia 13pt,
Skills *before* Summary, a separator line, a `Volunteering` section the renderer
has no concept of), tails it over real HTTP against a local fake provider,
downloads the deliverable through the API's own download route, and re-parses
it. The decisive results:

```
[PASS] the deliverable reports an in-place edit — mode=in_place skipped=[]
[PASS] the report counts the passages it rewrote — edits=4 appended=0 removed=1
[PASS] every run kept the uploaded font (Georgia) — fonts found: ['Georgia']
[PASS] every run kept the uploaded size (13pt) — sizes found: [13.0]
[PASS] the section order is the document's, not the renderer's
[PASS] the custom 'Volunteering' section survived
[PASS] the separator line survived
[PASS] the surviving skills line kept the document's own category format — Languages: Python
[PASS] a skills line with nothing selected is emptied, not left stale
[PASS] the deliverable re-parses with the facts intact
[PASS] the render report is persisted with the tailoring
[PASS] the uploaded file itself was never written to
[PASS] the tailoring prompt carried the format rules
[PASS] a text résumé is edited in place and reported as such — mode=in_place format=.txt
[PASS] the deliverable kept the uploaded file's line-ending convention
[PASS] the line count is unchanged by the edit — upload=16 lines, deliverable=16 lines
[PASS] a text deliverable is inspected as text, not scored as an unreadable DOCX
```

### The two defects the run found

Both were **scoring and format defects that no unit test looked for**, and both
now have a test verified to fail when its fix is reverted:

1. **A text deliverable was scored as an unreadable DOCX.** `analyze_ats`'s
   `_format_risks` opened the delivered file with `python-docx` regardless of
   its suffix, so a perfectly good `.txt` deliverable produced *"Could not
   inspect the rendered file: PackageNotFoundError"* — a
   `FORMAT_RISK_PENALTY` of 20 points off the ATS score for a file with nothing
   wrong with it. Fixed by dispatching on the real suffix; a text file is now
   inspected as text (its headings are checked against the parser's own
   vocabulary). Caught by the run because it asserted on the report rather than
   just on the file's contents.
2. **A text résumé's line endings were rewritten.** `Path.write_text`
   translates every `\n` to `\r\n` on Windows, so an LF résumé came back CRLF —
   a silent rewrite of the candidate's document by the feature whose entire
   promise is not to rewrite it. Fixed by reading and writing with
   `newline=""` and preserving whichever convention the upload used. The unit
   test for this fails on Windows without the fix.

### What the run confirmed that the tests could not

* The **route** passes the caller's own upload (`profile_row.file_path`), which
  is the wiring that makes the feature real rather than library-only; dropping
  it fails three API tests.
* The **deliverable survives the download route** and is re-parseable by the
  project's own parser — the WS-05 anti-fabrication gate still holds for an
  edited document, not just a rendered one.
* The **prompt really carries the FORMAT RULES**, so the model was asked for a
  bullet count that matches the document.

