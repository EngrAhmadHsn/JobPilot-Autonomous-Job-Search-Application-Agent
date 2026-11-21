---
name: bombadil
description: Property-based testing for the JobPilot web UI with Bombadil (@antithesishq/bombadil) — write TypeScript property specifications (invariants over time), run the autonomous browser explorer against the running console, and interpret failures.
---

# Bombadil — property-based testing for the console

Bombadil (Antithesis, MIT-licensed source) **autonomously explores a running
UI** and checks *properties* — conditions that must hold in every state or over
time — instead of example-based scripts. Where the Playwright specs pin
particular flows and the `ws41-audit.mjs` sweep pins one snapshot per viewport,
Bombadil generates thousands of action sequences and checks the invariants in
all of them. It fills the **property-based / fuzz** bucket of the testing
taxonomy: harder bugs, earlier, from the same running app.

- Repo: <https://github.com/antithesishq/bombadil> (Rust harness + TS spec language)
- Manual: <https://antithesishq.github.io/bombadil/>
- npm: `@antithesishq/bombadil` (ships the `bombadil` binary + TS types)

## Install

```bash
npm install --save-dev @antithesishq/bombadil
```

```jsonc
// package.json
{ "scripts": { "bombadil": "bombadil browser test --time-limit=1m" } }
```

**Platform: macOS and Linux only, natively.** This project develops on
Windows — run Bombadil under **WSL** (against `http://127.0.0.1:5191`, which
WSL reaches on the same host) or in CI (GitHub Actions, ubuntu-latest). Do not
add the dependency until a run environment exists; the skill's value without
the binary is writing specifications that CI executes.

## Run

```bash
# Defaults only (uncaught exceptions, unhandled rejections, error logs,
# HTTP 4xx/5xx, semantic-HTML navigation and clicks):
bombadil browser test --time-limit=1m http://localhost:5191/app

# With a specification (properties + actions):
bombadil browser test --time-limit=5m http://localhost:5191/app specs/console.ts
```

The explorer needs a **signed-in console**: seed the cookie first (the
`ws42-shot.mjs` login flow shows the form-encoded `POST /api/auth/cookie/login`)
or add a login action generator to the spec. Read-only exploration is the
default posture — see the honesty note below.

## Specification language (ES module, TypeScript optional)

A spec is a plain module whose top-level exports are **properties** and
**action generators**. Nothing else may be exported from the entry module.

```typescript
// Re-export the defaults, then add console-specific ones:
export * from "@antithesishq/bombadil/browser/defaults";
```

### Extract → Cell → property

`extract` runs **in the browser** on every state Bombadil captures; it returns
a stateful `Cell<T>` read via `.current`. `state.document` / `state.window` are
the live page's own objects.

```typescript
import { always, extract } from "@antithesishq/bombadil/browser";

const h1Count = extract(
  (state) => state.document.querySelectorAll("h1").length
);

// `always` takes a THUNK — it is evaluated in every state.
export const exactlyOneH1 = always(() => h1Count.current === 1);
```

### Temporal operators

| Operator | Holds when |
|---|---|
| `always(x)` | x holds in this and every future state |
| `eventually(x)` | x holds in this or some future state |
| `next(x)` | x holds in the next state |
| `now(x)` | x holds in this state (use as preconditions) |

Connectives are methods on formulas: `.and(y)`, `.or(y)`, `.implies(y)`,
`.not()`. The canonical shape — *precondition implies response, eventually
cleared*:

```typescript
const approveClicked = extract(() => /* ... */);
const gateVisible = extract(() => !!state_document.querySelector("[data-approval-gate]"));

export const approvalFlow = always(() =>
  now(() => approveClicked.current).implies(
    now(() => gateVisible.current).and(eventually(() => !gateVisible.current))
  )
);
```

(`gateVisible` must itself be an `extract` cell; `now(...)` wraps single-state
conditions so the connectives compose.)

### Custom action generators

`actions(() => ActionTemplate[])` runs per state; return `[]` when the action
makes no sense there. Weight branches by array position helpers per the manual.

```typescript
import { actions, extract } from "@antithesishq/bombadil/browser";

const submitButton = extract((state) => {
  const el = state.document.querySelector("[data-approval-submit]");
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return r.width > 0 ? { fingerprint: getFingerprint(el), point: { x: r.left + r.width / 2, y: r.top + r.height / 2 } } : null;
});

export const clickApprove = actions(() =>
  submitButton.current ? [{ Click: submitButton.current }] : []
);
```

## Console properties worth writing (starting set)

Grounded in this repo's own contracts — each is a property the unit suite
checks at one point in time; Bombadil checks it across **every explored state**:

- `noUncaughtExceptions`, no error-severity console logs, no 4xx/5xx (defaults —
  the 429-looks-like-logout class of bug surfaces here).
- `exactlyOneH1` — every screen, every state (the ws41 sweep's contract).
- `noHorizontalScroll` — `document.documentElement.scrollWidth <= clientWidth`
  (the rail-tooltip defect class).
- `queuedNeverReadsSent` — extract the application rows' status text; assert no
  state shows "Queued"/"Awaiting review" together with "Submitted" wording for
  the same card (the legend's honesty contract, fuzzed).
- `approvalGatePresent` — on the approvals route, the human-decision gate and
  its copy are in the DOM in every state where a packet is awaiting decision.
- `emptyStatesAreHonest` — no "NaN", "undefined", or `[object Object]` text
  anywhere (`document.body.textContent` regex).

## Honesty and safety rules for this repo

- Exploration **clicks things**. Point custom actions only at read-only
  affordances, or accept that Bombadil may exercise mutations the way a user
  would — it never fabricates data and never bypasses the approval gate, but a
  fuzzer *will* press "Queue the refresh". Run against the local dev database,
  never against anything shared.
- The approval gate must never be a property like "approve always succeeds" —
  the system hands back to the human by design. Assert the gate exists and the
  handoff copy stays truthful.

## Failure output

A failing property reports the violating state sequence with screenshots and
the extracted cell values — treat it like the compare_image ledger: reproduce,
classify (defect vs test wrong), fix, rerun.
