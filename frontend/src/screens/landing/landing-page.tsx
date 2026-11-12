import type { CSSProperties } from "react"
import { Link } from "react-router-dom"

import { useDocumentTitle } from "@/hooks/use-document-title"
import { useReveal } from "@/hooks/use-reveal"
import { MotionToggle } from "@/components/motion-toggle"
import { SkipToContent } from "@/components/common/skip-to-content"

import { AgentDemo } from "./agent-demo"
import { COLOR_FIELD_FALLBACK, ColorField } from "./color-field"

/**
 * The public landing page.
 *
 * The front door is the same desk as the console, after dark: a warm
 * near-black forest canvas, ivory type, and the identity's own colours
 * (lime for the agent, terracotta for the human) used as light. The hero's
 * light follows the pointer; the demonstration below it lets a visitor drive
 * the real workflow with sample data.
 *
 * Every claim on this page is one the code supports. There is no "apply to
 * thousands of jobs while you sleep": submission is approval-gated, the
 * targets are controlled, and every action leaves evidence.
 *
 * Copy rules this page keeps:
 *
 * - One primary action, and it goes to the form a new visitor needs. The
 *   hero and the closing card ask for an account; only the header asks to
 *   sign in.
 * - No abstract phase vocabulary. The loop section describes the four things
 *   one application passes through, in the words the console uses.
 * - No empty intensifiers, no "not X but Y" framing, and no sentence that
 *   only restates the previous one.
 */
