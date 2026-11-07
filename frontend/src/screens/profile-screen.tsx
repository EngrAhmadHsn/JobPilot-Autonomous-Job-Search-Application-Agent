import { ApplicationProfilePanel } from "@/components/profile/application-profile-panel"
import { ProfileView } from "@/components/profile/profile-view"
import { Disclosure } from "@/components/common/disclosure"
import { ErrorNotice } from "@/components/common/error-notice"
import { EmptyState } from "@/components/common/progress-state"
import { PageHeader, Section } from "@/components/common/page-header"
import { LinkButton } from "@/components/ui/link-button"
import { useProfileWithFallback } from "@/hooks/use-profile-fallback"

/**
 * Profile (WS-20).
 *
 * The order is the order of work: the answers you can give come first, and
 * the résumé — which you cannot change here — sits below, folded up. Only the
 * summary is open; the full extraction is a click away, so the page reads as
 * two short cards rather than one long document.
 *
 * The two halves stay visibly separate: what your résumé says, and what you
 * confirm. The matcher reads both, and the answers are the questions a résumé
 * does not carry.
 */
export function ProfileScreen() {
  const { profile: storedProfile, missing: profileMissing } = useProfileWithFallback()

  if (!storedProfile.data && !storedProfile.isPending && !profileMissing) {
    return (
      <EmptyState
        title="No profile yet"
        description="A profile is built from a résumé. Add one, then come back to answer the questions it does not cover."
        action={<LinkButton to="/app/resume">Add a résumé</LinkButton>}
      />
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Profile"
        description="Answer once here, and the agent can answer for you. Your résumé supplies the rest."
      />

      {storedProfile.isPending ? (
        <div className="space-y-2">
          <p className="text-sm text-foreground">Loading…</p>
          <div className="agent-progress h-1.5 w-full rounded-full" />
        </div>
      ) : null}

      {storedProfile.isError && !profileMissing ? (
        <ErrorNotice error={storedProfile.error} onRetry={() => storedProfile.refetch()} />
      ) : null}

      {storedProfile.data ? (
        <>
          <ApplicationProfilePanel profileId={storedProfile.data.profile_id} />

          <Section title="From your résumé">
            <Disclosure
              summary="See the full résumé profile"
              hint={`${storedProfile.data.profile.skills.length} skills · ${
                storedProfile.data.profile.projects.length
              } projects`}
            >
              <ProfileView profile={storedProfile.data.profile} />
            </Disclosure>
          </Section>
        </>
      ) : null}
    </div>
  )
}