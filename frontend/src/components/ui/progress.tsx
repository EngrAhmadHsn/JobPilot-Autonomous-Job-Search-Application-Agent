import { Progress as ProgressPrimitive } from "@animate-ui/react/primitives/base-ui/progress"
import { cn } from "cn"

/*
  WS-34: the progress bar, on the Base UI primitive.

  It renders the accessible role and value itself; the console's job is
  only the surface — a track in the muted fill and an indicator in the
  forest. The agent's own working state has a home already: the
  `.agent-progress` sweep in `index.css`, which a caller can layer onto
  the indicator's class when the bar is showing live agent work.
*/
function Progress({
  className,
  children,
  ...props
}: ProgressPrimitive.Root.Props) {
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      className={cn("flex w-full flex-col gap-2", className)}
      {...props}
    >
      {children}
      <ProgressPrimitive.Track
        data-slot="progress-track"
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
      >
        <ProgressPrimitive.Indicator
          data-slot="progress-indicator"
          className="h-full rounded-full bg-primary transition-[left,width] duration-300 ease-out"
        />
      </ProgressPrimitive.Track>
    </ProgressPrimitive.Root>
  )
}

export { Progress, ProgressPrimitive }