export function LandingPage() {
  const loopRef = useReveal<HTMLDivElement>()
  const productRef = useReveal<HTMLDivElement>()
  const trustRef = useReveal<HTMLDivElement>()

  useDocumentTitle("Job search that waits for you")

  return (
    <div className="night-surface min-h-screen">
      {/*
        The skip link comes before the header so it is the first thing Tab
        reaches. The header stays outside `<main>`; the content inside it is
        the landmark a screen reader can jump to.
      */}
      <SkipToContent />
      <SiteHeader />

      <main id="main-content" className="scroll-mt-24">
        {/* ----------------------------- hero ------------------------------ */}
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
            `--i` index). It is not a scroll reveal and not a loop, and
            `prefers-reduced-motion` flattens it to an instant appearance.
          */}
            <h1
              className="enter-up max-w-[20ch] font-heading text-4xl leading-[1.05] font-semibold tracking-tight text-balance text-ivory sm:text-6xl"
              style={{ "--i": 0 } as CSSProperties}
            >
              JobPilot finds the roles and fills in the forms.
              <span className="block text-lime">
                You approve what gets sent.
              </span>
            </h1>

            <p
              className="enter-up mt-6 max-w-[52ch] text-lg leading-relaxed text-night-muted"
              style={{ "--i": 1 } as CSSProperties}
            >
              Upload a résumé. JobPilot ranks every opening against it, shows
              what you match and what you don't, then tailors the résumé and
              prepares the application. It stops there and waits for you.
            </p>

            <div
              className="enter-up mt-8 flex flex-wrap items-center gap-3"
              style={{ "--i": 2 } as CSSProperties}
            >
              {/*
              The primary action asks for an account, so it must land on the
              create form. `state.mode` is what the sign-in screen reads to
              choose which form to open; without it a new visitor arrives at a
              sign-in form and is asked for a password they do not have.
            */}
              <Link
                to="/sign-in"
                state={{ mode: "create" }}
                className="inline-flex h-11 items-center rounded-xl bg-lime px-5 text-sm font-semibold text-lime-foreground transition-transform duration-150 hover:scale-[1.03] active:scale-[0.96]"
              >
                Create your account
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
              style={{ "--i": 3 } as CSSProperties}
            >
              Approval before every submission. Every action recorded. Every
              result backed by evidence.
            </p>
          </div>
        </section>

        {/* --------------------------- the demonstration --------------------- */}
        <section id="demo" className="mx-auto max-w-6xl px-6 pb-20">
          <div className="mb-6 max-w-[62ch]">
            <h2 className="font-heading text-3xl font-semibold tracking-tight text-ivory sm:text-4xl">
              See it work
            </h2>
            <p className="mt-3 text-night-muted">
              Pick a stage and look at what comes out. Sample data, nothing
              submitted.
            </p>
          </div>
          <AgentDemo />
        </section>

        {/* ---------------------------- the loop ----------------------------- */}
        <section id="how" className="border-t border-night-line">
          <div ref={loopRef} className="mx-auto max-w-6xl px-6 py-20">
            <div className="max-w-[62ch]">
              <h2 className="font-heading text-3xl font-semibold tracking-tight text-ivory sm:text-4xl">
                What happens to one application
              </h2>
              <p className="mt-3 text-night-muted">
                Four steps. The last one is yours.
              </p>
            </div>

            <ol className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {LOOP.map((step, index) => (
                <li
                  key={step.title}
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
                    <span className="font-heading text-sm font-semibold text-ivory">
                      {step.title}
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
        <section id="product" className="border-t border-night-line">
          <div ref={productRef} className="mx-auto max-w-6xl px-6 py-20">
            <div className="max-w-[62ch]">
              <h2 className="font-heading text-3xl font-semibold tracking-tight text-ivory sm:text-4xl">
                What you get
              </h2>
              <p className="mt-3 text-night-muted">
                Each one is a screen you can open today.
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
        <section id="trust" className="border-t border-night-line">
          <div ref={trustRef} className="mx-auto max-w-6xl px-6 py-20">
            <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
              <div>
                <h2 className="font-heading text-3xl font-semibold tracking-tight text-ivory sm:text-4xl">
                  You stay in control
                </h2>
                <p className="mt-3 max-w-[52ch] text-night-muted">
                  Two colours show who did what:
                </p>
                <div className="mt-6 space-y-3">
                  <div className="flex items-center gap-3">
                    <span
                      aria-hidden="true"
                      className="size-4 rounded-[5px] bg-lime"
                    />
                    <p className="text-sm text-ivory">
                      <span className="font-semibold">Lime</span>: the agent did
                      it.
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span
                      aria-hidden="true"
                      className="size-4 rounded-[5px] bg-terracotta"
                    />
                    <p className="text-sm text-ivory">
                      <span className="font-semibold">Terracotta</span>: a
                      person did it, or a person must.
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
            <h2 className="mx-auto max-w-[26ch] font-heading text-3xl font-semibold tracking-tight text-balance text-ivory sm:text-4xl">
              Try it with your own résumé.
            </h2>
            <p className="mx-auto mt-4 max-w-[52ch] text-sm leading-relaxed text-night-muted">
              It takes one document to start. You keep the last word on every
              application.
            </p>
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              <Link
                to="/sign-in"
                state={{ mode: "create" }}
                className="inline-flex h-11 items-center rounded-xl bg-lime px-6 text-sm font-semibold text-lime-foreground transition-transform duration-150 hover:scale-[1.03] active:scale-[0.96]"
              >
                Create your account
              </Link>
              <a
                href="#demo"
                className="inline-flex h-11 items-center rounded-xl border border-night-line px-6 text-sm font-semibold text-ivory transition-colors duration-150 hover:bg-ivory/8"
              >
                See the demo again
              </a>
            </div>
          </div>
        </section>
      </main>

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
                className="fill-ivory stroke-forest"
                strokeWidth="1.4"
                strokeLinejoin="round"
              />
              <path
                d="M9.6 9.1h5.2"
                className="stroke-forest"
                strokeWidth="2.4"
                strokeLinecap="round"
              />
            </svg>
          </span>
          <span className="font-heading text-[15px] font-semibold tracking-tight text-ivory">
            JobPilot
          </span>
        </Link>

        <nav
          aria-label="Sections"
          className="hidden items-center gap-6 md:flex"
        >
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
            What it does
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
          JobPilot is a demonstration product. It submits only after you
          approve.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <span>Motion</span>
          <MotionToggle tone="night" />
          <Link
            to="/sign-in"
            className="underline underline-offset-4 hover:text-ivory"
          >
            Open the console
          </Link>
        </div>
      </div>
    </footer>
  )
}

/**
 * The four things one application passes through.
 *
 * Each body states the outcome, not the mechanism. A visitor deciding whether
 * to try this needs to know what they end up holding, not how it is computed.
 */
const LOOP: { title: string; body: string }[] = [
  {
    title: "A profile",
    body: "Your résumé, read into skills, roles and dates. Nothing added.",
  },
  {
    title: "Ranked matches",
    body: "Every opening scored, with the reasons and the gaps.",
  },
  {
    title: "A prepared application",
    body: "A résumé tailored to the role, and the form filled in.",
  },
  {
    title: "A decision, then evidence",
    body: "You approve. Then you get proof it landed.",
  },
]

const CAPABILITIES: { title: string; body: string }[] = [
  {
    title: "Matches you can argue with",
    body: "Every score shows what you match and what you miss.",
  },
  {
    title: "A résumé that stays true",
    body: "Every line traces back to your original résumé.",
  },
  {
    title: "Applications with a paper trail",
    body: "Check every field before you approve it.",
  },
  {
    title: "Evidence, or the word unverified",
    body: "A submission is verified only if there is proof. Otherwise it says so.",
  },
]

const TRUST: { title: string; body: string }[] = [
  {
    title: "Approval gates every submission",
    body: "The agent prepares. You send.",
  },
  {
    title: "A record of every action",
    body: "Everything is written to your account's history.",
  },
  {
    title: "Your data stays in your account",
    body: "Your résumés and applications are private to you.",
  },
]
