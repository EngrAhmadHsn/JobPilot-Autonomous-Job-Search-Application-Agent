import { MailIcon, MapPinIcon } from "lucide-react"

import { PlainText } from "@/components/common/plain-text"
import { Card, CardContent } from "@/components/ui/card"
import type { CandidateProfile } from "@/lib/api/types"

/*
  The Profile's identity card (WS-40, reference panel 6's left column).

  Every field is the parsed profile's own (`PersonalInformation`): the name,
  title, email and location the résumé states. Nothing is assumed when a
  field is empty — the row simply does not render.

  What the reference draws that this **cannot**: a photograph (the product
  never collects one — an initials monogram is the honest equivalent, the
  same pattern the Discover detail panel and the account menu use), the
  "Profile Complete" percentage badge (there is no completeness endpoint;
  inventing one from field counts would be a fabricated metric — the real
  coverage signal is the measured question gaps, which render on the
  application-answers surface), and social links.
*/

/** Initials for the monogram: two letters at most, never invented. */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "?"
  const first = parts[0]?.charAt(0) ?? ""
  const last =
    parts.length > 1 ? (parts[parts.length - 1]?.charAt(0) ?? "") : ""
  return (first + last).toUpperCase() || "?"
}

export function ProfileIdentityCard({
  profile,
}: {
  profile: CandidateProfile
}) {
  const person = profile.personal_information
  const name = person.name.trim() || "Your résumé has no name line"
  const title = person.title.trim()
  const location = person.location.trim()
  const email = person.email.trim()

  return (
    <Card>
      <CardContent className="flex items-start gap-4">
        <span
          aria-hidden="true"
          className="flex size-14 shrink-0 items-center justify-center rounded-full bg-forest-soft font-heading text-lg font-semibold text-forest"
        >
          {initials(person.name)}
        </span>
        <div className="min-w-0 space-y-1">
          <p className="font-heading text-lg leading-tight font-semibold wrap-anywhere text-foreground">
            <PlainText as="span">{name}</PlainText>
          </p>
          {title ? (
            <p className="text-sm wrap-anywhere text-muted-foreground">
              <PlainText as="span">{title}</PlainText>
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {location ? (
              <span className="inline-flex min-w-0 items-center gap-1">
                <MapPinIcon aria-hidden="true" className="size-3.5 shrink-0" />
                <PlainText as="span" className="wrap-anywhere">
                  {location}
                </PlainText>
              </span>
            ) : null}
            {email ? (
              <span className="inline-flex min-w-0 items-center gap-1">
                <MailIcon aria-hidden="true" className="size-3.5 shrink-0" />
                <PlainText as="span" className="wrap-anywhere">
                  {email}
                </PlainText>
              </span>
            ) : null}
            {profile.experience.length > 0 ? (
              <span>
                {profile.experience.length}{" "}
                {profile.experience.length === 1 ? "role" : "roles"} on record
              </span>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
