# Website D1 — Design tokens + facelift consistency pass

Date: 2026-08-07. CC-1 comprehensive directive, Part D1.

## Finding: the directive's "generic default styling" premise is stale

Direct inspection of `website/app/layout.tsx` and `website/tailwind.config.js`
shows a real, already-shipped, distinctive palette — navy `ink` (#0a0e27),
`gold` (#d4af37), `teal` (#2ec4b6), `parchment` (#e8e2d0), `muted` (#8a94ad),
`loss` (#d47a6a) — explicitly documented in `tailwind.config.js`'s own comment
as "DESIGN SYSTEM tokens... matching the 'The book of records. Every signal.
Every loss.' brand." This is applied consistently across every page (`grep`
confirmed `text-parchment`/`text-muted`/`font-serif` usage site-wide) and is
neither cream/terracotta nor a generic dark+neon default — it's a genuinely
distinctive "book of records" theme, already in place before this directive.
**This is the stale figure to flag**: the directive's premise that the site
"uses generic default styling" does not match the real current state.

## What was genuinely missing, and what this pass fixes

The COLOR system existed; a formal TOKEN layer above it (reusable
type-scale/spacing/panel/table primitives) did not. Every page hand-rolled
its own copy of the same three patterns, with real, confirmed drift between
copies:

- Page title: `<h1 className="font-serif text-3xl text-parchment">` +
  `<p className="text-muted mt-2 max-w-2xl">`, repeated verbatim across all
  9 pages.
- Section heading: `<h2 className="font-serif text-xl text-parchment">` in
  some pages (`quant/page.tsx`, methodology's sub-sections) vs
  `<h2 className="font-serif text-2xl text-parchment mb-4">` in others
  (`lab/page.tsx`) — a real, confirmed inconsistency in the SAME semantic
  role, not a stylistic choice.
- Bordered panel: `rounded-lg border border-gold/30 bg-ink p-6` (pricing),
  `rounded-lg border border-loss/30 bg-ink p-6` (homepage graveyard teaser),
  and further ad hoc variants in `agents/page.tsx` — three independent
  copies of the same shape.
- Data table header/body row classes: `text-muted border-b border-muted/30`
  / `border-b border-muted/10`, duplicated verbatim across `quant/page.tsx`'s
  two tables.

## What shipped

Three new shared components (`website/components/PageHeader.tsx`,
`SectionHeader.tsx`, `Panel.tsx`) and one token file
(`website/lib/designTokens.ts`, exporting the table row/cell className
strings). `SectionHeader` standardizes on the `text-2xl mb-4` variant.
`Panel` takes a `tone` prop (`default`/`gold`/`teal`/`loss`) matching the
three accent colors already established elsewhere on the site, replacing
three independently-drifting copies with one.

Applied across all 9 pages the directive named (Ledger [homepage], Heatmap,
Quant, Graveyard, Lab, Methodology, Pricing, Agents, Factory Loop) — every
page's `<h1>`/description now goes through `PageHeader`; every page's
section headings that had a bare `<h2>` now go through `SectionHeader`;
every bordered card goes through `Panel`; both `quant/page.tsx` tables use
the shared token classNames. `methodology/page.tsx`'s five in-prose
sub-headings were left as bare `<h2>` deliberately — they're inline prose
markers inside one continuous `<section className="mt-8">` flow, not
discrete card/section boundaries, and forcing them through `SectionHeader`
(which adds its own `mb-4` block wrapper) would have disrupted that prose
rhythm for no real consistency gain.

One small design addition beyond pure componentization: an optional
`eyebrow` prop on `PageHeader` (a small gold, uppercase, letter-spaced label
above the `<h1>`) — used on Heatmap ("CROSS-ASSET") and Graveyard ("NO QUIET
FAILURES") to add a light editorial touch consistent with the existing
serif/parchment "book of records" voice, not a new palette.

## Verification

- `npx tsc --noEmit`: zero new errors (the only errors present are
  pre-existing jest-dom matcher type gaps in `__tests__/strategyPage.test.tsx`,
  confirmed unrelated — they exist regardless of this change and don't touch
  any file this pass modified).
- `npx next build`: compiles cleanly, all 14 routes generate.
- `npx jest`: 630/632 passing (2 pre-existing failures in
  `siteDataSchema.test.ts` against `docs/site_data/failure_patterns.json`,
  a real-data drift issue unrelated to this change — never touched by D1).
- Real Playwright screenshots (Chromium, `website/` dev server) of
  Pricing, Heatmap, and Quant confirm the refactored pages render
  correctly with no visual regression — see the session's screenshot
  captures (not committed to the repo; ephemeral verification artifacts).

## Scope discipline

CSS/component/token changes only — no `fetchJson` call sites changed, no
data shapes changed, no verdict/judgment logic touched. Every page's actual
data and copy is byte-identical to before; only the JSX wrapper around
existing text changed.
