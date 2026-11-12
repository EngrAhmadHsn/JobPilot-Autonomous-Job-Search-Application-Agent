import { Suspense, lazy, type ReactNode } from "react"
import { Navigate, type RouteObject } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { SignInScreen } from "@/screens/sign-in-screen"

/**
 * Every screen is loaded lazily, and that is the whole point of this file.
 *
 * The previous version imported eleven console screens at module scope and
 * split only the landing page. Because static imports populate the entry
 * chunk, the split did nothing: `dist/index.html` loaded an 855 kB `index-*.js`
 * before it could discover the landing chunk, so a marketing visitor
 * downloaded the entire console and a console user downloaded both. The
 * comment above the landing split claimed a visitor "never downloads the
 * console"; the code could not keep that promise.
 *
 * Splitting each screen means a visitor to `/` downloads the landing page and
 * its providers, nothing else, and a console user downloads one screen at a
 * time as they navigate. `AppShell` and `SignInScreen` stay eager: the shell
 * is the frame around every console route and the gate that decides whether a
 * caller sees a screen at all, and sign-in is the door. Loading either one
 * lazily would trade a real delay for a saving of a few kilobytes.
 */
const LandingPage = lazy(() =>
  import("@/screens/landing/landing-page").then((module) => ({
    default: module.LandingPage,
  }))
)
const OverviewScreen = lazy(() =>
  import("@/screens/overview-screen").then((module) => ({
    default: module.OverviewScreen,
  }))
)
const ResumeScreen = lazy(() =>
  import("@/screens/resume-screen").then((module) => ({
    default: module.ResumeScreen,
  }))
)
const ProfileScreen = lazy(() =>
  import("@/screens/profile-screen").then((module) => ({
    default: module.ProfileScreen,
  }))
)
const MatchesScreen = lazy(() =>
  import("@/screens/matches-screen").then((module) => ({
    default: module.MatchesScreen,
  }))
)
const JobDetailScreen = lazy(() =>
  import("@/screens/job-detail-screen").then((module) => ({
    default: module.JobDetailScreen,
  }))
)
const TailorIndexScreen = lazy(() =>
  import("@/screens/tailor-screen").then((module) => ({
    default: module.TailorIndexScreen,
  }))
)
const TailorJobScreen = lazy(() =>
  import("@/screens/tailor-screen").then((module) => ({
    default: module.TailorJobScreen,
  }))
)
const ApprovalsScreen = lazy(() =>
  import("@/screens/approvals-screen").then((module) => ({
    default: module.ApprovalsScreen,
  }))
)
const TrackerScreen = lazy(() =>
  import("@/screens/tracker-screen").then((module) => ({
    default: module.TrackerScreen,
  }))
)
const TrackerDetailScreen = lazy(() =>
  import("@/screens/tracker-screen").then((module) => ({
    default: module.TrackerDetailScreen,
  }))
)
const ActivityScreen = lazy(() =>
  import("@/screens/activity-screen").then((module) => ({
    default: module.ActivityScreen,
  }))
)
const OperationsScreen = lazy(() =>
  import("@/screens/operations-screen").then((module) => ({
    default: module.OperationsScreen,
  }))
)
const AdminScreen = lazy(() =>
  import("@/screens/admin-screen").then((module) => ({
    default: module.AdminScreen,
  }))
)

/**
 * A screen that is still arriving.
 *
 * A plain frame rather than a spinner, because the chunk is usually a fraction
 * of a second away and a spinner that flashes is worse than a moment of calm.
 * The frame keeps the page's own background, so the swap from it to the screen
 * is a fade of content rather than a flash of colour.
 */
function frame(node: ReactNode) {
  return (
    <Suspense
      fallback={
        <div
          className="min-h-screen bg-background"
          role="status"
          aria-label="Loading the screen"
        />
      }
    >
      {node}
    </Suspense>
  )
}

/**
 * The route tree.
 *
 * Two surfaces share this package, and they are kept apart on purpose:
 *
 * - `/` and `/sign-in` are **public** — the marketing page and the way in.
 * - `/app/*` is the **console**. Every screen there is a child of `AppShell`,
 *   which is where the identity gate lives: a caller with no session never
 *   sees a console screen.
 *
 * The list is exported (rather than built inside `App.tsx`) so that the tests
 * can mount exactly the same routing in a memory router.
 */
export const routes: RouteObject[] = [
  { path: "/", element: frame(<LandingPage />) },
  { path: "/sign-in", element: <SignInScreen /> },
  {
    path: "/app",
    element: <AppShell />,
    /*
      The children are wrapped once here rather than per route. `AppShell`
      renders its chrome immediately, so only the outlet's content suspends: a
      thumb tap on the nav keeps the header and the drawer in place while the
      next screen arrives, instead of replacing the whole page with a frame.
    */
    children: [
      { index: true, element: frame(<OverviewScreen />) },
      { path: "resume", element: frame(<ResumeScreen />) },
      { path: "profile", element: frame(<ProfileScreen />) },
      { path: "matches", element: frame(<MatchesScreen />) },
      { path: "matches/:jobId", element: frame(<JobDetailScreen />) },
      { path: "tailor", element: frame(<TailorIndexScreen />) },
      { path: "tailor/:jobId", element: frame(<TailorJobScreen />) },
      { path: "approvals", element: frame(<ApprovalsScreen />) },
      { path: "tracker", element: frame(<TrackerScreen />) },
      {
        path: "tracker/:applicationId",
        element: frame(<TrackerDetailScreen />),
      },
      { path: "activity", element: frame(<ActivityScreen />) },
      { path: "operations", element: frame(<OperationsScreen />) },
      { path: "admin", element: frame(<AdminScreen />) },
    ],
  },
  // An unknown path is the landing page, not a blank console.
  { path: "*", element: <Navigate to="/" replace /> },
]
