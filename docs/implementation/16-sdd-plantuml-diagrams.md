# WS-16: PlantUML diagrams for the Software Design Document

**Status:** done 2026-10-22
**Milestone:** M5
**Depends on:** WS-13 (the operator console), WS-14 (identity and isolation)

## 1. Why this workstream exists

The Software Design Document, `docs/SDD.docx`, was written on 2026-10-22 with the
diagrams drawn as plain boxes in a plotting script. They are legible, but they are
not UML, and a supervisor reading a design document expects the standard
notations: a class diagram, an object diagram, an entity-relationship diagram,
and the behavioural diagrams that show how the system behaves over time.

This workstream replaces the hand-drawn structural and behavioural diagrams with
PlantUML sources that are kept in the repository, and adds the four kinds the
current document does not have at all.

## 2. Scope

### 2.1 In scope

- A shared PlantUML style file that matches the document's typography.
- Twelve PlantUML sources under `docs/diagrams/`, each rendering to a PNG.
- A repeatable render script, `scripts/render_diagrams.py`.
- The SDD rebuilt with the PlantUML figures in place of the hand-drawn ones, with
  the new figures and the text that explains them.

### 2.2 Out of scope

- The data flow diagram. A classic DFD is not a UML notation, and the hand-drawn
  one reads better. It stays.
- The console's screen map. A screen map is a navigation model, not UML. It stays.
- Any change to the runtime code. This workstream adds documents and a build
  script.

## 3. The diagram set

| # | Source file | Notation | Where it lands in the SDD |
|---|---|---|---|
| 1 | `architecture-packages.puml` | Package | 3.1, the layers of the backend |
| 2 | `architecture-components.puml` | Component | 3.1, the components and their interfaces |
| 3 | `class-domain.puml` | Class | 3.2, the candidate, the job and the match |
| 4 | `class-tailoring.puml` | Class | 3.2, the classes the tailoring produces |
| 5 | `class-application.puml` | Class | 3.2, the application workflow and identity |
| 6 | `object-snapshot.puml` | Object | 3.2, the objects at one moment |
| 7 | `sequence-job-refresh.puml` | Sequence | 3.2, the job refresh |
| 8 | `activity-refresh.puml` | Activity | 3.2, the refresh and its two gates |
| 9 | `sequence-application-submit.puml` | Sequence | 3.2, the application submission |
| 10 | `activity-tailoring.puml` | Activity | 3.2, the tailoring pipeline |
| 11 | `state-application-lifecycle.puml` | State | 3.2, the application status lifecycle |
| 12 | `usecase-console.puml` | Use case | 5.16, who uses the system |
| 13 | `erd-account-data.puml` | Entity-relationship | 4.1, the records an account owns |
| 14 | `erd-workflow.puml` | Entity-relationship | 4.1, the shared corpus and the lifecycle |
| 15 | `storage-layout.puml` | Package | 4.1, the data directory |

The plan first named twelve diagrams. It grew to fifteen, and three of them
were split, because a diagram that cannot be read on the page is not a
diagram:

- The class diagram was split into three. One diagram with eighteen classes
  was twenty-one inches wide, which prints its thirteen point text at under
  four points on a six inch column.
- The entity-relationship diagram was split in two, for the same reason.
- The activity diagrams were rewritten with fewer and longer steps, which
  turned them from narrow strips into full-width figures.

## 4. Design decisions

- **Sources are committed, the jar is not.** The `.puml` files live in
  `docs/diagrams/` so a diagram can be edited and re-rendered. PlantUML itself is
  a build-time tool; the jar is not committed and `scripts/render_diagrams.py`
  reports clearly how to supply it.
- **One style file.** `docs/diagrams/_style.puml` holds the shared skin
  parameters, so every diagram uses the same face, the same white background and
  the same border weight as the document.
- **The diagrams are drawn from the code, not from the prose.** The class
  diagram's attributes and methods are the fields and functions in `src/`; the
  entity-relationship diagram's columns are the nine Alembic revisions; the
  state diagram's transitions are `ALLOWED_TRANSITIONS` in
  `src/applications/tracking.py`.
- **ASCII only in the sources.** PlantUML reads the sources with the platform
  default encoding, which is Cp1252 on this machine, so the sources avoid
  characters that would change meaning.

## 5. Plan

- **Phase A, the style and the build script.** Write `_style.puml` and
  `scripts/render_diagrams.py`. The script finds a PlantUML jar from
  `PLANTUML_JAR`, from `tools/plantuml.jar`, or from `plantuml` on the path, and
  renders every source to `docs/diagrams/png/`. It fails with a message that
  says where to put the jar.
- **Phase B, the structural diagrams.** The package, component, class, object and
  entity-relationship diagrams. These are the ones with the most room to be
  wrong, so they are written first and checked against the code.
- **Phase C, the behavioural diagrams.** The two sequences, the two activities
  and the state machine.
- **Phase D, the rebuild.** The SDD build script is changed to take the
  PlantUML PNGs, the figure numbering is reworked, and the text that explains
  each new figure is written. The document is rebuilt, rendered, and every page
  is read.
- **Phase E, the acceptance run.** `scripts/render_diagrams.py` runs clean from
  a fresh checkout, the SDD post-check reports no errors, and the figures are
  listed in the table of figures with the right page numbers.

## 6. How the work is verified

- Every `.puml` file is rendered and the PNG is read and inspected, because a
  PlantUML diagram that renders is not the same as one that reads.
- The render script computes the size each diagram prints at and refuses one
  whose text would fall below seven points. This is a mechanical check, and it
  is what caught the three diagrams that had to be split.
- The entity-relationship diagram's columns are checked against the live
  database schema, and the state diagram's transitions against the code.
- The SDD is rendered to PDF and each page is reviewed, as with the first
  version.
- The document self-check script must report no errors.

## 7. Risks

- **A diagram that renders but does not read.** PlantUML will happily lay out an
  unreadable graph. Mitigation: every PNG is inspected and the source is edited
  until it reads.
- **The jar is not on the machine that reviews the document.** Mitigation: the
  PNGs are committed, so the document can be opened and read without PlantUML.
  Only a change to a diagram needs the tool.
- **The diagram set outgrows the section it sits in.** Mitigation: the section
  text names each figure and says what it shows, so a reader never meets a
  figure without a sentence.
- **The figure numbers drift from the order.** The captions carry a sequence
  field, so Word renumbers them in the order they appear. The build script
  refuses a body whose figures are not in number order, because the text that
  refers to them would then point at the wrong figure.
