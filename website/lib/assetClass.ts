import type { StrategyRosterEntry } from "./types";

export type AssetClass = "Crypto" | "Gold" | "Silver" | "Forex" | "Stocks";

export const ASSET_CLASS_ORDER: AssetClass[] = [
  "Crypto",
  "Gold",
  "Silver",
  "Forex",
  "Stocks",
];

const CRYPTO_ASSETS = new Set(["BTC", "ETH", "BNB", "SOL"]);
const FOREX_ASSETS = new Set(["EUR/USD", "GBP/USD", "USD/JPY"]);

// Anything not recognized as crypto/gold/silver/forex defaults to Stocks
// (e.g. the PEAD tickers: AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META).
function classifySingleAsset(asset: string): AssetClass {
  if (CRYPTO_ASSETS.has(asset)) return "Crypto";
  if (asset === "GOLD") return "Gold";
  if (asset === "SILVER") return "Silver";
  if (FOREX_ASSETS.has(asset)) return "Forex";
  return "Stocks";
}

export interface AssetClassification {
  assetClass: AssetClass;
  isPair: boolean;
}

// Pair assets (e.g. "GOLD-SILVER", "BTC-ETH") are classified by their first
// (dominant) leg and flagged so callers can render them in a separate
// "Pairs" sub-group rather than mixing them into the single-asset grid.
export function classifyAsset(asset: string): AssetClassification {
  if (asset.includes("-")) {
    const [dominant] = asset.split("-");
    return { assetClass: classifySingleAsset(dominant), isPair: true };
  }
  return { assetClass: classifySingleAsset(asset), isPair: false };
}

export interface AssetClassGroup {
  assetClass: AssetClass;
  primary: StrategyRosterEntry[];
  pairs: StrategyRosterEntry[];
}

export function groupRosterByAssetClass(
  roster: StrategyRosterEntry[]
): AssetClassGroup[] {
  const buckets = new Map<AssetClass, AssetClassGroup>();
  for (const assetClass of ASSET_CLASS_ORDER) {
    buckets.set(assetClass, { assetClass, primary: [], pairs: [] });
  }

  for (const entry of roster) {
    const { assetClass, isPair } = classifyAsset(entry.asset);
    const bucket = buckets.get(assetClass)!;
    (isPair ? bucket.pairs : bucket.primary).push(entry);
  }

  return ASSET_CLASS_ORDER.map((assetClass) => buckets.get(assetClass)!);
}
