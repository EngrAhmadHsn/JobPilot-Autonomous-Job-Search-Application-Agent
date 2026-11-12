import { ApplicationProfilePanel } from "@/components/profile/application-profile-panel"
import { ModelCredentialsCard } from "@/components/profile/model-credentials-card"
import { ProfileView } from "@/components/profile/profile-view"
import { Disclosure } from "@/components/common/disclosure"
import { ErrorNotice } from "@/components/common/error-notice"
import { EmptyState } from "@/components/common/progress-state"
import { PageHeader, Section } from "@/components/common/page-header"
import { LinkButton } from "@/components/ui/link-button"
import { useProfileWithFallback } from "@/hooks/use-profile-fallback"

/**
 * Profile (WS-20, reordered WS-27).
 *
 * The order is the order of work, and it is now strictly **yours first, then
 * your résumé's**:
 *
 * 1. the answers you can give (preferences, application answers, EEO);
 * 2. your model credential — an account setting, not a profile field;
 * 3. your résumé, which you cannot change here, folded away at the bottom.
 *
 * WS-27 moved the credential card up here and gave it a `Section`. It used to
 * sit as a bare `<Card>` *after* the résumé block — the only orphan card in
 * the console, visually last on a page about profile answers, and outside the
 * heading outline (`CardTitle` is a `div`). Its own docstring calls it an
 * account setting, so it belongs with the settings-shaped blocks, not below
 * résumé-derived content it has nothing to do with.
 *
 * The two halves of the profile stay visibly separate: what your résumé says,
 * and what you confirm. The matcher reads both, and the answers are the
 * questions a résumé does not carry.
 */
export function ProfileScreen() {
  const {
    profile: storedProfile,
    missing: profileMissing,
    profileId,
    documents,
  } = useProfileWithFallback()

  /*
    WS-27: three states, and they must not be confused.

    ``profileId`` (not ``isPending``) is what says whether a profile exists:
    with no stored id and no fallback document, the hook's query is
    *disabled*, and a disabled React Query reports ``isPending: true``
    forever. Keying the empty state on ``isPending`` therefore showed
    "Loading…" indefinitely on a fresh account — the old early return only
    appeared to work because it ran before the pending flag was consulted.

    - ``profileId`` null while the document list is still loading: loading;
    - ``profileId`` null once the list has resolved: no profile, offer upload;
    - ``profileId`` set: the answers and the résumé.

    The credential card renders in **all three** states. It is an account
    setting, and a deployment in `required` mode must be able to take a key
    before the first résumé exists.
  */
  const resolving = documents.isPending && !profileId
  const needsResume = !profileId && documents.isSuccess

  return (
    <div className="space-y-6">
      <PageHeader
        title="Profile"
        description="Answer once here, and the agent can answer for you. Your résumé supplies the rest."
      />

      {resolving || (storedProfile.isPending && profileId) ? (
        <div className="space-y-2">
          <p className="text-sm text-foreground">Loading…</p>
          <div className="agent-progress h-1.5 w-full rounded-full" />
        </div>
      ) : null}

      {storedProfile.isError && !profileMissing ? (
        <ErrorNotice error={storedProfile.error} onRetry={() => storedProfile.refetch()} />
      ) : null}

      {needsResume ? (
        <EmptyState
          title="No profile yet"
          description="A profile is built from a résumé. Add one, then come back to answer the questions it does not cover."
          action={<LinkButton to="/app/resume">Add a résumé</LinkButton>}
        />
      ) : null}

      {storedProfile.data ? (
        <ApplicationProfilePanel profileId={storedProfile.data.profile_id} />
      ) : null}

      {/*
        WS-22/WS-27: an account setting, so it sits with the answer cards and
        above the résumé — which is reference material, not something you edit
        here. Rendered whether or not a résumé exists.

        The Section is named for the *concern* ("Your model", i.e. whose AI
        runs your tailoring), not for the widget, following the "What you want
        next" / Work preferences precedent on the Résumé screen — otherwise
        the section heading and the card title would say the same words twice.
      */}
      <Section
        title="Your model"
        description="Optional. Use your own AI provider key and your calls run on your quota and your bill."
      >
        <div className="max-w-3xl">
          <ModelCredentialsCard />
        </div>
      </Section>

      {storedProfile.data ? (
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
      ) : null}
    </div>
  )
}