import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { useSearchParams } from "react-router-dom"

import { Banner } from "@/components/common/banner"
import { CardSkeleton } from "@/components/common/card-skeleton"
import { ErrorNotice } from "@/components/common/error-notice"
import { PageHeader } from "@/components/common/page-header"
import { ModelCredentialsCard } from "@/components/profile/model-credentials-card"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { LinkButton } from "@/components/ui/link-button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { request } from "@/lib/api/client"
import { api } from "@/lib/api/endpoints"
import type { components } from "@/lib/api/schema"
import type { Identity } from "@/lib/api/types"

/** What `PATCH /api/auth/me` accepts (the backend's own `UserUpdate`). */
type AccountUpdate = components["schemas"]["UserUpdate"]

/** The tabs the backend actually supports — in the design's order. */
type AccountTab = "profile" | "credentials" | "privacy"

/*
  The design's fourth tab ("Sessions") is deliberately absent: a sessions
  list would have to draw device names and last-active times the API does
  not track, and a tab that invents its data is worse than no tab. The
  screen ships the three surfaces the backend can honestly serve — the
  identity, the model key, and privacy.
*/

/**
 * Account & Security (WS-46), at `/app/account`, reached from the account
 * menu.
 *
 * "Your workspace, your rules." — the account-level settings that used to be
 * scattered (the BYOK card sat stranded at the foot of Profile, behind the
 * profile data guard) get one screen of their own:
 *
 * | tab              | what it renders                                          |
 * |------------------|----------------------------------------------------------|
 * | Profile          | the identity card — name, email, password — wired to the  |
 * |                  | `PATCH /api/auth/me` route the backend ships              |
 * | Model credentials| the "Your model key" card (the BYOK editor, same endpoint |
 * |                  | surface it had on Profile)                                |
 * | Privacy          | the privacy & deletion panel, linking to the profile's    |
 * |                  | answers tab where the voluntary EEO answers live          |
 *
 * The identity card is **editable** because the endpoint was verified to
 * exist at implementation time (`PATCH /api/auth/me`, WS-14): a user may
 * change their own email, password and display name. The design's Save and
 * Change-password buttons are therefore real, not decoration.
 *
 * The PATCH call is made through the shared `request` client rather than a
 * new `api` method, so `endpoints.ts` keeps only the routes it already
 * served; the session rides the same HttpOnly cookie and the CSRF header is
 * added by the client, like every other unsafe call.
 */
