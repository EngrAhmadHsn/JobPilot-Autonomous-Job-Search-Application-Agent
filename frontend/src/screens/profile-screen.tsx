import { ApplicationProfilePanel } from "@/components/profile/application-profile-panel"
import { ProfileView } from "@/components/profile/profile-view"
import { ErrorNotice } from "@/components/common/error-notice"
import { EmptyState } from "@/components/common/progress-state"
import { PageHeader, Section } from "@/components/common/page-header"
import { LinkButton } from "@/components/ui/link-button"
import { useProfileWithFallback } from "@/hooks/use-profile-fallback"

/**
 * The profile screen (WS-20).
 *
 * Two halves of the same person, kept visibly apart:
 *
 * - **what the résumé says** — the parsed profile, read-only, the source the
 *   agent extracts facts from; and
 * - **what you confirm** — the application answers and preferences the
 *   résumé does not carry, edited in the panel below.
 *
 * It is a screen of its own (rather than a panel at the foot of the Résumé
 * screen) so it has a destination in the navigation and can be found.
 */
export function ProfileScreen() {
  const { profile: storedProfile, missing: profileMissing } =
    useProfileWithFallback()

  if (!storedProfile.data && !storedProfile.isPending && !profileMissing) {
    return (
      <EmptyState
        title="No profile selected"
        description="A profile is built from a résumé. Upload one, then come back to answer the questions it does not cover."
        action={<LinkButton to="/app/resume">Go to the Resume screen</LinkButton>}
      />
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Your profile"
        description="What your résumé states, and the answers you confirm. The matcher reads both; the answers are the questions a résumé does not carry — work authorization, salary, notice period."
      />

      {storedProfile.isPending ? (
        <div className="space-y-2">
          <p className="text-sm text-foreground">Loading your profile…</p>
          <div className="agent-progress h-1.5 w-full rounded-full" />
        </div>
      ) : null}

      {storedProfile.isError && !profileMissing ? (
        <ErrorNotice
          error={storedProfile.error}
          onRetry={() => storedProfile.refetch()}
        />
      ) : null}

      {storedProfile.data ? (
        <>
          <Section title="From your résumé">
            <ProfileView profile={storedProfile.data.profile} />
          </Section>
          <Section title="Answers you confirm">
            <ApplicationProfilePanel
              profileId={storedProfile.data.profile_id}
            />
          </Section>
        </>
      ) : null}
    </div>
  )
}