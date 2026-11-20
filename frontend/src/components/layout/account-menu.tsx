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
import { cn } from "cn"

import { useTheme } from "@/components/theme-provider"
import { api } from "@/lib/api/endpoints"
import {
  setMotionPreference,
  useMotionPreference,
  type MotionPreference,
} from "@/lib/motion"
import { useCurrentProfileId } from "@/lib/profile"

/**
 * The account menu.
 *
 * It shows **the account the console is signed in as** (WS-14), the
 * profile the console is working with, and the theme — and it offers a
 * sign-out that ends the session **server-side**, not merely in the
 * browser: a session is a row, and a row that is only forgotten by the
 * browser is still a live credential.
 *
 * WS-34 restyles the trigger into the shell's account areas: at desktop
 * widths it sits in the forest sidebar's footer (`surface="sidebar"`),
 * on narrow screens in the top bar (`surface="bar"`). The menu's
 * contents — and therefore the behavior the tests pin — are the same on
 * both surfaces, and the popover opens upward from a footer.
 */
export function AccountMenu({
  surface = "bar",
  compact = false,
  className,
}: {
  surface?: "bar" | "sidebar"
  /**
   * A cramped host — the 72 px rail. The account's identity still names
   * the menu (the `aria-label` and the dialog's own heading), but the
   * email text is dropped: a `sm:inline` span inside a 72 px strip
   * overflowed it and painted the address across the canvas.
   */
  compact?: boolean
  className?: string
}) {
  const { theme, setTheme } = useTheme()
  const motion = useMotionPreference()
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

  const onSidebar = surface === "sidebar"

  return (
    <DropdownMenu>
      {/*
        `h-11`/`size-11` is 44px. This trigger is the only path to sign
        out, the theme switch and the motion control, so it has to be
        easy to hit with a thumb. It was `h-9`.
      */}
      <DropdownMenuTrigger
        className={cn(
          "inline-flex items-center gap-2 rounded-lg border px-2.5 text-sm transition-colors duration-150",
          /*
            Two sidebar shapes, from the design's rail footer (nodes 47:27
            collapsed, 49:2253 + 49:2368 expanded): the 72 px strip holds
            the 36 px avatar alone; the expanded rail and the drawer's
            footer hold the avatar beside a two-line identity block — the
            account line over the caption "Account & preferences". No
            chevron: the design's footer draws none, and the popover opens
            upward from here.
          */
          onSidebar
            ? cn(
                "border-transparent bg-transparent text-sidebar-foreground hover:bg-sidebar-hover",
                compact ? "h-11 justify-center" : "h-auto w-full py-2"
              )
            : "h-11 border-border bg-card text-foreground hover:bg-accent/60",
          className
        )}
        aria-label="Account and display settings"
      >
        <span
          aria-hidden="true"
          className={cn(
            "inline-flex shrink-0 items-center justify-center rounded-full bg-terracotta font-semibold text-terracotta-foreground",
            onSidebar ? "size-9 text-[13px]" : "size-6 text-[11px]"
          )}
        >
          {profileId ? "OP" : "—"}
        </span>
        {onSidebar && !compact ? (
          <span className="min-w-0 flex-1 text-start leading-tight">
            <span className="block truncate text-[13px] leading-[19px] font-semibold text-sidebar-foreground">
              {identity?.email ?? "Operator"}
            </span>
            <span className="block text-[10px] leading-[15px] text-sidebar-muted">
              Account &amp; preferences
            </span>
          </span>
        ) : (
          <span
            className={cn(
              "min-w-0 truncate text-muted-foreground",
              /*
                `compact` (the 72 px rail) must REMOVE `sm:inline`, not layer
                a `hidden` on top of it: tailwind-merge keeps both because
                they are different variants, and `sm:inline` then wins at
                desktop widths. Choosing the whole class set is what actually
                hides it.
              */
              compact ? "hidden" : "hidden sm:inline",
              onSidebar && "text-sidebar-muted"
            )}
          >
            {identity?.email ?? "Operator"}
          </span>
        )}
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align={onSidebar ? "start" : "end"}
        side={onSidebar ? "top" : "bottom"}
        className="w-64"
      >
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
          <DropdownMenuLabel>Motion</DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuRadioGroup
          value={motion}
          onValueChange={(value) =>
            setMotionPreference(value as MotionPreference)
          }
        >
          <DropdownMenuRadioItem value="system">
            Follow the system
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="full">
            Full motion
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="reduced">
            Reduced motion
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
