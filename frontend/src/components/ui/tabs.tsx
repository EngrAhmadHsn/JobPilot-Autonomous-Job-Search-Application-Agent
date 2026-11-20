import { Tabs as TabsPrimitive } from "@animate-ui/react/primitives/base-ui/tabs"
import { createContext, useContext } from "react"
import { cn } from "cn"

/*
  WS-34: the tabs, on the Base UI primitive. Two variants (WS-42):

  - **underline** — the reference's tab rows ("Overview / Match Details /
    Company …") are underlined headings over a hairline.
  - **pill** — the design file's action-row tabs (Resume Studio `16:82`,
    Profile `16:202`, Activity `16:242`): paper pills, `r=8`, `13/600`, the
    active one filled forest with paper text.

  The keyboard movement (arrow keys, roving focus) is the primitive's, which
  is exactly why this wraps Base UI rather than restyling buttons. The
  variant travels through context because the primitive splits the row
  across `Tabs`, `TabsList` and `TabsTrigger`.
*/

type TabsVariant = "underline" | "pill"

const TabsVariantContext = createContext<TabsVariant>("underline")

function Tabs({
  variant = "underline",
  className,
  ...props
}: TabsPrimitive.Root.Props & { variant?: TabsVariant }) {
  return (
    <TabsVariantContext.Provider value={variant}>
      <TabsPrimitive.Root
        data-slot="tabs"
        data-variant={variant}
        className={cn("flex flex-col gap-3", className)}
        {...props}
      />
    </TabsVariantContext.Provider>
  )
}

function TabsList({ className, ...props }: TabsPrimitive.List.Props) {
  const variant = useContext(TabsVariantContext)
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        "flex items-center gap-1",
        variant === "pill" && "w-fit flex-wrap gap-2.5",
        variant === "underline" && "w-fit border-b border-border",
        className
      )}
      {...props}
    />
  )
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  const variant = useContext(TabsVariantContext)
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex h-9 items-center gap-1.5 px-3 text-sm outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring/60",
        variant === "underline" &&
          cn(
            "rounded-t-md text-muted-foreground hover:text-foreground data-active:font-medium data-active:text-foreground",
            /*
              The underline sits on the list's own hairline, so it never
              double-draws where the two meet. It paints only on the active
              tab: the ::after starts transparent (a bare `after:bg-primary`
              here drew the underline on every tab), and `data-active` turns
              it into the underline.
            */
            "after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-transparent data-active:after:bg-primary"
          ),
        variant === "pill" &&
          cn(
            /*
              The design's measured pill (node `49:954`): 37 px tall, r=8,
              13/600, the active one forest-filled with paper text.
            */
            "h-[37px] rounded-lg border border-border-surface bg-card px-3.5 py-2 text-[13px] font-semibold leading-[19px] text-primary hover:bg-accent data-active:border-primary data-active:bg-primary data-active:text-primary-foreground"
          ),
        className
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-content"
      className={cn("outline-none", className)}
      {...props}
    />
  )
}

export { Tabs, TabsContent, TabsList, TabsTrigger }
