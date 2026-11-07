import { Suspense, lazy, type ReactNode } from "react"
import { Navigate, type RouteObject } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { ActivityScreen } from "@/screens/activity-screen"
import { AdminScreen } from "@/screens/admin-screen"
import { JobDetailScreen } from "@/screens/job-detail-screen"
import { MatchesScreen } from "@/screens/matches-screen"
import { ApprovalsScreen } from "@/screens/approvals-screen"
import { OperationsScreen } from "@/screens/operations-screen"
import { OverviewScreen } from "@/screens/overview-screen"
import { ProfileScreen } from "@/screens/profile-screen"
import { ResumeScreen } from "@/screens/resume-screen"
import { SignInScreen } from "@/screens/sign-in-screen"
import { TailorIndexScreen, TailorJobScreen } from "@/screens/tailor-screen"
import { TrackerDetailScreen, TrackerScreen } from "@/screens/tracker-screen"

/**
 * The landing page is loaded lazily.
 *
 * It is the only public surface, and it carries the light field, the
 * interactive demonstration and the demonstration data — none of which a
 * signed-in operator needs. Splitting it means a console user never
 * downloads the marketing bundle, and a marketing visitor never downloads
 * the console. The fallback is a plain frame, not a spinner: the page is
 * usually a fraction of a second away.
 */
const LandingPage = lazy(() =>
  import("@/screens/landing/landing-page").then((module) => ({
    default: module.LandingPage,
  }))
)

function frame(node: ReactNode) {
  return <Suspense fallback={<div className="min-h-screen bg-night" />}>{node}</Suspense>
}

/**
 * The route tree.
 *
 * Two surfaces share this package, and they are kept apart on purpose:
 *
 * - `/` and `/sign-in` are **public** — the marketing page and the way in.
 * - `/app/*` is the **console**. Every screen there is a child of
 *   `AppShell`, which is where the identity gate lives: a caller with no
 *   session never sees a console screen.
 *
 * The list is exported (rather than built inside `App.tsx`) so that the
 * tests can mount exactly the same routing in a memory router.
 */
export const routes: RouteObject[] = [
  { path: "/", element: frame(<LandingPage />) },
  { path: "/sign-in", element: <SignInScreen /> },
  {
    path: "/app",
    element: <AppShell />,
    children: [
      { index: true, element: <OverviewScreen /> },
      { path: "resume", element: <ResumeScreen /> },
      { path: "profile", element: <ProfileScreen /> },
      { path: "matches", element: <MatchesScreen /> },
      { path: "matches/:jobId", element: <JobDetailScreen /> },
      { path: "tailor", element: <TailorIndexScreen /> },
      { path: "tailor/:jobId", element: <TailorJobScreen /> },
      { path: "approvals", element: <ApprovalsScreen /> },
      { path: "tracker", element: <TrackerScreen /> },
      { path: "tracker/:applicationId", element: <TrackerDetailScreen /> },
      { path: "activity", element: <ActivityScreen /> },
      { path: "operations", element: <OperationsScreen /> },
      { path: "admin", element: <AdminScreen /> },
    ],
  },
  // An unknown path is the landing page, not a blank console.
  { path: "*", element: <Navigate to="/" replace /> },
]
