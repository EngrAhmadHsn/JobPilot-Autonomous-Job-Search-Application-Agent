import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { AnimateUIProvider } from "@animate-ui/react/provider"

import "./index.css"
import App from "./App.tsx"
import { ThemeProvider } from "@/components/theme-provider.tsx"
import { initMotion } from "@/lib/motion"

/*
  Resolve the motion preference **before** the first render, so the
  `<html data-motion>` attribute the CSS keys on is already correct and no
  content is ever painted with the wrong setting.
*/
initMotion()

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/*
      The console opens on the warm ivory canvas. The theme is still the
      operator's to change — the account menu switches it — but the default
      is the light one, because the identity of the product is a warm page
      with ink on it, not a dark dashboard.
    */}
    <ThemeProvider defaultTheme="light">
      {/*
        WS-48: the motion clock.

        `@animate-ui/react`'s primitives read their timings from this
        context, and so does every hand-written `motion` value in the console
        (through `useTempoTransition`). `tempo={1}` is the library's own
        scale — the recipes' durations are the intended feel, so this is
        stated rather than inherited by accident, and it is the single dial
        if the whole console ever needs to move faster or slower.

        `reducedMotion="user"` is not a nicety: it is what makes the
        primitives ask the visitor (through `ReducedMotionConfig`) before they
        travel, scale or rotate. Fades and blurs stay, which is the point —
        reduced motion means less movement, not less feedback. The console's
        own `<html data-motion>` CSS block in `index.css` covers the
        keyframed entrances on the same principle.
      */}
      <AnimateUIProvider tempo={1} reducedMotion="user">
        <App />
      </AnimateUIProvider>
    </ThemeProvider>
  </StrictMode>
)
