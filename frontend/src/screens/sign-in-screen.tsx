import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { ErrorNotice } from "@/components/common/error-notice"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api/endpoints"

/**
 * The sign-in screen.
 *
 * The API has an identity (WS-14), so the console needs one too: a
 * session cookie the browser attaches on its own, and a CSRF header on
 * every unsafe request. The console keeps **no token in JavaScript** — a
 * token in `localStorage` is readable by any script that gets injected,
 * and an `HttpOnly` cookie is not.
 *
 * The screen has two modes, because a deployment needs the first
 * account to be creatable: sign in, or create an account.
 */
export function SignInScreen() {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<"sign-in" | "create">("sign-in")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")

  const signIn = useMutation({
    mutationFn: () => api.signIn(email, password),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["identity"] })
    },
  })

  const createAccount = useMutation({
    mutationFn: () => api.createAccount(email, password),
    onSuccess: () => {
      // The account exists; signing in proves the credentials work.
      signIn.mutate()
    },
  })

  const pending = signIn.isPending || createAccount.isPending
  const error = signIn.error ?? createAccount.error

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6 py-16">
      <div className="w-full max-w-sm space-y-8">
        <div className="space-y-2">
          <h1 className="font-display text-2xl text-foreground">
            {mode === "sign-in" ? "Sign in" : "Create an account"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {mode === "sign-in"
              ? "The console works against your own account: your resumes, your applications, your history."
              : "The first account to register may claim the data that predates the identity work."}
          </p>
        </div>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (mode === "sign-in") {
              signIn.mutate()
            } else {
              createAccount.mutate()
            }
          }}
        >
          <label className="block space-y-1">
            <span className="text-sm font-medium text-foreground">Email</span>
            <Input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-sm font-medium text-foreground">
              Password
            </span>
            <Input
              type="password"
              autoComplete={
                mode === "sign-in" ? "current-password" : "new-password"
              }
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          {error ? <ErrorNotice error={error} /> : null}

          <Button type="submit" className="w-full" disabled={pending}>
            {pending
              ? "Working…"
              : mode === "sign-in"
                ? "Sign in"
                : "Create the account"}
          </Button>
        </form>

        <button
          type="button"
          className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          onClick={() => setMode(mode === "sign-in" ? "create" : "sign-in")}
        >
          {mode === "sign-in"
            ? "No account yet? Create one"
            : "Already have an account? Sign in"}
        </button>
      </div>
    </div>
  )
}
