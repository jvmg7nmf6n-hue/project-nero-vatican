import { NO_SIGNAL_YET, deriveCurrentStatus } from "./status";
import type { LedgerRow, StrategyRosterEntry } from "./types";

// A strategy card answers two different questions: "has this strategy earned
// trust?" (research status / tier, see lib/tier.ts -- static, backtest-derived)
// and "what is it doing right now?" (this file -- dynamic, ledger-derived).
// SignalState is a small display-level grouping on top of deriveCurrentStatus's
// raw ledger signal_type / NO_SIGNAL_YET, so the card can style each state
// distinctly without duplicating the ledger-matching logic itself.
export type SignalState = "entry" | "exit" | "watching" | "no_signal_yet";

export const SIGNAL_STATE_LABELS: Record<SignalState, string> = {
  entry: "ENTRY",
  exit: "EXIT",
  watching: "WATCHING",
  no_signal_yet: "NO SIGNAL YET",
};

// Tailwind color-class strings for each state deliberately live in
// StrategyCard.tsx, not here -- tailwind.config.ts's `content` glob only scans
// app/**/*.{ts,tsx} and components/**/*.{ts,tsx}, not lib/, so class-name
// strings placed in this file would never be picked up by Tailwind's static
// scanner and would silently produce unstyled output in production.

// WATCH and NO_TRADE both mean "evaluated, no position open" -- the same
// message to a reader ("it's watching, not trading") -- so they share the
// neutral-gray WATCHING state rather than needing a 5th visual bucket.
// Anything else (including NO_SIGNAL_YET, and any future signal_type this
// mapping doesn't yet know about) falls back to "no_signal_yet" rather than
// guessing a more specific state.
function mapRawStatusToSignalState(rawStatus: string): SignalState {
  switch (rawStatus) {
    case "ENTRY":
      return "entry";
    case "EXIT":
      return "exit";
    case "WATCH":
    case "NO_TRADE":
      return "watching";
    default:
      return "no_signal_yet";
  }
}

export function deriveSignalState(
  entry: Pick<StrategyRosterEntry, "name" | "asset">,
  recentRows: LedgerRow[]
): SignalState {
  const rawStatus = deriveCurrentStatus(entry, recentRows);
  return rawStatus === NO_SIGNAL_YET ? "no_signal_yet" : mapRawStatusToSignalState(rawStatus);
}
