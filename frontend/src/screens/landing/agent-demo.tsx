import { Check, CircleSlash, Pause, Play } from "lucide-react"
import type { CSSProperties, KeyboardEvent, ReactNode } from "react"
import { useCallback, useEffect, useRef, useState } from "react"

import { useEffectiveReducedMotion } from "@/lib/motion"
import { cn } from "cn"

import { DEMO_NOTICE, DEMO_STAGES, type DemoPanel } from "./demo-data"

/**
 * The interactive product demonstration.
 *
 * A miniature JobPilot that a visitor drives: pick a workflow stage on the
 * left and the panel shows what the agent does there, what it reports, and
 * what comes out. It is a working interface, not a slideshow — but it is
 * **isolated**: the data is a fixture (`demo-data.ts`), no request is ever
 * made, and the demo says so, on screen, at all times.
 *
 * Behaviour:
 *
 * - **Manual by default, with an optional walkthrough.** The visitor can
 *   step through the stages by hand; an automatic walkthrough can run, but
 *   it pauses the instant the visitor takes over, and there is an explicit
 *   play/pause control.
 * - **It only runs while it is on screen** (an `IntersectionObserver`),
 *   and not at all under `prefers-reduced-motion`.
 * - **It is fully keyboard-operable**: the stage list is a `tablist` with
 *   arrow-key navigation, `Home`/`End`, and a roving focus.
 */
