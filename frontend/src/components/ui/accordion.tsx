import { Accordion as AccordionPrimitive } from "@animate-ui/react/primitives/base-ui/accordion"
import { ChevronDownIcon } from "lucide-react"
import { cn } from "cn"

/*
  WS-34: the accordion, on the Base UI primitive.

  Progressive disclosure for the dense screens: raw event data, long
  requirement lists, report detail. The chevron rotates via the
  primitive's own `data-open` attribute, and the panel's show/hide is a
  grid-rows transition so content of any height animates without a fixed
  max-height hack.
*/
function Accordion({ className, ...props }: AccordionPrimitive.Root.Props) {
  return (
    <AccordionPrimitive.Root
      data-slot="accordion"
      className={cn("w-full", className)}
      {...props}
    />
  )
}

function AccordionItem({ className, ...props }: AccordionPrimitive.Item.Props) {
  return (
    <AccordionPrimitive.Item
      data-slot="accordion-item"
      className={cn("border-b border-border last:border-b-0", className)}
      {...props}
    />
  )
}

function AccordionHeader({
  className,
  ...props
}: AccordionPrimitive.Header.Props) {
  return (
    <AccordionPrimitive.Header
      data-slot="accordion-header"
      className={cn("flex", className)}
      {...props}
    />
  )
}

function AccordionTrigger({
  className,
  children,
  ...props
}: AccordionPrimitive.Trigger.Props) {
  return (
    <AccordionPrimitive.Trigger
      data-slot="accordion-trigger"
      className={cn(
        "group flex flex-1 items-center justify-between gap-2 py-3 text-left text-sm font-medium transition-colors duration-150 outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-ring/60",
        className
      )}
      {...props}
    >
      {children}
      <ChevronDownIcon
        aria-hidden="true"
        className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 ease-out group-data-open:rotate-180"
      />
    </AccordionPrimitive.Trigger>
  )
}

function AccordionPanel({
  className,
  children,
  ...props
}: AccordionPrimitive.Panel.Props) {
  return (
    <AccordionPrimitive.Panel
      data-slot="accordion-panel"
      className={cn(
        "grid grid-rows-[0fr] transition-[grid-template-rows] duration-200 ease-out data-open:grid-rows-[1fr]",
        className
      )}
      {...props}
    >
      <div className="overflow-hidden">
        <div className="pb-3 text-sm leading-relaxed text-muted-foreground">
          {children}
        </div>
      </div>
    </AccordionPrimitive.Panel>
  )
}

export {
  Accordion,
  AccordionHeader,
  AccordionItem,
  AccordionPanel,
  AccordionTrigger,
}
