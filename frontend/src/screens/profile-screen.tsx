import { ApplicationProfilePanel } from "@/components/profile/application-profile-panel"
import { ModelCredentialsCard } from "@/components/profile/model-credentials-card"
import { ProfileView } from "@/components/profile/profile-view"
import { ErrorNotice } from "@/components/common/error-notice"
import { EmptyState } from "@/components/common/progress-state"
import { CardSkeleton } from "@/components/common/card-skeleton"
import { PageHeader, Section } from "@/components/common/page-header"
import { LinkButton } from "@/components/ui/link-button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useProfileWithFallback } from "@/hooks/use-profile-fallback"
import { useState } from "react"
import { KeySkills } from "@/screens/facts/profile/key-skills"
import { ProfileIdentityCard } from "@/screens/facts/profile/identity-card"

/** The tabs, in the reference's order (panel 6). */
type ProfileTab =
  "overview" | "experience" | "skills" | "preferences" | "settings"

/**
 * Profile (WS-20, reordered WS-27, tabbed WS-40).
 *
 * **The reference panel 6 draws a tabbed profile; this maps those tabs onto
 * content that exists.** Nothing here is a placeholder tab:
 *
 * | tab         | what it renders                                              |
 * |-------------|--------------------------------------------------------------|
 * | Overview    | the identity card + a résumé summary + a key-skills glance     |
 * | Experience  | the parsed experience, education, projects and certifications  |
 * | Skills      | the full skill list, in the document's own order               |
 * | Preferences | the application-profile panel — work preferences, the measured |
 * |             | question gaps, application answers and EEO (one component, one |
 * |             | shared read/save query; WorkPreferencesCard stays the single   |
 * |             | preferences editor)                                            |
 * | Settings    | a pointer to the account settings below the tabs                |
 *
 * The BYOK credential card sits **below the tab set, outside the
 * `storedProfile.data` guard** — WS-27's rule that it must render in all three
 * states (resolving / no profile / populated), because a `required`-mode
 * deployment needs a key before the first résumé exists.
 *
 * The two halves of the profile stay visibly separate, unchanged from WS-27:
 * what your **résumé says** (Overview/Experience/Skills — read-only here) and
 * what **you confirm** (Preferences/Settings — editable). The matcher reads
 * both, and the answers are the questions a résumé does not carry.
 *
 * The reference's "Profile Complete" percentage is **not rendered**: there is
 * no completeness endpoint, and computing one from field counts would be a
 * fabricated metric. The measured question gaps in Settings are the honest
 * coverage signal.
 */
export function ProfileScreen() {
  const {
    profile: storedProfile,
    missing: profileMissing,
    profileId,
    documents,
  } = useProfileWithFallback()
  const [tab, setTab] = useState<ProfileTab>("overview")

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
        <CardSkeleton rows={4} />
      ) : null}

      {storedProfile.isError && !profileMissing ? (
        <ErrorNotice
          error={storedProfile.error}
          onRetry={() => storedProfile.refetch()}
        />
      ) : null}

      {needsResume ? (
        <EmptyState
          title="No profile yet"
          description="A profile is built from a résumé. Add one, then come back to answer the questions it does not cover."
          action={<LinkButton to="/app/resume">Add a résumé</LinkButton>}
        />
      ) : null}

      {storedProfile.data ? (
        <Tabs
          value={tab}
          onValueChange={(next) => setTab(next as ProfileTab)}
          className="gap-5"
        >
          <TabsList aria-label="Profile sections">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="experience">Experience</TabsTrigger>
            <TabsTrigger value="skills">Skills</TabsTrigger>
            <TabsTrigger value="preferences">Preferences</TabsTrigger>
            <TabsTrigger value="settings">Settings</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-5">
            <ProfileIdentityCard profile={storedProfile.data.profile} />

            {storedProfile.data.profile.summary.trim() ? (
              <Section title="Summary">
                <p className="max-w-[68ch] text-sm leading-relaxed text-muted-foreground">
                  {storedProfile.data.profile.summary}
                </p>
              </Section>
            ) : null}

            <Section
              title="Key skills"
              description="The first few the résumé lists, in its own order — not a ranking."
            >
              <KeySkills
                skills={storedProfile.data.profile.skills}
                onSeeAll={() => setTab("skills")}
              />
            </Section>
          </TabsContent>

          <TabsContent value="experience" className="space-y-5">
            <Section
              title="From your résumé"
              description="Parsed from the document you uploaded. This tab is a read-only view — edit the résumé itself, not a copy of it here."
            >
              <ProfileView profile={storedProfile.data.profile} />
            </Section>
          </TabsContent>

          <TabsContent value="skills" className="space-y-5">
            <Section
              title="Skills"
              description={`${storedProfile.data.profile.skills.length} stated in the résumé, in the document's own order.`}
            >
              <KeySkills skills={storedProfile.data.profile.skills} />
            </Section>
          </TabsContent>

          <TabsContent value="preferences" className="space-y-5">
            {/*
              The whole application-profile panel lives here — work
              preferences, the measured question gaps, the application
              answers and EEO. It is one component behind one shared
              read/save query (WS-20/21/25b), and splitting it by tab would
              mean splitting that query for a cosmetic win; keeping it whole
              also keeps `WorkPreferencesCard` the ONE preferences editor.
            */}
            <ApplicationProfilePanel
              profileId={storedProfile.data.profile_id}
            />
          </TabsContent>

          <TabsContent value="settings" className="space-y-5">
            <p className="max-w-[68ch] text-sm text-muted-foreground">
              Account settings that are not part of your profile answers. Your
              model key is the one control here.
            </p>
          </TabsContent>
        </Tabs>
      ) : null}

      {/*
        WS-27 keeps a hard rule that the tabbing must not break: the
        credential card renders in **all three** states — resolving, no
        profile, and populated. It is an account setting, and a deployment in
        `BYOK_MODE=required` must be able to take a key before the first
        résumé exists, or the console is unstartable. So it sits OUTSIDE the
        `storedProfile.data` guard (where the tabs live) rather than inside a
        tab that only exists once a profile does.
      */}
      <Section
        title="Your model"
        description="Optional. Use your own AI provider key and your calls run on your quota and your bill."
      >
        <div className="max-w-3xl">
          <ModelCredentialsCard />
        </div>
      </Section>
    </div>
  )
}