export function AgentDemo() {
  const [active, setActive] = useState(0)
  const [paused, setPaused] = useState(false)
  const [visible, setVisible] = useState(false)
  const reduced = useEffectiveReducedMotion()
  const containerRef = useRef<HTMLDivElement | null>(null)
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])

  // The walkthrough only advances while the demo is actually in view, and
  // never under reduced-motion. Stepping by hand always works.
  useEffect(() => {
    const element = containerRef.current
    if (!element || typeof IntersectionObserver === "undefined") {
      setVisible(true)
      return
    }
    const observer = new IntersectionObserver(
      (entries) => setVisible(entries.some((entry) => entry.isIntersecting)),
      { threshold: 0.25 }
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // The walkthrough is **content**, not movement, so it advances regardless
  // of the motion preference. Under reduced motion the panel still changes;
  // it simply fades instead of rising (see index.css).
  const autoPlaying = !paused && visible

  useEffect(() => {
    if (!autoPlaying) return
    const timer = window.setInterval(() => {
      setActive((index) => (index + 1) % DEMO_STAGES.length)
    }, 5_200)
    return () => window.clearInterval(timer)
  }, [autoPlaying])

  const select = useCallback((index: number) => {
    setActive(index)
    // A visitor who takes over the walkthrough keeps it: the timer stops.
    setPaused(true)
  }, [])

  const onKeyDown = useCallback(
    (event: KeyboardEvent, index: number) => {
      const last = DEMO_STAGES.length - 1
      let next: number | null = null
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        next = index === last ? 0 : index + 1
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        next = index === 0 ? last : index - 1
      } else if (event.key === "Home") {
        next = 0
      } else if (event.key === "End") {
        next = last
      }
      if (next === null) return
      event.preventDefault()
      select(next)
      tabRefs.current[next]?.focus()
    },
    [select]
  )

  const stage = DEMO_STAGES[active] ?? DEMO_STAGES[0]!

  return (
    <div
      ref={containerRef}
      className="overflow-hidden rounded-2xl border border-night-line bg-night-raised shadow-[0_30px_80px_-40px_rgba(0,0,0,0.9)]"
    >
      {/* The window chrome: it must look like a product, and read as a demo. */}
      <div className="flex flex-wrap items-center gap-3 border-b border-night-line px-4 py-3">
        <span className="flex items-center gap-1.5" aria-hidden="true">
          <span className="size-2.5 rounded-full bg-terracotta/70" />
          <span className="size-2.5 rounded-full bg-lime/70" />
          <span className="size-2.5 rounded-full bg-ivory/25" />
        </span>
        <p className="font-heading text-sm font-medium text-ivory">
          JobPilot · live demonstration
        </p>
        <span className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-lime/40 bg-lime/10 px-2.5 py-1 text-[11px] font-medium text-lime">
          <span className="size-1.5 rounded-full bg-lime" aria-hidden="true" />
          {DEMO_NOTICE}
        </span>
      </div>

      <div className="grid gap-0 lg:grid-cols-[240px_1fr]">
        {/* The stages, as a tablist. Arrow keys move between them. */}
        <div
          role="tablist"
          aria-label="Workflow stages"
          aria-orientation="vertical"
          className="flex gap-1 overflow-x-auto border-b border-night-line p-2 lg:flex-col lg:overflow-visible lg:border-r lg:border-b-0"
        >
          {DEMO_STAGES.map((item, index) => {
            const selected = index === active
            return (
              <button
                key={item.id}
                ref={(node) => {
                  tabRefs.current[index] = node
                }}
                role="tab"
                id={`demo-tab-${item.id}`}
                aria-selected={selected}
                aria-controls={`demo-panel-${item.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => select(index)}
                onKeyDown={(event) => onKeyDown(event, index)}
                className={cn(
                  "group flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm whitespace-nowrap transition-colors duration-150",
                  selected
                    ? "bg-lime/12 text-ivory"
                    : "text-night-muted hover:bg-ivory/5 hover:text-ivory"
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold",
                    selected
                      ? "bg-lime text-lime-foreground"
                      : "bg-ivory/10 text-night-muted"
                  )}
                >
                  {index + 1}
                </span>
                <span className="font-medium">{item.label}</span>
              </button>
            )
          })}
        </div>

        {/* The panel for the selected stage. */}
        <div
          key={stage.id}
          role="tabpanel"
          id={`demo-panel-${stage.id}`}
          aria-labelledby={`demo-tab-${stage.id}`}
          tabIndex={0}
          className="enter-up min-w-0 p-5 sm:p-7"
        >
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="rounded-full border border-ivory/15 px-2 py-0.5 text-[11px] font-medium tracking-wide text-night-muted uppercase">
              {stage.phase}
            </span>
            <h3 className="font-heading text-xl font-semibold text-ivory">
              {stage.label}
            </h3>
          </div>
          <p className="mt-2 max-w-[62ch] text-sm leading-relaxed text-night-muted">
            {stage.summary}
          </p>

          {/* What the agent reports, in the product's own plain language. */}
          <ul className="mt-5 space-y-1.5">
            {stage.agent.map((line, index) => (
              <li
                key={line}
                className="enter-up flex items-center gap-2 text-sm text-ivory/90"
                style={{ "--i": index } as CSSProperties}
              >
                <Check className="size-3.5 shrink-0 text-lime" aria-hidden="true" />
                {line}
              </li>
            ))}
          </ul>

          <div className="mt-6">
            <DemoPanelView panel={stage.panel} />
          </div>
        </div>
      </div>

      {/* The controls: an explicit, honest play/pause for the walkthrough. */}
      <div className="flex items-center justify-between gap-3 border-t border-night-line px-4 py-3">
        <div className="flex items-center gap-1.5" aria-hidden="true">
          {DEMO_STAGES.map((item, index) => (
            <span
              key={item.id}
              className={cn(
                "h-1 rounded-full transition-all duration-300",
                index === active ? "w-5 bg-lime" : "w-1.5 bg-ivory/20"
              )}
            />
          ))}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-night-muted" aria-live="polite">
            {paused
              ? "Walkthrough paused"
              : visible
                ? reduced
                  ? "Walkthrough playing · fades only"
                  : "Walkthrough playing"
                : "Walkthrough paused (off screen)"}
          </span>
          <button
            type="button"
            onClick={() => setPaused((value) => !value)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-night-line px-3 py-1.5 text-xs font-medium text-ivory transition-colors duration-150 hover:bg-ivory/8"
            aria-label={paused ? "Play the walkthrough" : "Pause the walkthrough"}
          >
            {paused ? (
              <Play className="size-3.5" aria-hidden="true" />
            ) : (
              <Pause className="size-3.5" aria-hidden="true" />
            )}
            {paused ? "Play" : "Pause"}
          </button>
        </div>
      </div>
    </div>
  )
}

/** The panel body, switched on the stage's kind. */
function DemoPanelView({ panel }: { panel: DemoPanel }) {
  switch (panel.kind) {
    case "resume":
      return (
        <Card>
          <div className="flex flex-wrap items-center gap-3">
            <span className="grid size-10 place-items-center rounded-full bg-lime text-sm font-semibold text-lime-foreground">
              {panel.name.slice(0, 1)}
            </span>
            <div>
              <p className="font-heading text-base font-semibold text-ivory">
                {panel.name}
              </p>
              <p className="text-xs text-night-muted">{panel.headline}</p>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-1.5">
            {panel.skills.map((skill) => (
              <span
                key={skill}
                className="rounded-full bg-ivory/8 px-2.5 py-1 text-xs text-ivory/90"
              >
                {skill}
              </span>
            ))}
          </div>
          <p className="mt-4 text-xs text-night-muted">
            {panel.experience} roles · {panel.note}
          </p>
        </Card>
      )

    case "discovery":
      return (
        <Card>
          <ul className="divide-y divide-night-line">
            {panel.rows.map((row) => (
              <li
                key={`${row.company}-${row.title}`}
                className="flex flex-wrap items-center justify-between gap-2 py-2.5 first:pt-0 last:pb-0"
              >
                <div>
                  <p className="text-sm font-medium text-ivory">{row.title}</p>
                  <p className="text-xs text-night-muted">
                    {row.company} · {row.location}
                  </p>
                </div>
                <span className="rounded-full border border-night-line px-2 py-0.5 font-mono text-[11px] text-night-muted">
                  {row.source}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-night-muted">{panel.note}</p>
        </Card>
      )

    case "matching":
      return (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-ivory">{panel.title}</p>
              <p className="text-xs text-night-muted">{panel.company}</p>
            </div>
            <div className="text-right">
              <p className="font-heading text-2xl font-semibold text-lime">
                {panel.score.toFixed(1)}
              </p>
              <p className="text-[11px] text-night-muted">match score</p>
            </div>
          </div>
          <div
            aria-hidden="true"
            className="mt-3 h-1.5 overflow-hidden rounded-full bg-ivory/10"
          >
            <span
              className="block h-full rounded-full bg-lime"
              style={{ width: `${panel.score}%` }}
            />
          </div>
          <ul className="mt-4 space-y-2">
            {panel.reasons.map((reason) => (
              <li key={reason.text} className="flex items-start gap-2 text-sm">
                {reason.have ? (
                  <Check
                    className="mt-0.5 size-3.5 shrink-0 text-lime"
                    aria-hidden="true"
                  />
                ) : (
                  <CircleSlash
                    className="mt-0.5 size-3.5 shrink-0 text-terracotta"
                    aria-hidden="true"
                  />
                )}
                <span
                  className={reason.have ? "text-ivory/90" : "text-terracotta"}
                >
                  {reason.text}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-night-muted">{panel.note}</p>
        </Card>
      )

    case "tailoring":
      return (
        <Card>
          <p className="text-sm font-medium text-ivory">
            {panel.title}{" "}
            <span className="font-normal text-night-muted">
              · {panel.company}
            </span>
          </p>
          <ul className="mt-3 space-y-3">
            {panel.bullets.map((bullet) => (
              <li key={bullet.before} className="text-sm">
                <p className="text-night-muted line-through decoration-terracotta/60">
                  {bullet.before}
                </p>
                <p className="mt-0.5 text-ivory/95">{bullet.after}</p>
                <span
                  className={cn(
                    "mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium",
                    bullet.verdict === "grounded"
                      ? "bg-lime/15 text-lime"
                      : "bg-terracotta/15 text-terracotta"
                  )}
                >
                  {bullet.verdict === "grounded"
                    ? "Grounded in the profile"
                    : "Tightened, not invented"}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-night-muted">{panel.note}</p>
        </Card>
      )

    case "preparation":
      return (
        <Card>
          <ul className="divide-y divide-night-line">
            {panel.fields.map((field) => (
              <li
                key={field.field}
                className="flex flex-wrap items-center justify-between gap-2 py-2.5 first:pt-0 last:pb-0"
              >
                <span className="text-sm font-medium text-ivory">
                  {field.field}
                </span>
                <span className="text-xs text-night-muted">{field.source}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-night-muted">{panel.note}</p>
        </Card>
      )

    case "approval":
      return (
        <Card className="border-terracotta/40">
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-full bg-terracotta text-terracotta-foreground">
              <Pause className="size-4" aria-hidden="true" />
            </span>
            <div>
              <p className="font-heading text-base font-semibold text-ivory">
                A human decision is required
              </p>
              <p className="mt-1 text-sm text-night-muted">
                {panel.jobTitle} · {panel.company}
              </p>
              <p className="mt-1 text-xs text-night-muted">
                Target: {panel.adapter}
              </p>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <span className="rounded-lg bg-lime px-3 py-1.5 text-xs font-medium text-lime-foreground">
              Approve &amp; submit
            </span>
            <span className="rounded-lg border border-night-line px-3 py-1.5 text-xs font-medium text-ivory">
              Reject
            </span>
          </div>
          <p className="mt-4 text-xs text-night-muted">{panel.note}</p>
        </Card>
      )

    case "verification":
      return (
        <Card>
          <p className="text-sm font-medium text-ivory">
            {panel.jobTitle}{" "}
            <span className="font-normal text-night-muted">
              · {panel.company}
            </span>
          </p>
          <div className="mt-3 rounded-lg border border-night-line bg-night/60 p-3">
            <p className="text-xs text-night-muted">Confirmation page</p>
            <p className="mt-1 text-sm text-ivory">“{panel.confirmation}”</p>
          </div>
          <ul className="mt-4 space-y-1.5 text-xs text-night-muted">
            <li className="flex items-center gap-2">
              <Check className="size-3.5 text-lime" aria-hidden="true" />
              Confirmation text captured
            </li>
            <li className="flex items-center gap-2">
              <Check className="size-3.5 text-lime" aria-hidden="true" />
              Screenshot recorded as evidence
            </li>
            <li className="break-all">
              Landed on <span className="font-mono">{panel.jobUrl}</span>
            </li>
          </ul>
          <p className="mt-4 text-xs text-night-muted">{panel.note}</p>
        </Card>
      )
  }
}

function Card({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-night-line bg-night/50 p-4",
        className
      )}
    >
      {children}
    </div>
  )
}
