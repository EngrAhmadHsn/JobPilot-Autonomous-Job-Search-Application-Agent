import { Navigate, type RouteObject } from "react-router-dom"

import { AppShell } from "@/components/layout/app-shell"
import { Placeholder } from "@/screens/placeholder"
import { ResumeScreen } from "@/screens/resume-screen"

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
        element: <Placeholder title="Matches" phase="C" />,
      },
      {
        path: "matches/:jobId",
        element: <Placeholder title="Job detail" phase="C" />,
      },
      {
        path: "tailor",
        element: <Placeholder title="Tailor" phase="D" />,
      },
      {
        path: "tailor/:jobId",
        element: <Placeholder title="Tailor" phase="D" />,
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
