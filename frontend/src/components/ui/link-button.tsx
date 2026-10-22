import { cn } from "cn"
import type { VariantProps } from "class-variance-authority"
import type { ReactNode } from "react"
import { Link } from "react-router-dom"

import { buttonVariants } from "@/components/ui/button"

/**
 * A link that looks like a button.
 *
 * The `Button` component is a real `<button>`, and making it a link with
 * the component library's `render` prop turns it into an element with the
 * **button** role even when it is an anchor — which tells a screen reader
 * the wrong thing and hides the destination from a middle-click. A link
 * that navigates is a link: this one carries the button's styling and the
 * link's semantics.
 */
export function LinkButton({
  to,
  variant = "default",
  size = "default",
  className,
  children,
}: {
  to: string
  variant?: VariantProps<typeof buttonVariants>["variant"]
  size?: VariantProps<typeof buttonVariants>["size"]
  className?: string
  children: ReactNode
}) {
  return (
    <Link
      to={to}
      viewTransition
      className={cn(buttonVariants({ variant, size }), className)}
    >
      {children}
    </Link>
  )
}
