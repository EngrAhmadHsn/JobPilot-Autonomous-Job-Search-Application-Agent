/*
  The screen heading, re-exported from its one implementation.

  WS-42 consolidated this: `components/ui/page-header.tsx` is the only
  definition, and this module exists so the screens that already import
  `@/components/common/page-header` keep working. Before that there were two
  headers — one with a `meta` row and one without, with different type sizes —
  and half the console imported each, so the same title rendered two ways.
*/
export { PageHeader, Section } from "@/components/ui/page-header"
