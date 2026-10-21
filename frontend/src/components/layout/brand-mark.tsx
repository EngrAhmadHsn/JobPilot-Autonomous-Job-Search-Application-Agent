/**
 * The product mark.
 *
 * A sheet of paper with a highlighter stroke across it: the console is a
 * dossier, and the agent's marks are the lime ones. It is drawn rather
 * than imported so that it inherits the theme's tokens and needs no
 * network request.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={
        className ??
        "inline-flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-primary"
      }
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24" className="size-[18px]" fill="none">
        <path
          d="M6.5 3.75h7.25L18 8v12.25H6.5z"
          className="fill-primary-foreground/95"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />
        <path
          d="M9 13.2h6.6M9 16.2h4.4"
          className="stroke-primary"
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
