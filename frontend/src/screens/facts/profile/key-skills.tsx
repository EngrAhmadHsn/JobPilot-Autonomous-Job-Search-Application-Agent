import { Badge } from "@/components/ui/badge"
import { PlainText } from "@/components/common/plain-text"

/*
  "Key skills" (WS-40, reference panel 6's chip row).

  The reference shows a handful of skill chips. The profile's `skills` list is
  the parser's own read of the document — these are the first few, in the
  document's order, never a relevance ranking the product cannot compute. The
  full list lives on the Skills tab; this is the glance.
*/

/** How many chips the glance row shows before deferring to the tab. */
export const KEY_SKILLS_SHOWN = 8

export function KeySkills({
  skills,
  onSeeAll,
}: {
  skills: string[]
  /** Hand off to the full list; absent when there is nothing more to show. */
  onSeeAll?: () => void
}) {
  if (skills.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        The résumé did not list any skills the parser recognised.
      </p>
    )
  }
  const shown = skills.slice(0, KEY_SKILLS_SHOWN)
  const rest = skills.length - shown.length

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {shown.map((skill) => (
          /*
            `whitespace-normal` + `wrap-anywhere` deliberately override the
            Badge's own `whitespace-nowrap`/`overflow-hidden`: a long skill
            name ("Structured Query Language") must wrap inside the chip
            rather than be clipped at its border. `wrap-anywhere` (not
            `break-words`) is the utility that actually lets an unbreakable
            token break — measured on this project before.
          */
          <Badge
            key={skill}
            variant="secondary"
            className="max-w-full overflow-visible whitespace-normal"
          >
            <PlainText as="span" className="wrap-anywhere">
              {skill}
            </PlainText>
          </Badge>
        ))}
      </div>
      {rest > 0 && onSeeAll ? (
        <button
          type="button"
          onClick={onSeeAll}
          className="text-xs font-medium text-primary underline-offset-2 hover:underline"
        >
          +{rest} more {rest === 1 ? "skill" : "skills"}
        </button>
      ) : null}
    </div>
  )
}
