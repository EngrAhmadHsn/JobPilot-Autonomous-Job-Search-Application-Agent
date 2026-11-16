import { Separator as SeparatorPrimitive } from "@base-ui/react/separator"
import { cn } from "cn"

/*
  WS-34: the hairline, on the Base UI primitive.

  A separator is structure, not decoration, so it stays a 1px warm line
  and takes its colour from the border token. `orientation` handles the
  vertical case with the right ARIA semantics.
*/
function Separator({ className, ...props }: SeparatorPrimitive.Props) {
  return (
    <SeparatorPrimitive
      data-slot="separator"
      className={cn(
        "shrink-0 bg-border data-[orientation=horizontal]:h-px data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full data-[orientation=vertical]:w-px",
        className
      )}
      {...props}
    />
  )
}

export { Separator }
