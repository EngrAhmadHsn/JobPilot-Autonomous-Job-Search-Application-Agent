import { cn } from "cn"
import type { ReactNode } from "react"

/**
 * Untrusted text, rendered as plain text.
 *
 * Every string the backend returns — a job description, a tailored bullet, a
 * confirmation message, an insight — arrives here. The element is a `<p>` or
 * a `<pre>` with `whitespace-pre-wrap`: the browser shows the characters the
 * server sent and nothing else. There is no markup path here, and the
 * ESLint rule in `eslint.config.js` forbids the two APIs that would create
 * one.
 */
export function PlainText({
  children,
  className,
  as: Tag = "p",
}: {
  children: ReactNode
  className?: string
  as?: "p" | "pre" | "span"
}) {
  return (
    <Tag
      className={cn(
        "text-sm leading-relaxed break-words whitespace-pre-wrap text-foreground",
        className
      )}
    >
      {children}
    </Tag>
  )
}
