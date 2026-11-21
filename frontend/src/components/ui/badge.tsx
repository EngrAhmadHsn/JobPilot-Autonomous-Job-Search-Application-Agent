import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

/*
  WS-34: the generic badge. A badge is a small label that classifies the
  thing beside it, so it never carries meaning by colour alone — whatever
  renders inside it has to read as text first. The variants are the
  neutral paper family; the *semantic* statuses (agent lime, human
  terracotta) have their own component in `status-badge.tsx`, which is
  the one screens should reach for when a backend state is being shown.

  WS-48: rebased on the canonical base-nova badge — same parts
  (`useRender` + `mergeProps`, `data-slot="badge"`, the six variants with
  the anchor-wrapped hover states), restyled to our tokens. Three
  deliberate deltas from the canonical classes, so screens don't move:

  - `px-2.5` keeps the WS-34 chip padding (canonical is `px-2`).
  - No fixed `h-5`: the canonical badge pins its height, which would clip
    the wrapping skill chips in `profile/key-skills` (they override
    `whitespace-normal` and must grow with their content).
  - `transition-colors`, not the canonical `transition-all` — a badge only
    ever changes colour, and `transition-all` is a flagged pattern in the
    repo's motion contract.
*/
const badgeVariants = cva(
  "group/badge inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-4xl border border-transparent px-2.5 py-0.5 text-xs font-medium whitespace-nowrap transition-colors focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a]:hover:bg-primary/80",
        secondary:
          "bg-secondary text-secondary-foreground [a]:hover:bg-secondary/80",
        destructive:
          "bg-destructive/10 text-destructive focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:focus-visible:ring-destructive/40 [a]:hover:bg-destructive/20",
        outline:
          "border-border bg-card text-foreground [a]:hover:bg-muted [a]:hover:text-muted-foreground",
        ghost:
          "hover:bg-muted hover:text-muted-foreground dark:hover:bg-muted/50",
        link: "text-primary underline-offset-4 hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant,
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  })
}

export { Badge, badgeVariants }
