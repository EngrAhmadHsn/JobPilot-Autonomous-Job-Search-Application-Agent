import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import App from "./App.tsx"
import { ThemeProvider } from "@/components/theme-provider.tsx"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/*
      The console opens on the warm ivory canvas. The theme is still the
      operator's to change — the account menu switches it — but the default
      is the light one, because the identity of the product is a warm page
      with ink on it, not a dark dashboard.
    */}
    <ThemeProvider defaultTheme="light">
      <App />
    </ThemeProvider>
  </StrictMode>
)
