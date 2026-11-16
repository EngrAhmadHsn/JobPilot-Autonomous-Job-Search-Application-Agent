import { cn } from "cn"

/**
 * The product mark.
 *
 * A sheet of paper with a highlighter stroke across it: the console is a
 * dossier, and the agent's marks are the lime ones. It is drawn rather
 * than imported so that it inherits the theme's tokens and needs no
 * network request.
 *
 * WS-34 adds the sidebar variant: on the deep forest surface the mark
 * loses its forest chip (which would disappear into the sidebar) and the
 * sheet itself becomes the mark — ivory paper, forest ink, lime stroke.
 */
export function BrandMark({
  className,
  variant = "default",
}: {
  className?: string
  /** "default" sits on paper; "sidebar" sits on the forest sidebar. */
  variant?: "default" | "sidebar"
}) {
  const onSidebar = variant === "sidebar"
  return (
    <span
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-[10px]",
        onSidebar ? "bg-transparent" : "bg-primary",
        className
      )}
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24" className="size-[18px]" fill="none">
        <path
          d="M6.5 3.75h7.25L18 8v12.25H6.5z"
          className={onSidebar ? "fill-ivory" : "fill-primary-foreground/95"}
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />
        <path
          d="M9 13.2h6.6M9 16.2h4.4"
          className={onSidebar ? "stroke-forest" : "stroke-primary"}
          strokeWidth="1.6"
          strokeLinecap="round"
        />
        <path
          d="M9.6 9.1h5.2"
          className="stroke-lime"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
      </svg>
    </span>
  )
}
