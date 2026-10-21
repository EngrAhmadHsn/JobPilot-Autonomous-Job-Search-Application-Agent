import { Navigate, type RouteObject } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { Placeholder } from "@/screens/placeholder"
import { JobDetailScreen } from "@/screens/job-detail-screen"
import { MatchesScreen } from "@/screens/matches-screen"
import { ResumeScreen } from "@/screens/resume-screen"
import { TailorIndexScreen, TailorJobScreen } from "@/screens/tailor-screen"

/**
 * The console's routes.
 *
 * The list is exported (rather than built inside `App.tsx`) so that the
 * tests can mount exactly the same routing in a memory router.
 */
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/resume" replace /> },
      {
        path: "resume",
        element: <ResumeScreen />,
      },
      {
        path: "matches",
        element: <MatchesScreen />,
      },
      {
        path: "matches/:jobId",
        element: <JobDetailScreen />,
      },
      {
        path: "tailor",
        element: <TailorIndexScreen />,
      },
      {
        path: "tailor/:jobId",
        element: <TailorJobScreen />,
      },
      {
        path: "approvals",
        element: <Placeholder title="Approvals" phase="E" />,
      },
      {
        path: "tracker",
        element: <Placeholder title="Tracker" phase="F" />,
      },
      {
        path: "tracker/:applicationId",
        element: <Placeholder title="Tracker" phase="F" />,
      },
      {
        path: "operations",
        element: <Placeholder title="Operations" phase="G" />,
      },
    ],
  },
]