export function AccountScreen() {
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get("tab")
  const tab: AccountTab =
    requestedTab === "credentials" || requestedTab === "privacy"
      ? requestedTab
      : "profile"

  return (
    <div className="space-y-6">
      <PageHeader
        title="Your workspace, your rules."
        documentTitle="Account & security"
        description="Your profile, model credentials, and privacy."
      />

      <Tabs
        value={tab}
        onValueChange={(next) => {
          const params = new URLSearchParams(searchParams)
          if (next === "profile") params.delete("tab")
          else params.set("tab", String(next))
          setSearchParams(params, { replace: true })
        }}
        variant="pill"
        className="gap-5"
      >
        <TabsList aria-label="Account sections">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="credentials">Model credentials</TabsTrigger>
          <TabsTrigger value="privacy">Privacy</TabsTrigger>
        </TabsList>

        <TabsContent value="profile">
          <div className="max-w-3xl">
            <AccountIdentityCard />
          </div>
        </TabsContent>

        <TabsContent value="credentials">
          <div className="max-w-3xl">
            <ModelCredentialsCard />
          </div>
        </TabsContent>

        <TabsContent value="privacy">
          <div className="max-w-3xl">
            <PrivacyPanel />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}

/**
 * The account's identity, editable.
 *
 * `GET /api/auth/me` fills the fields; `PATCH /api/auth/me` saves them.
 * The password change is disclosed on demand rather than always on show —
 * the design's card carries two buttons, and only one of them needs a form.
 *
 * The backend signs the caller's **other** sessions out when the password
 * changes (the change was made from this one, which stays), and that is
 * stated here rather than discovered by surprise.
 */
function AccountIdentityCard() {
  const queryClient = useQueryClient()
  const identity = useQuery({
    queryKey: ["identity"],
    queryFn: ({ signal }) => api.identity(signal),
  })

  /*
    The fields are **edits over the stored identity**, not copies of it:
    state holds what the operator has typed (null until they do), and the
    stored value fills any field they have not touched — including a field
    whose fetch has not landed yet. Deriving the display value this way
    means no seeding effect: a refetch cannot clobber what is being typed,
    and an untouched field always follows the server.
  */
  const [nameEdit, setNameEdit] = useState<string | null>(null)
  const [emailEdit, setEmailEdit] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")

  const loaded = identity.data
  const fullName = nameEdit ?? loaded?.full_name ?? ""
  const email = emailEdit ?? loaded?.email ?? ""

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["identity"] })

  const saveDetails = useMutation({
    mutationFn: (body: AccountUpdate) =>
      request<Identity>("/api/auth/me", { method: "PATCH", json: body }),
    onSuccess: invalidate,
  })

  const changePassword = useMutation({
    mutationFn: (body: AccountUpdate) =>
      request<Identity>("/api/auth/me", { method: "PATCH", json: body }),
    onSuccess: () => {
      setNewPassword("")
      setConfirmPassword("")
      setShowPassword(false)
      invalidate()
    },
  })

  if (identity.isPending) {
    return <CardSkeleton rows={3} />
  }
  if (identity.isError) {
    return (
      <ErrorNotice error={identity.error} onRetry={() => identity.refetch()} />
    )
  }

  const passwordsDiffer =
    newPassword.length > 0 && newPassword !== confirmPassword
  const passwordReady =
    newPassword.length >= 8 &&
    newPassword === confirmPassword &&
    !changePassword.isPending

  const detailsReady =
    email.trim().length > 0 &&
    !saveDetails.isPending &&
    // Nothing to save when neither field moved off its stored value.
    (email !== (loaded?.email ?? "") || fullName !== (loaded?.full_name ?? ""))

  return (
    <Card data-testid="account-identity">
      <CardHeader>
        <CardTitle>Your account</CardTitle>
        <CardDescription>
          The identity your sign-in uses. Notices about your account go to this
          email.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-xs font-medium text-muted-foreground">
              Name
            </span>
            <Input
              value={fullName}
              onChange={(e) => setNameEdit(e.target.value)}
              autoComplete="name"
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs font-medium text-muted-foreground">
              Email
            </span>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmailEdit(e.target.value)}
              autoComplete="email"
            />
          </label>
        </div>

        {saveDetails.isError ? <ErrorNotice error={saveDetails.error} /> : null}
        {saveDetails.isSuccess ? (
          <Banner tone="success" title="Saved.">
            <p>Your account is updated.</p>
          </Banner>
        ) : null}
        {/*
          The password outcome lives **outside** the disclosed form: a
          successful change closes the form, and a banner that closed with it
          would never be read.
        */}
        {changePassword.isError ? (
          <ErrorNotice error={changePassword.error} />
        ) : null}
        {changePassword.isSuccess ? (
          <Banner tone="success" title="Password changed.">
            <p>Your other sessions were signed out.</p>
          </Banner>
        ) : null}

        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() =>
              saveDetails.mutate({
                full_name: fullName.trim() || null,
                email: email.trim(),
              })
            }
            disabled={!detailsReady}
          >
            {saveDetails.isPending ? "Saving…" : "Save changes"}
          </Button>
          {!showPassword ? (
            <Button
              variant="outline"
              onClick={() => setShowPassword(true)}
              aria-expanded={showPassword}
            >
              Change password
            </Button>
          ) : null}
        </div>

        {showPassword ? (
          <div className="space-y-4 border-t border-border-surface pt-5">
            <div>
              <h3 className="text-[15px] font-semibold text-primary">
                Change password
              </h3>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                Changing your password signs your other sessions out. This one
                stays signed in.
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground">
                  New password
                </span>
                <Input
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground">
                  Confirm new password
                </span>
                <Input
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
              </label>
            </div>
            {passwordsDiffer ? (
              <p className="text-sm text-terracotta-foreground">
                The passwords do not match yet.
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => changePassword.mutate({ password: newPassword })}
                disabled={!passwordReady}
              >
                {changePassword.isPending ? "Changing…" : "Change password"}
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setShowPassword(false)
                  setNewPassword("")
                  setConfirmPassword("")
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

/**
 * The privacy & deletion panel.
 *
 * The voluntary EEO answers are the one set of facts this product keeps
 * **separate** from the application profile — opt-in, never inferred, never
 * a ranking signal, deletable independently. They are edited on the
 * profile's answers tab, so the panel links there rather than duplicating
 * the editor (a second editor would be a second place the two could
 * disagree).
 */
function PrivacyPanel() {
  return (
    <section className="flex min-w-0 flex-col gap-2 rounded-surface bg-terracotta-soft p-[18px]">
      <h2 className="text-[20px] leading-[29px] font-semibold text-primary">
        Privacy &amp; deletion
      </h2>
      <p className="text-sm leading-relaxed text-muted-foreground">
        Voluntary EEO answers are stored separately from your application
        profile, are never inferred from your résumé, and are never used to rank
        jobs. You can inspect, change, or delete them at any time.
      </p>
      <div>
        <LinkButton to="/app/profile?tab=answers" variant="ghost" size="sm">
          Review EEO answers →
        </LinkButton>
      </div>
    </section>
  )
}
