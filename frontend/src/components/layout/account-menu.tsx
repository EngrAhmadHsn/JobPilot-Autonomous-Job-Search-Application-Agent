import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { useTheme } from "@/components/theme-provider"
import { api } from "@/lib/api/endpoints"
import { useCurrentProfileId } from "@/lib/profile"

/**
 * The account menu.
 *
 * It shows **the account the console is signed in as** (WS-14), the
 * profile the console is working with, and the theme — and it offers a
 * sign-out that ends the session **server-side**, not merely in the
 * browser: a session is a row, and a row that is only forgotten by the
 * browser is still a live credential.
 */
export function AccountMenu() {
  const { theme, setTheme } = useTheme()
  const profileId = useCurrentProfileId()
  const queryClient = useQueryClient()
  const { data: identity } = useQuery({
    queryKey: ["identity"],
    queryFn: ({ signal }) => api.identity(signal),
    retry: false,
  })
  const signOut = useMutation({
    mutationFn: () => api.signOut(),
    onSuccess: () => {
      queryClient.setQueryData(["identity"], null)
      queryClient.invalidateQueries()
    },
  })

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-2.5 text-sm transition-colors duration-150 hover:bg-accent/60"
        aria-label="Account and display settings"
      >
        <span
          aria-hidden="true"
          className="inline-flex size-6 items-center justify-center rounded-full bg-terracotta text-[11px] font-semibold text-terracotta-foreground"
        >
          {profileId ? "OP" : "—"}
        </span>
        <span className="hidden text-muted-foreground sm:inline">
          {identity?.email ?? "Operator"}
        </span>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-64">
        {/*
          The label is a *group* label in Base UI, and a group label needs
          a group: without this wrapper the menu throws the moment it
          opens.
        */}
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-normal">
            <span className="block text-sm font-medium text-foreground">
              Operator console
            </span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {profileId ? (
                <>
                  Working with profile{" "}
                  <code className="font-mono text-[11px] text-foreground">
                    {profileId}
                  </code>
                </>
              ) : (
                "No profile selected yet"
              )}
            </span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuRadioGroup
          value={theme}
          onValueChange={(value) =>
            setTheme(value as "light" | "dark" | "system")
          }
        >
          <DropdownMenuRadioItem value="light">Ivory</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">Charcoal</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            Match the system
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>

        <DropdownMenuSeparator />

        <DropdownMenuGroup>
          <DropdownMenuItem
            className="justify-start gap-2"
            onSelect={() => signOut.mutate()}
          >
            <span>Sign out</span>
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
