import type { LedgerRow } from "./types";

// CC-1 overnight directive, Part 5.2: a short per-row commentary note,
// derived ONLY from real fields already on the row -- never invented.
//
// The only real field pair this can be meaningfully derived from for a
// RESOLVED trade (an EXIT row) is entry_price/exit_price -- the real
// percentage move between them. Every other row shape (ENTRY, NO_TRADE,
// WATCH, or an EXIT missing either price) has no real margin to report,
// so this returns an honest empty string rather than a fabricated note --
// matching this component's own existing isLoss()'s same "both prices
// required" precondition, not a new convention.
export function deriveLedgerCommentary(row: LedgerRow): string {
  if (row.signal_type !== "EXIT") return "";
  if (row.entry_price === null || row.exit_price === null || row.entry_price === 0) return "";

  const pctMove = ((row.exit_price - row.entry_price) / row.entry_price) * 100;
  const sign = pctMove >= 0 ? "+" : "";
  return `${sign}${pctMove.toFixed(2)}% vs entry`;
}
