import { Separator as SeparatorPrimitive } from "@base-ui/react/separator"
import { cn } from "cn"

/*
  WS-34: the hairline, on the Base UI primitive.

  A separator is structure, not decoration, so it stays a 1px warm line
  and takes its colour from the border token. `orientation` handles the
  vertical case with the right ARIA semantics.

  WS-48: rebased on the canonical base-nova separator — the explicit
  `orientation` default and the `data-horizontal:`/`data-vertical:`
  shorthand variants (the `shadcn/tailwind.css` custom variants that map
  onto `[data-orientation=…]`, which Base UI renders). The vertical case
  adopts the canonical `self-stretch` in place of the forked `h-full`; no
  screen renders a vertical separator, so nothing moves.
*/
function Separator({
  className,
  orientation = "horizontal",
  ...props
}: SeparatorPrimitive.Props) {
  return (
    <SeparatorPrimitive
      data-slot="separator"
      orientation={orientation}
      className={cn(
        "shrink-0 bg-border data-horizontal:h-px data-horizontal:w-full data-vertical:w-px data-vertical:self-stretch",
        className
      )}
      {...props}
    />
  )
}

export { Separator }
