import { useQuery } from "@tanstack/react-query"
import { useState } from "react"
import { FileText, Link2, Lock } from "lucide-react"
import { useSearchParams } from "react-router-dom"

import { ApplicationAnswersPanel } from "@/components/profile/application-profile-panel"
import { WorkPreferencesCard } from "@/components/profile/work-preferences-card"
import { ProfileView } from "@/components/profile/profile-view"
import { ErrorNotice } from "@/components/common/error-notice"
import { EmptyState } from "@/components/common/progress-state"
import { CardSkeleton } from "@/components/common/card-skeleton"
import { Pagination } from "@/components/common/pagination"
import { PageHeader } from "@/components/common/page-header"
import { DOCUMENTS_PER_PAGE } from "@/components/documents/document-picker"
import { LinkButton } from "@/components/ui/link-button"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useProfileWithFallback } from "@/hooks/use-profile-fallback"
import { api } from "@/lib/api/endpoints"
import { apiUrl } from "@/lib/api/client"
import { formatDateTime, formatList } from "@/lib/format"
import { KeySkills } from "@/screens/facts/profile/key-skills"
import { ProfileIdentityCard } from "@/screens/facts/profile/identity-card"

/** The tabs, in the design file's order (node `16:202`). */
type ProfileTab = "documents" | "answers" | "preferences"

/** Which tab a `?tab=` deep link may open, so an unknown value stays honest. */
const TABS: ProfileTab[] = ["documents", "answers", "preferences"]

function tabFromSearch(value: string | null): ProfileTab {
  return TABS.includes(value as ProfileTab)
    ? (value as ProfileTab)
    : "documents"
}

/** How a measured gap reads as a chip, in the coverage words the backend uses. */
function coverageChip(coverage: string) {
  switch (coverage) {
    case "answered":
      return (
        <span className="inline-flex items-center rounded-[6px] bg-lime-soft px-2.5 py-1 text-[11px] leading-4 font-semibold text-lime-foreground">
          Confirmed
        </span>
      )
    case "not_in_profile":
      return (
        <span className="inline-flex items-center rounded-[6px] bg-terracotta-soft px-2.5 py-1 text-[11px] leading-4 font-semibold text-terracotta-foreground">
          Needs your answer
        </span>
      )
    case "never_autofill":
      return (
        <span className="inline-flex items-center rounded-[6px] border border-border-surface px-2.5 py-1 text-[11px] leading-4 font-semibold text-muted-foreground">
          Never autofilled
        </span>
      )
    default:
      return (
        <span className="inline-flex items-center rounded-[6px] border border-border-surface px-2.5 py-1 text-[11px] leading-4 font-semibold text-muted-foreground">
          Unclassified
        </span>
      )
  }
}

/**
 * Profile & documents (WS-20 · tabbed WS-40 · rebuilt to the design file's
 * screen `16:202` in WS-42).
 *
 * The design's tabs — Documents · Application answers · Work preferences —
 * map onto content that exists, and every one opens onto real content:
 *
 * | tab              | what it renders                                                 |
 * |------------------|-----------------------------------------------------------------|
 * | Documents        | the document library with its original/tailored provenance, the |
 * |                  | parsed source facts, and the stored preferences at a glance     |
 * | Application      | the measured question gaps, the confirmed answers and voluntary |
 * | answers          | self-identification — `ApplicationAnswersPanel`'s own cards     |
 * | Work preferences | `WorkPreferencesCard` — the ONE preferences editor, shared with |
 * |                  | the résumé intake page                                          |
 *
 * The design's fourth tab ("Upload résumé") is not a tab here: the Documents
 * card carries the real **Upload →** action, and a tab whose only content
 * was a pointer to another route would be a tab opening onto nothing.
 *
 * Two halves stay visibly separate, unchanged since WS-27: what your
 * **résumé says** (Documents — read-only) and what **you confirm**
 * (answers/preferences — editable). The matcher reads both.
 *
 * The design's "Profile Complete" percentage is **not rendered**: there is
 * no completeness endpoint, and computing one from field counts would be a
 * fabricated metric. The measured question gaps in the side rail are the
 * honest coverage signal.
 *
 * Model credentials no longer sit on this screen (WS-46): they live on the
 * Account & Security screen at `/app/account`, which a `required`-mode
 * deployment can reach before the first résumé exists — the same guarantee
 * WS-27 pinned when the card lived here. The "Private by design." card
 * says so and links there.
 *
 * A `?tab=` query parameter opens a tab directly (`/app/profile?tab=answers`
 * from the account screen's privacy panel); an unknown value opens Documents.
 */
