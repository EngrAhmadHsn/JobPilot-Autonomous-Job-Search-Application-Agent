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
          <h1
            className="enter-up max-w-[19ch] font-heading text-4xl leading-[1.05] font-semibold tracking-tight text-balance text-ivory sm:text-6xl"
            style={{ "--i": 0 } as CSSProperties}
          >
            Your job search runs itself.
            <span className="block text-lime">You still make the calls.</span>
          </h1>

          <p
            className="enter-up mt-6 max-w-[58ch] text-lg leading-relaxed text-night-muted"
            style={{ "--i": 1 } as CSSProperties}
          >
            JobPilot reads your résumé, finds the roles that fit, and says why
            each one does. For the roles worth your time it writes the tailored
            résumé and fills in the application — then it waits. Nothing reaches
            an employer until you approve it.
          </p>

          <div
            className="enter-up mt-8 flex flex-wrap items-center gap-3"
            style={{ "--i": 2 } as CSSProperties}
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
              See how it works
            </a>
          </div>

          <p
            className="enter-up mt-5 text-xs text-night-muted"
            style={{ "--i": 3 } as CSSProperties}
          >
            You approve every application · every action is on your record ·
            evidence backs every result
          </p>
        </div>
      </section>

      {/* --------------------------- the demonstration --------------------- */}
      <section id="demo" className="mx-auto max-w-6xl scroll-mt-20 px-6 pb-20">
        <div className="mb-6 max-w-[62ch]">
          <h2 className="font-heading text-3xl font-semibold tracking-tight text-ivory sm:text-4xl">
            See it work
          </h2>
          <p className="mt-3 text-night-muted">
            Pick a stage of the process and look at what the agent produces.
            Sample data, a real interface — nothing here touches your account
            or a live job board.
          </p>
        </div>
        <AgentDemo />
      </section>

      {/* ---------------------------- the loop ----------------------------- */}
      <section id="how" className="scroll-mt-20 border-t border-night-line">
        <div ref={loopRef} className="mx-auto max-w-6xl px-6 py-20">
          <div className="max-w-[62ch]">
            <h2 className="font-heading text-3xl font-semibold tracking-tight text-ivory sm:text-4xl">
              It works the whole process
            </h2>
            <p className="mt-3 text-night-muted">
              A search returns a list and stops. JobPilot keeps going: it reads
              your résumé, searches, matches, tailors the résumé, prepares the
              application — and stops at the one step that is yours, the
              decision to send it.
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
              What each screen does
            </h2>
            <p className="mt-3 text-night-muted">
              Every claim below is a screen you can open. Nothing here is a
              plan for later.
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
                Nothing important happens without you, and you can see
                everything that did. Two colours carry that promise everywhere
                in the product:
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
              See the demo again
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
          JobPilot. A demonstration product: the agent submits only to
          controlled test sites, and only after you approve.
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
    body: "It reads your résumé and searches the boards you configured.",
  },
  {
    phase: "Reason",
    body: "It scores every listing against your experience and shows the reasons behind the score.",
  },
  {
    phase: "Plan",
    body: "It picks the roles worth an application, and what each one needs from your résumé.",
  },
  {
    phase: "Act",
    body: "It tailors your résumé to the job and fills in the application fields from your profile.",
  },
  {
    phase: "Observe",
    body: "After you approve, it reads the page the employer showed back.",
  },
  {
    phase: "Evaluate",
    body: "It compares that page with what it sent, and reports what it found — verified, or honestly unverified.",
  },
  {
    phase: "Adapt",
    body: "It retries what is safe to retry and leaves the rest to you.",
  },
  {
    phase: "Escalate",
    body: "It stops and asks whenever the decision is yours: approve, answer a question, resolve a block.",
  },
]

const CAPABILITIES: { title: string; body: string }[] = [
  {
    title: "Résumé → structured profile",
    body: "Upload a DOCX, TXT or MD file and get a typed profile: skills, roles, dates, education. It reports what the document says, and nothing it does not.",
  },
  {
    title: "Jobs from real boards",
    body: "Greenhouse, Lever, Ashby and Remotive, turned into one shape and de-duplicated before anything is scored.",
  },
  {
    title: "Matching that explains itself",
    body: "Every listing gets a score with its reasons: which requirements you meet, and which you are missing.",
  },
  {
    title: "Résumés tailored to the job",
    body: "Your résumé is rewritten toward the role, then checked against the original. A claim with no support is dropped, not written.",
  },
  {
    title: "Applications prepared, not fired",
    body: "Each application is assembled with matching fields and the source of every value — then it waits for you.",
  },
  {
    title: "Evidence, or it did not happen",
    body: "An approved submission records the confirmation text, the URL and a screenshot. Without that, the result is unverified, never “submitted”.",
  },
]

const TRUST: { title: string; body: string }[] = [
  {
    title: "Approval before every submission",
    body: "Nothing goes out until a person approves it. The agent prepares the application; you decide whether it is sent.",
  },
  {
    title: "Decisions you can follow",
    body: "Every match carries its reasons, and every change to an application carries who made it and when.",
  },
  {
    title: "A record you can read",
    body: "Uploads, searches, approvals and submissions are recorded, and you can read your own trail at any time.",
  },
  {
    title: "Your data stays yours",
    body: "Your résumés and applications are private to your account. Another account cannot reach them, and an id that is not yours answers exactly like one that does not exist.",
  },
  {
    title: "Your sign-in stays on the server",
    body: "The browser holds no token a script could read; it carries a session cookie the server can revoke at any moment.",
  },
]
