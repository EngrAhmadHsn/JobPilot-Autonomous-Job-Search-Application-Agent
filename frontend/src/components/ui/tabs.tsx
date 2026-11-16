import { Tabs as TabsPrimitive } from "@base-ui/react/tabs"
import { cn } from "cn"

/*
  WS-34: the tabs, on the Base UI primitive.

  The active tab is an underline, not a pill — the reference's tab rows
  ("Overview / Match Details / Company …") are underlined headings over a
  hairline. The keyboard movement (arrow keys, roving focus) is the
  primitive's, which is exactly why this wraps Base UI rather than
  restyling buttons.
*/
function Tabs({ className, ...props }: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      className={cn("flex flex-col gap-3", className)}
      {...props}
    />
  )
}

function TabsList({ className, ...props }: TabsPrimitive.List.Props) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        "flex w-fit items-center gap-1 border-b border-border",
        className
      )}
      {...props}
    />
  )
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex h-9 items-center gap-1.5 rounded-t-md px-3 text-sm text-muted-foreground transition-colors duration-150 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60 data-active:font-medium data-active:text-foreground",
        /*
          The underline sits on the list's own hairline, so it never
          double-draws where the two meet. It paints only on the active
          tab: the ::after starts transparent (a bare `after:bg-primary`
          here drew the underline on every tab), and `data-active` turns
          it into the underline.
        */
        "after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-transparent data-active:after:bg-primary",
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
