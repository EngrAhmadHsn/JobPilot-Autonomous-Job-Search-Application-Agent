import { useEffect, useRef } from "react"

import { usePointerCapable } from "@/hooks/use-media-query"
import { useEffectiveReducedMotion } from "@/lib/motion"

/**
 * The light field.
 *
 * A pointer-reactive wash of light on the night canvas: the cursor stirs
 * a few soft blooms of the identity's own colours — the agent's **lime**
 * and the human's **terracotta**, over a low forest warmth — and the light
 * lags behind the hand rather than snapping to it, like a lamp moving over
 * a desk.
 *
 * The rules it keeps, because a moving background is easy to get wrong:
 *
 * - **It never runs when nothing is happening.** The render loop starts on
 *   the first pointer move and **stops** once the blooms have settled and
 *   the pointer has left. An idle page does zero work per frame.
 * - **It is off on touch and under `prefers-reduced-motion`.** The
 *   component renders nothing in those cases and the section's own static
 *   gradient is the fallback.
 * - **It is `pointer-events: none` and `aria-hidden`.** It can never
 *   intercept a click, a hover, or a focus target, and it is never
 *   announced to a screen reader.
 * - **Intensity answers speed, subtly.** A fast sweep brightens the wash a
 *   little; a slow one is dim. It is feedback, not decoration.
 *
 * Canvas 2D is deliberately the simplest technique that does the job:
 * additively-blended radial gradients. A WebGL shader would buy a softer
 * falloff, but it would also add a second rendering path, a shader to
 * maintain, and a GPU cost — for a wash this soft, it is not worth it.
 */

/** One bloom: a position, a target, a radius, a colour and its alpha. */
interface Bloom {
  x: number
  y: number
  /** Where the bloom is easing toward, in device pixels. */
  targetX: number
  targetY: number
  /** Relative depth: 0 is right under the hand, 1 trails far behind. */
  depth: number
  radius: number
  color: [number, number, number]
  /** Base alpha before the speed term. */
  alpha: number
}

/** The identity's colours, as RGB triples the canvas can blend. */
const LIME: [number, number, number] = [217, 243, 106]
const TERRACOTTA: [number, number, number] = [241, 214, 200]
const FOREST: [number, number, number] = [122, 155, 109]

/**
 * The largest extent one bloom may be sized from, in CSS pixels.
 *
 * The radius used to scale with `max(width, height)`, so on a 2560 px
 * display the deepest bloom reached roughly 1,500 px from the cursor —
 * wider than the hero is tall. Near the bottom of the hero the wash was
 * still bright when the section clipped it, so the boundary against the
 * next section read as a hard step between two shades of the same night.
 * The field is a lamp over a desk, not a flood: the extent is capped, and
 * the falloff therefore ends inside the hero on every screen.
 */
const MAX_BLOOM_EXTENT = 900

/**
 * The vertical fade applied to the canvas.
 *
 * The cap bounds the radius; this makes the bottom edge *invisible* rather
 * than merely dim, so no bloom can end on the section boundary whatever the
 * pointer does.
 */
const FIELD_FADE =
  "linear-gradient(to bottom, rgba(0,0,0,1) 0%, rgba(0,0,0,1) 72%, rgba(0,0,0,0) 100%)"

