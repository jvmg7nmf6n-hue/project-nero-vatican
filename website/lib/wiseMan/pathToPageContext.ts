// Maps the current URL pathname to a PageContextIdentifier, client-side, so
// the widget knows which page it's on with ZERO extra user action (Sec 5) --
// no page needs to pass its own identifier down through the tree; WiseMan
// derives it itself from next/navigation's usePathname().

import type { PageContextIdentifier } from "./pageContext";

export function resolvePathToPageContext(pathname: string): PageContextIdentifier {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return { page: "home" };
  if (segments[0] === "strategy" && segments[1]) return { page: "strategy", id: decodeURIComponent(segments[1]) };

  const knownPages = [
    "agents", "factory-loop", "graveyard", "heatmap", "lab", "ledger",
    "macro", "methodology", "pricing", "quant", "signals",
  ] as const;
  const match = knownPages.find((p) => p === segments[0]);
  if (match) return { page: match };

  // An unrecognized route (a future page not yet wired into the resolver)
  // -- fall back to home rather than throwing, so the widget never breaks
  // navigation on a new page it doesn't know about yet.
  return { page: "home" };
}
