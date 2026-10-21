import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

import { useTheme } from "@/components/theme-provider"
import { useCurrentProfileId } from "@/lib/profile"

/**
 * The account menu.
 *
 * The console is single-operator for now, so this is **not** a fake
 * signed-in user: it shows the profile the console is working with, the
 * theme, and an honest line about sign-in not being available yet. The
 * identity work (the API's user model and its scopes) is what will give
 * this menu a real name to show.
 */
export function AccountMenu() {
  const { theme, setTheme } = useTheme()
  const profileId = useCurrentProfileId()

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
        <span className="hidden text-muted-foreground sm:inline">Operator</span>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-64">
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

        <DropdownMenuItem disabled className="justify-start gap-2">
          <span className="text-muted-foreground">Sign in</span>
        </DropdownMenuItem>
        <p className="px-2 pb-2 text-xs text-muted-foreground">
          Accounts arrive with the API&apos;s identity work. Until then this
          console talks to a local API and has no sign-in of its own.
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
