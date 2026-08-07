/**
 * CC-1 Part D1 — shared table styling tokens. Before this file existed, every
 * data table on the site (quant/page.tsx's cointegration + lead-lag tables)
 * hand-rolled the identical `text-muted border-b border-muted/30` header row
 * and `border-b border-muted/10` body row className strings independently.
 * Exported as plain className strings (not a generic <Table> component)
 * because every table on this site has a genuinely different column set --
 * forcing a generic component would trade real flexibility for a thinner
 * abstraction than these three strings already provide.
 */
export const TABLE_HEADER_ROW = "text-muted border-b border-muted/30";
export const TABLE_HEADER_CELL = "py-2 pr-4";
export const TABLE_BODY_ROW = "border-b border-muted/10";
export const TABLE_BODY_CELL = "py-2 pr-4";