export function ProfileScreen() {
  const {
    profile: storedProfile,
    missing: profileMissing,
    profileId,
    documents,
  } = useProfileWithFallback()
  const [searchParams] = useSearchParams()
  const [tab, setTab] = useState<ProfileTab>(() =>
    tabFromSearch(searchParams.get("tab"))
  )
  /** Whether the parsed source facts are expanded under the library. */
  const [showFacts, setShowFacts] = useState(false)
  /**
   * The page selection, held **against the list it was made from**: when the
   * library itself changes — an upload, a new tailored copy — the selection
   * no longer stands, and the pager reads page one again. Derived during
   * render rather than reset by an effect, so a changed list and its page
   * never disagree for a frame.
   */
  const [pageSelection, setPageSelection] = useState<{
    list: unknown
    page: number
  } | null>(null)

  /*
    The stored preferences and the measured gaps, for the Documents tab's
    glance cards. Same query keys the editors use — one cache, no drift.
  */
  const storedAnswers = useQuery({
    queryKey: ["application-profile", profileId],
    queryFn: ({ signal }) => api.getApplicationProfile(profileId!, signal),
    enabled: Boolean(profileId),
  })
  const gaps = useQuery({
    queryKey: ["question-gaps", profileId],
    queryFn: ({ signal }) => api.getQuestionGaps(profileId!, signal),
    enabled: Boolean(profileId),
  })

  /*
    WS-27: three states, and they must not be confused.

    ``profileId`` (not ``isPending``) is what says whether a profile exists:
    with no stored id and no fallback document, the hook's query is
    *disabled*, and a disabled React Query reports ``isPending: true``
    forever. Keying the empty state on ``isPending`` therefore showed
    "Loading…" indefinitely on a fresh account.

    - ``profileId`` null while the document list is still loading: loading;
    - ``profileId`` null once the list has resolved: no profile, offer upload;
    - ``profileId`` set: the answers and the résumé.
  */
  const resolving = documents.isPending && !profileId
  const needsResume = !profileId && documents.isSuccess

  const profile = storedProfile.data?.profile
  const library = documents.data?.documents ?? []
  const preferences = storedAnswers.data?.application_profile.preferences
  const gapRows = gaps.data?.questions ?? []

  /*
    The library pages client-side (the backend returns the whole list, the
    same as the résumé screen's picker). React Query's structural sharing
    keeps `documents.data` identical while the documents are unchanged, so a
    selection made against one list survives unrelated rerenders — and a
    changed list drops it, which is the reset the pager needs.
  */
  const documentPage =
    pageSelection && pageSelection.list === documents.data
      ? pageSelection.page
      : 0
  const changeDocumentPage = (page: number) =>
    setPageSelection({ list: documents.data, page })

  const documentPages = Math.max(
    1,
    Math.ceil(library.length / DOCUMENTS_PER_PAGE)
  )
  const safeDocumentPage = Math.min(documentPage, documentPages - 1)
  const visibleDocuments = library.slice(
    safeDocumentPage * DOCUMENTS_PER_PAGE,
    (safeDocumentPage + 1) * DOCUMENTS_PER_PAGE
  )

  return (
    <div className="space-y-6">
      <PageHeader
        title="A strong start, on your terms."
        description="Your source documents and confirmed answers in one place."
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
          variant="pill"
          className="gap-5"
        >
          <TabsList aria-label="Profile sections">
            <TabsTrigger value="documents">Documents</TabsTrigger>
            <TabsTrigger value="answers">Application answers</TabsTrigger>
            <TabsTrigger value="preferences">Work preferences</TabsTrigger>
          </TabsList>

          <TabsContent value="documents">
            <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] xl:items-start">
              <div className="min-w-0 space-y-3">
                {/*
                  The document library (design `16:202`, card "Your original
                  stays original."). Every row states its provenance: the
                  résumé you uploaded is ORIGINAL; a tailored copy is TAILORED
                  and points back at what produced it.
                */}
                <section className="flex min-w-0 flex-col gap-3.5 rounded-surface border border-border-surface bg-card p-5">
                  <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                    <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
                      Your original stays original.
                    </h2>
                    <LinkButton to="/app/resume" variant="ghost">
                      Upload →
                    </LinkButton>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Tailored copies always point back to their source.
                  </p>
                  <div
                    className="h-px w-full shrink-0 bg-border-surface"
                    aria-hidden
                  />

                  {library.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No documents yet — upload a résumé to start.
                    </p>
                  ) : (
                    <>
                      <ul className="space-y-3">
                        {visibleDocuments.map((document) => (
                          <li
                            key={document.id}
                            className="flex min-w-0 items-center gap-3 border-b border-border-surface pb-3 last:border-b-0 last:pb-0"
                          >
                            <FileText
                              className="size-5 shrink-0 text-forest/70"
                              strokeWidth={1.7}
                              aria-hidden
                            />
                            <div className="min-w-0 flex-1 space-y-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <p className="truncate text-sm font-semibold text-primary">
                                  {document.filename}
                                </p>
                                {document.kind === "tailored" ? (
                                  <span className="inline-flex items-center rounded-[6px] bg-lime-soft px-2.5 py-1 text-[11px] leading-4 font-semibold text-lime-foreground">
                                    TAILORED
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center rounded-[6px] bg-forest-soft px-2.5 py-1 text-[11px] leading-4 font-semibold text-primary">
                                    ORIGINAL
                                  </span>
                                )}
                                {document.profile_id === profileId ? (
                                  <span className="inline-flex items-center rounded-[6px] bg-forest-soft px-2.5 py-1 text-[11px] leading-4 font-semibold text-primary">
                                    In use
                                  </span>
                                ) : null}
                              </div>
                              <p className="text-xs leading-[17px] text-muted-foreground">
                                {document.kind === "tailored"
                                  ? `Produced by the agent for a job${
                                      document.created_at
                                        ? ` · ${formatDateTime(document.created_at)}`
                                        : ""
                                    }`
                                  : `Your uploaded résumé${
                                      document.created_at
                                        ? ` · ${formatDateTime(document.created_at)}`
                                        : ""
                                    } · used for matching and tailoring`}
                              </p>
                            </div>
                            {/*
                            The design's per-row "Preview ↗" (node 49:1285):
                            the document opens from its real download route
                            in a new tab, so a candidate can check what will
                            be sent before it is sent — the same route the
                            résumé picker uses.
                          */}
                            <a
                              href={apiUrl(
                                `/api/documents/${encodeURIComponent(document.id)}/download`
                              )}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex h-[37px] shrink-0 items-center rounded-lg border border-[#dce1d6] bg-card px-3.5 text-[13px] leading-[19px] font-semibold text-forest transition-colors outline-none hover:bg-accent/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                            >
                              Preview
                              <span aria-hidden="true" className="ml-1">
                                ↗
                              </span>
                              <span className="sr-only">
                                {" "}
                                {document.filename}
                              </span>
                            </a>
                            {document.kind === "tailored" && document.job_id ? (
                              <LinkButton
                                to={`/app/tailor/${encodeURIComponent(document.job_id)}`}
                                variant="ghost"
                                size="sm"
                              >
                                <Link2 className="size-3.5" aria-hidden />
                                Open in Studio
                              </LinkButton>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                      {/*
                        The shared pager (WS-46): the library pages at five
                        per page, exactly like the résumé screen's picker,
                        and renders nothing while everything fits on one.
                      */}
                      <Pagination
                        page={safeDocumentPage}
                        pageSize={DOCUMENTS_PER_PAGE}
                        total={library.length}
                        onPageChange={changeDocumentPage}
                        label="documents"
                      />
                    </>
                  )}

                  {profile ? (
                    <div className="rounded-surface bg-forest-soft p-[18px]">
                      <h3 className="text-[15px] font-semibold text-primary">
                        What your source actually says
                      </h3>
                      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                        {profile.skills.length > 0
                          ? formatList(profile.skills.slice(0, 8))
                          : "The parsed résumé states no skills."}
                      </p>
                      <div className="mt-3">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setShowFacts((v) => !v)}
                          aria-expanded={showFacts}
                        >
                          {showFacts
                            ? "Hide source facts"
                            : "View source facts →"}
                        </Button>
                      </div>
                      {showFacts ? (
                        <div className="mt-3 space-y-5 border-t border-primary/15 pt-4">
                          <ProfileIdentityCard profile={profile} />
                          <ProfileView profile={profile} />
                          <KeySkills skills={profile.skills} />
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </section>

                {/*
                  The stored preferences at a glance (design's "One source for
                  your preferences"). Edit switches to the Work preferences
                  tab — the one editor.
                */}
                <section className="flex min-w-0 flex-col gap-3 rounded-surface border border-border-surface bg-card p-5">
                  <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                    <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
                      One source for your preferences
                    </h2>
                    <Button
                      variant="ghost"
                      onClick={() => setTab("preferences")}
                    >
                      Edit →
                    </Button>
                  </div>
                  <dl className="grid gap-y-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] sm:gap-x-6">
                    <dt className="text-sm text-muted-foreground">Location</dt>
                    <dd className="text-sm font-medium text-foreground">
                      {preferences?.preferred_locations?.length
                        ? formatList(preferences.preferred_locations)
                        : "Not stated"}
                    </dd>
                    <dt className="text-sm text-muted-foreground">Workplace</dt>
                    <dd className="text-sm font-medium text-foreground">
                      {preferences?.remote_preference || "Not stated"}
                    </dd>
                    <dt className="text-sm text-muted-foreground">
                      Role focus
                    </dt>
                    <dd className="text-sm font-medium text-foreground">
                      {preferences?.target_roles?.length
                        ? formatList(preferences.target_roles)
                        : "Not stated"}
                    </dd>
                  </dl>
                </section>
              </div>

              <aside className="min-w-0 space-y-3 xl:sticky xl:top-[calc(var(--header-height,7rem)+1rem)]">
                {/*
                  The coverage rail (design's "Ready for the questions that
                  matter."), from the measured gaps — the honest coverage
                  signal, in the backend's own coverage words.
                */}
                {gapRows.length > 0 ? (
                  <section className="flex min-w-0 flex-col gap-3 rounded-surface border border-border-surface bg-card p-5">
                    <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
                      Ready for the questions that matter.
                    </h2>
                    <p className="text-sm text-muted-foreground">
                      Your résumé cannot answer everything. Keep your answers
                      explicit.
                    </p>
                    <dl className="space-y-2.5">
                      {gapRows.slice(0, 4).map((gap) => (
                        <div
                          key={gap.label}
                          className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5"
                        >
                          <dt className="text-sm font-medium text-foreground">
                            {gap.label}
                          </dt>
                          <dd>{coverageChip(gap.coverage)}</dd>
                        </div>
                      ))}
                    </dl>
                    <div>
                      <Button onClick={() => setTab("answers")}>
                        Review application answers →
                      </Button>
                    </div>
                  </section>
                ) : null}

                <section className="flex min-w-0 flex-col gap-2 rounded-surface bg-forest-soft p-[18px]">
                  <div className="flex items-center gap-2">
                    <Lock
                      className="size-4 shrink-0 text-primary"
                      aria-hidden
                    />
                    <h2 className="text-[15px] font-semibold text-primary">
                      Private by design.
                    </h2>
                  </div>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Voluntary EEO answers are stored separately and never used
                    to rank jobs.
                  </p>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Model credentials and account controls remain in your
                    account menu.
                  </p>
                  <div>
                    <LinkButton to="/app/account" variant="ghost" size="sm">
                      Privacy &amp; account →
                    </LinkButton>
                  </div>
                </section>
              </aside>
            </div>
          </TabsContent>

          <TabsContent value="answers">
            <ApplicationAnswersPanel
              profileId={storedProfile.data.profile_id}
            />
          </TabsContent>

          <TabsContent value="preferences">
            <div className="grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] xl:items-start">
              <div className="min-w-0">
                <WorkPreferencesCard
                  key={`prefs-${storedProfile.data.profile_id}`}
                  profileId={storedProfile.data.profile_id}
                />
              </div>
              <aside className="min-w-0 space-y-3">
                {/*
                  The design's "Your answers have a clear source." panel
                  (node `47:374`) — the rule that makes the form safe: a
                  missing answer stops form filling instead of triggering a
                  guess.
                */}
                <section className="flex min-w-0 flex-col gap-3 rounded-surface bg-forest-soft p-[18px]">
                  <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
                    Your answers have a clear source.
                  </h2>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Parsed résumé facts and your confirmed employer answers are
                    separate. A missing answer stops form filling instead of
                    triggering a guess.
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Required fields are labeled. Tab moves between fields. Enter
                    selects an option. Escape dismisses a popup.
                  </p>
                  <div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setTab("answers")}
                    >
                      Review board questions →
                    </Button>
                  </div>
                </section>
              </aside>
            </div>
          </TabsContent>
        </Tabs>
      ) : null}
    </div>
  )
}
