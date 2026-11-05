import type { CSSProperties } from "react"
import { Link } from "react-router-dom"

import { useReveal } from "@/hooks/use-reveal"
import { MotionToggle } from "@/components/motion-toggle"

import { AgentDemo } from "./agent-demo"
import { COLOR_FIELD_FALLBACK, ColorField } from "./color-field"

/**
 * The public landing page.
 *
 * The front door is the same desk as the console, after dark: a warm
 * near-black forest canvas, ivory type, and the identity's own colours —
 * lime for the agent, terracotta for the human — used as light. The hero's
 * light follows the pointer; the interactive demonstration below it lets a
 * visitor drive the real workflow with sample data.
 *
 * Every claim on this page is one the code supports. There is no "apply to
 * thousands of jobs while you sleep": submission is approval-gated, the
 * targets are controlled, and every action leaves evidence.
 */
export function LandingPage() {
  const loopRef = useReveal<HTMLDivElement>()
  const productRef = useReveal<HTMLDivElement>()
  const trustRef = useReveal<HTMLDivElement>()

  return (
    <div className="night-surface min-h-screen">
      <SiteHeader />

      {/* ------------------------------- hero ------------------------------ */}
      <section className="relative isolate overflow-hidden">
        <div
          aria-hidden="true"
          className="absolute inset-0"
          style={{ backgroundImage: COLOR_FIELD_FALLBACK }}
        />
        <ColorField />
        <div className="relative mx-auto max-w-6xl px-6 pt-20 pb-16 sm:pt-28 sm:pb-24">
          {/*
            The hero arrives once, on load: a short stagger down the column so
            the first thing a visitor sees is alive before they have moved the
            pointer. `.enter-up` is a one-shot CSS animation (delay from the
            `--i` index) — it is not a scroll reveal and not a loop, and
            `prefers-reduced-motion` flattens it to an instant appearance.
          */}
          <p
            className="enter-up inline-flex items-center gap-2 rounded-full border border-night-line bg-night-soft/80 px-3 py-1 text-xs text-night-muted backdrop-blur"
            style={{ "--i": 0 } as CSSProperties}
          >
            <span className="size-1.5 rounded-full bg-lime" aria-hidden="true" />
            Autonomous job search · with a human at the wheel
          </p>

          <h1
            className="enter-up mt-6 max-w-[19ch] font-heading text-4xl leading-[1.05] font-semibold tracking-tight text-balance text-ivory sm:text-6xl"
            style={{ "--i": 1 } as CSSProperties}
          >
            Your job search, on autopilot.
            <span className="block text-lime">Your decisions, in your hands.</span>
          </h1>

          <p
            className="enter-up mt-6 max-w-[58ch] text-lg leading-relaxed text-night-muted"
            style={{ "--i": 2 } as CSSProperties}
          >
            JobPilot finds roles that fit, explains why each one does, tailors
            your résumé without inventing a word, and prepares each application
            for your review. It never submits anything until you approve it —
            and it records the evidence when it does.
          </p>

          <div
            className="enter-up mt-8 flex flex-wrap items-center gap-3"
            style={{ "--i": 3 } as CSSProperties}
          >
            <Link
              to="/sign-in"
              className="inline-flex h-11 items-center rounded-xl bg-lime px-5 text-sm font-semibold text-lime-foreground transition-transform duration-150 hover:scale-[1.03] active:scale-[0.97]"
            >
              Open the console
            </Link>
            <a
              href="#demo"
              className="inline-flex h-11 items-center rounded-xl border border-night-line px-5 text-sm font-semibold text-ivory transition-colors duration-150 hover:bg-ivory/8"
            >
              See it work
            </a>
          </div>

          <p
            className="enter-up mt-5 text-xs text-night-muted"
            style={{ "--i": 4 } as CSSProperties}
          >
            Approval required before every submission · an audit record for
            every action · no credential ever leaves the server
          </p>
        </div>
      </section>

      {/* --------------------------- the demonstration --------------------- */}
      <section id="demo" className="mx-auto max-w-6xl scroll-mt-20 px-6 pb-20">
        <div className="mb-6 max-w-[62ch]">
          <h2 className="font-heading text-3xl font-semibold tracking-tight text-ivory sm:text-4xl">
            Walk the loop yourself
          </h2>
          <p className="mt-3 text-night-muted">
            Pick any stage of the agent&apos;s working loop and see what it
            does there, what it reports, and what comes out. It is a real
            interface running on sample data — nothing here touches your
            account or a live job board.
          </p>
        </div>
        <AgentDemo />
      </section>

      {/* ---------------------------- the loop ----------------------------- */}
      <section id="how" className="scroll-mt-20 border-t border-night-line">
        <div ref={loopRef} className="mx-auto max-w-6xl px-6 py-20">
          <div className="max-w-[62ch]">
            <h2 className="font-heading text-3xl font-semibold tracking-tight text-ivory sm:text-4xl">
              An agent, not a filter
            </h2>
            <p className="mt-3 text-night-muted">
              A filter returns a list. An agent runs a loop: it perceives, it
              reasons, it plans, it acts, it observes what happened, it
              evaluates the result, and it adapts — or stops and asks you.
              That loop is the product.
            </p>
          </div>

          <ol className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {LOOP.map((step, index) => (
              <li
                key={step.phase}
                data-reveal=""
                style={{ "--i": index % 4 } as CSSProperties}
                className="rounded-xl border border-night-line bg-night-soft/60 p-5"
              >
                <div className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="grid size-6 place-items-center rounded-full bg-lime/15 font-mono text-[11px] text-lime"
                  >
                    {index + 1}
                  </span>
                  <span className="font-heading text-sm font-semibold tracking-wide text-ivory uppercase">
                    {step.phase}
                  </span>
                </div>
                <p className="mt-3 text-sm leading-relaxed text-night-muted">
                  {step.body}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* -------------------------- the capabilities ----------------------- */}
      <section id="product" className="scroll-mt-20 border-t border-night-line">
        <div ref={productRef} className="mx-auto max-w-6xl px-6 py-20">
          <div className="max-w-[62ch]">
            <h2 className="font-heading text-3xl font-semibold tracking-tight text-ivory sm:text-4xl">
              What it actually does
            </h2>
            <p className="mt-3 text-night-muted">
              Only what the code supports. Each of these is a screen in the
              console, backed by a real endpoint.
            </p>
          </div>

          <div className="mt-10 grid gap-4 md:grid-cols-2">
            {CAPABILITIES.map((capability, index) => (
              <article
                key={capability.title}
                data-reveal=""
                style={{ "--i": index % 2 } as CSSProperties}
                className="rounded-2xl border border-night-line bg-night-soft/50 p-6"
              >
                <h3 className="font-heading text-lg font-semibold text-ivory">
                  {capability.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-night-muted">
                  {capability.body}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* --------------------------- trust & control ----------------------- */}
      <section id="trust" className="scroll-mt-20 border-t border-night-line">
        <div ref={trustRef} className="mx-auto max-w-6xl px-6 py-20">
          <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <div>
              <h2 className="font-heading text-3xl font-semibold tracking-tight text-ivory sm:text-4xl">
                You stay in control
              </h2>
              <p className="mt-3 max-w-[52ch] text-night-muted">
                A system that acts on your behalf has to be legible and
                interruptible. Two colours carry that promise everywhere in
                the product:
              </p>
              <div className="mt-6 space-y-3">
                <div className="flex items-center gap-3">
                  <span
                    aria-hidden="true"
                    className="size-4 rounded-[5px] bg-lime"
                  />
                  <p className="text-sm text-ivory">
                    <span className="font-semibold">Lime</span> — the agent did
                    it.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span
                    aria-hidden="true"
                    className="size-4 rounded-[5px] bg-terracotta"
                  />
                  <p className="text-sm text-ivory">
                    <span className="font-semibold">Terracotta</span> — a human
                    did, or a human must.
                  </p>
                </div>
              </div>
            </div>

            <ul className="space-y-4">
              {TRUST.map((item, index) => (
                <li
                  key={item.title}
                  data-reveal=""
                  style={{ "--i": index } as CSSProperties}
                  className="rounded-xl border border-night-line bg-night-soft/50 p-5"
                >
                  <h3 className="font-heading text-base font-semibold text-ivory">
                    {item.title}
                  </h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-night-muted">
                    {item.body}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* ------------------------------ final CTA -------------------------- */}
      <section className="border-t border-night-line">
        <div className="mx-auto max-w-6xl px-6 py-20 text-center">
          <h2 className="mx-auto max-w-[24ch] font-heading text-3xl font-semibold tracking-tight text-balance text-ivory sm:text-4xl">
            Point it at your résumé. Keep your hand on the wheel.
          </h2>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link
              to="/sign-in"
              className="inline-flex h-11 items-center rounded-xl bg-lime px-6 text-sm font-semibold text-lime-foreground transition-transform duration-150 hover:scale-[1.03] active:scale-[0.97]"
            >
              Create your account
            </Link>
            <a
              href="#demo"
              className="inline-flex h-11 items-center rounded-xl border border-night-line px-6 text-sm font-semibold text-ivory transition-colors duration-150 hover:bg-ivory/8"
            >
              Revisit the demo
            </a>
          </div>
        </div>
      </section>

      <SiteFooter />
    </div>
  )
}

/** The public site's header: the mark, a few anchors, and the way in. */
function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-night-line bg-night/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3.5">
        <Link to="/" className="flex items-center gap-2.5">
          <span
            aria-hidden="true"
            className="grid size-8 place-items-center rounded-[10px] bg-lime"
          >
            <svg viewBox="0 0 24 24" className="size-[18px]" fill="none">
              <path
                d="M6.5 3.75h7.25L18 8v12.25H6.5z"
                className="fill-ivory"
                stroke="#173d32"
                strokeWidth="1.4"
                strokeLinejoin="round"
              />
              <path
                d="M9.6 9.1h5.2"
                stroke="#173d32"
                strokeWidth="2.4"
                strokeLinecap="round"
              />
            </svg>
          </span>
          <span className="font-heading text-[15px] font-semibold tracking-tight text-ivory">
            JobPilot
          </span>
        </Link>

        <nav aria-label="Sections" className="hidden items-center gap-6 md:flex">
          <a
            href="#how"
            className="text-sm text-night-muted transition-colors hover:text-ivory"
          >
            How it works
          </a>
          <a
            href="#product"
            className="text-sm text-night-muted transition-colors hover:text-ivory"
          >
            Product
          </a>
          <a
            href="#trust"
            className="text-sm text-night-muted transition-colors hover:text-ivory"
          >
            Trust
          </a>
        </nav>

        <div className="flex items-center gap-2">
          {/*
            The motion control, where it is visible without scrolling. Many
            machines report `prefers-reduced-motion` for reasons unrelated to
            the visitor (Windows' "Animation effects" off), so the page offers
            a way to see its motion without changing the OS setting.
          */}
          <MotionToggle tone="night" className="hidden sm:inline-flex" />
          <Link
            to="/sign-in"
            className="inline-flex h-9 items-center rounded-lg border border-night-line px-4 text-sm font-medium text-ivory transition-colors duration-150 hover:bg-ivory/8"
          >
            Sign in
          </Link>
        </div>
      </div>
    </header>
  )
}

function SiteFooter() {
  return (
    <footer className="border-t border-night-line">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-xs text-night-muted">
        <p>
          JobPilot · the agentic job applier. A demonstration product; the
          agent submits only to controlled targets, and only after approval.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <span>Motion</span>
          <MotionToggle tone="night" />
          <Link to="/sign-in" className="underline underline-offset-4 hover:text-ivory">
            Open the console
          </Link>
        </div>
      </div>
    </footer>
  )
}

const LOOP: { phase: string; body: string }[] = [
  {
    phase: "Perceive",
    body: "Reads your résumé into a structured profile and searches configured job boards for listings.",
  },
  {
    phase: "Reason",
    body: "Scores each listing against the profile with a hybrid of lexical and semantic signals, and explains the score.",
  },
  {
    phase: "Plan",
    body: "Decides which roles are worth an application, and what each one needs from your résumé.",
  },
  {
    phase: "Act",
    body: "Tailors the résumé under a factuality check, and fills the application's fields from the profile.",
  },
  {
    phase: "Observe",
    body: "After an approved submission, reads the confirmation page and records the evidence.",
  },
  {
    phase: "Evaluate",
    body: "Compares what it intended with what the page showed — verified, or honestly unverified.",
  },
  {
    phase: "Adapt",
    body: "Retries the recoverable, and escalates the rest to you instead of guessing.",
  },
  {
    phase: "Escalate",
    body: "When a decision is yours — approve, answer a question, resolve a block — the agent stops and waits.",
  },
]

const CAPABILITIES: { title: string; body: string }[] = [
  {
    title: "Résumé → structured profile",
    body: "Upload a DOCX, TXT or MD file and get a typed candidate profile — skills, roles, dates, education. Extraction only; the parser adds nothing the document does not say.",
  },
  {
    title: "Discovery across real boards",
    body: "Greenhouse, Lever and Remotive, normalized into one listing shape, de-duplicated and screened before anything is scored.",
  },
  {
    title: "Matching that explains itself",
    body: "A hybrid score per listing, with the reasons it ranked: which requirements you meet, and which are genuinely missing.",
  },
  {
    title: "Tailoring under a factuality check",
    body: "Résumé lines are rewritten toward the role and then validated against the original. A claim with no support is dropped, not written.",
  },
  {
    title: "Applications prepared, not fired",
    body: "Each application is assembled with matching fields and a provenance for every value — and then it waits for you.",
  },
  {
    title: "Evidence, or it did not happen",
    body: "Approved submissions record the confirmation text, the URL and a screenshot. No confirmation means 'unverified', never 'success'.",
  },
]

const TRUST: { title: string; body: string }[] = [
  {
    title: "Approval before every submission",
    body: "Nothing is submitted until a person approves the prepared application. The agent's role is to make the decision easy, not to make it.",
  },
  {
    title: "Explainable decisions",
    body: "Every match carries its reasons; every state change carries an actor and a timestamp in the application's history.",
  },
  {
    title: "A real audit trail",
    body: "Uploads, searches, matches, prepares, approvals, submissions and every guard that tripped are recorded, readable by the account they belong to.",
  },
  {
    title: "Tenant isolation by construction",
    body: "Authorization lives in the data layer, not the screens. Your résumés and applications are yours; another account cannot reach them, and a foreign id is indistinguishable from a missing one.",
  },
  {
    title: "Secrets never reach the browser",
    body: "The session is an HttpOnly cookie; the console holds no token. Job-board text is treated as data, never as instructions.",
  },
]