export function ColorField({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  // The **effective** preference: "System" follows the OS, but a visitor who
  // chose "Full" motion still gets the field on a machine that reports reduce.
  const reduced = useEffectiveReducedMotion()
  const pointerCapable = usePointerCapable()
  const enabled = pointerCapable && !reduced

  useEffect(() => {
    if (!enabled) return
    const canvas = canvasRef.current
    const host = canvas?.parentElement
    if (!canvas || !host) return
    const context = canvas.getContext("2d")
    if (!context) return

    let width = 0
    let height = 0
    let dpr = 1
    let running = false
    let frame = 0
    /** 0..1 — how energetic the current gesture is, eased over time. */
    let energy = 0
    /** Where the hand is, in device pixels, and whether it is inside. */
    let pointerX = -1
    let pointerY = -1
    let inside = false

    const blooms: Bloom[] = [
      { depth: 0.0, radius: 0.55, color: LIME, alpha: 0.32 },
      { depth: 0.28, radius: 0.7, color: TERRACOTTA, alpha: 0.22 },
      { depth: 0.55, radius: 0.95, color: FOREST, alpha: 0.34 },
      { depth: 0.85, radius: 1.2, color: LIME, alpha: 0.12 },
    ].map((b) => ({
      ...b,
      x: 0,
      y: 0,
      targetX: 0,
      targetY: 0,
    })) as Bloom[]

    const anchor = (bloom: Bloom) => {
      const baseX = width / 2
      const baseY = height * 0.42
      const px = inside ? pointerX : baseX
      const py = inside ? pointerY : baseY
      bloom.targetX = px + (baseX - px) * bloom.depth
      bloom.targetY = py + (baseY - py) * bloom.depth
    }

    const resize = () => {
      const rect = host.getBoundingClientRect()
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = Math.max(1, Math.round(rect.width * dpr))
      height = Math.max(1, Math.round(rect.height * dpr))
      canvas.width = width
      canvas.height = height
      canvas.style.width = `${rect.width}px`
      canvas.style.height = `${rect.height}px`
      if (!inside) {
        for (const bloom of blooms) {
          bloom.x = width / 2
          bloom.y = height * 0.42
        }
      }
      draw()
    }

    const draw = () => {
      context.clearRect(0, 0, width, height)
      context.globalCompositeOperation = "lighter"
      // The scale the blooms are sized from is capped, so a wide monitor
      // gets the same lamp as a laptop instead of a wall-to-wall wash.
      const extent = Math.min(Math.max(width, height), MAX_BLOOM_EXTENT * dpr)
      for (const bloom of blooms) {
        const radius = bloom.radius * extent * 0.5
        const gradient = context.createRadialGradient(
          bloom.x,
          bloom.y,
          0,
          bloom.x,
          bloom.y,
          radius
        )
        const alpha = bloom.alpha * (0.6 + energy * 0.7)
        const [r, g, b] = bloom.color
        gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${alpha})`)
        gradient.addColorStop(0.45, `rgba(${r}, ${g}, ${b}, ${alpha * 0.32})`)
        gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`)
        context.fillStyle = gradient
        context.fillRect(
          bloom.x - radius,
          bloom.y - radius,
          radius * 2,
          radius * 2
        )
      }
    }

    const step = () => {
      let settled = true
      for (const bloom of blooms) {
        anchor(bloom)
        // A per-depth easing: the shallow bloom keeps up, the deep one
        // trails, which is what reads as "light lagging behind the hand".
        const ease = 0.16 - bloom.depth * 0.09
        const dx = bloom.targetX - bloom.x
        const dy = bloom.targetY - bloom.y
        bloom.x += dx * ease
        bloom.y += dy * ease
        if (Math.abs(dx) > 0.4 || Math.abs(dy) > 0.4) settled = false
      }
      // The energy always decays, so the wash dims the moment the hand rests.
      energy *= 0.94
      draw()
      if (settled && !inside && energy < 0.01) {
        running = false
        return
      }
      frame = window.requestAnimationFrame(step)
    }

    const start = () => {
      if (running) return
      running = true
      frame = window.requestAnimationFrame(step)
    }

    const onPointerMove = (event: PointerEvent) => {
      const rect = host.getBoundingClientRect()
      const nextX = (event.clientX - rect.left) * dpr
      const nextY = (event.clientY - rect.top) * dpr
      if (inside) {
        const distance = Math.hypot(nextX - pointerX, nextY - pointerY)
        // A screen-width of travel in one move is "fast"; map it into 0..1
        // and keep only a fraction, so the brightness breathes rather than
        // flashing.
        energy = Math.min(1, energy + distance / (Math.max(width, 1) * 0.5) * 0.5)
      }
      pointerX = nextX
      pointerY = nextY
      inside = true
      start()
    }

    const onPointerLeave = () => {
      inside = false
      if (running) start()
    }

    const observer =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(resize)
        : null
    observer?.observe(host)
    resize()

    host.addEventListener("pointermove", onPointerMove)
    host.addEventListener("pointerleave", onPointerLeave)
    return () => {
      observer?.disconnect()
      host.removeEventListener("pointermove", onPointerMove)
      host.removeEventListener("pointerleave", onPointerLeave)
      window.cancelAnimationFrame(frame)
    }
  }, [enabled])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={className}
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        // The blooms are additive light on a dark canvas; a soft multiplier
        // would make an opaque sheet instead.
        opacity: 0.9,
        // The light ends inside the hero, never on its boundary.
        maskImage: FIELD_FADE,
        WebkitMaskImage: FIELD_FADE,
      }}
    />
  )
}

/**
 * The static fallback the night hero carries when the field is off.
 *
 * It is the same wash, frozen: two soft radial gradients in the identity's
 * colours. It is a real gradient, not a placeholder — a touch visitor gets
 * a composed hero, not an empty one. Its horizontal radius is capped for
 * the same reason the canvas is: above ~1200 px a percentage radius paints
 * across the whole viewport, and the wash would end on the section's edge.
 */
export const COLOR_FIELD_FALLBACK =
  "radial-gradient(ellipse min(60vw, 620px) 60% at 28% 32%, color-mix(in oklab, #d9f36a 22%, transparent), transparent 70%), radial-gradient(ellipse min(52vw, 540px) 55% at 74% 60%, color-mix(in oklab, #f1d6c8 20%, transparent), transparent 72%)"
