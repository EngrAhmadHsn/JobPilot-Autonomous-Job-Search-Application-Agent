# WS-32 assist-mode pilot — the first live run (2026-11-15)

The raw measurement from the pilot's first run against **real Greenhouse boards**. The
narrative and the defects it establishes are in
[`../../implementation/32-submission-readiness.md`](../../implementation/32-submission-readiness.md) §5.5;
these files are the evidence behind it.

**Nothing was submitted.** The run filled one real application form and stopped before
`Submit application` — no application reached any employer. The target was Cloudflare's
"AI Security Research & Red Team Engineer" posting, with a clearly-fake demo candidate
("Ada Lovelace", `ada.lovelace@example.com`) and the `.txt` résumé beside this file.
Seven boards were measured; three corpus postings probed turned out to be closed.

| File | What it is |
|---|---|
| `01_pilot_as_is.json` | `scripts/pilot_assist.py` exactly as it ships, against a live board. It stops with `needs_human` in 3.7 s and types nothing, because `_drive_form` returns at `plan.unresolved` before the fill. |
| `02_fill_star_normalised.json` | The same planner and the same `_fill_control`, with **only** the trailing `*` stripped from the lookup. 9 fields filled instead of 4; `dom_readback` shows the values really in the controls. This is the proof that the required-marker breaks the locator. |
| `03_liveness.json` | 12 corpus postings probed for liveness. A **closed** posting answers 200 + a redirect to `<company>?error=true`, so liveness is not readable from the status code. 9 live, 3 closed. |
| `04_planner_unresolved.json` | Seven live boards through `build_form_plan(read_controls(page), demo_facts)`: known / unknown / unresolved counts per board, and every unresolved label. Unresolved runs 11–25 on one provider. |
| `05_dom_labels.json` | The DOM of the Cloudflare form: every input with its `labels`, `aria-label` and `aria-labelledby`, plus `get_by_label` counts for `"First Name"` vs `"First Name*"` (1 vs 0). |
| `filled_form.png` | The filled Cloudflare form, screenshot before the run ended. Name, email, phone, LinkedIn, legal name, country and the attached résumé are visible; `Submit application` is untouched. |
| `demo_resume.txt` | The fake résumé the run attached. |

Reproduce with the scripts recorded in the workstream doc §5.5. They live in the session's
scratch directory and are not committed — the JSON above is the durable record.
