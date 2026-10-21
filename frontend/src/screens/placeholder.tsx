import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/**
 * A screen that is not built yet.
 *
 * Phase A builds the shell, the client and the routing; each later phase
 * replaces one of these with the real screen. It exists so that the shell
 * is usable (and testable) from the first commit.
 */
export function Placeholder({
  title,
  phase,
}: {
  title: string
  phase: string
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">
          This screen is built in phase {phase}.
        </p>
      </CardContent>
    </Card>
  )
}
