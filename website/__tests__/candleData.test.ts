import { candleFileTimeframe, candleFilename, sanitizeAssetForFilename } from "@/lib/candleData";

describe("sanitizeAssetForFilename", () => {
  it("strips the slash from forex pairs", () => {
    expect(sanitizeAssetForFilename("EUR/USD")).toBe("EURUSD");
    expect(sanitizeAssetForFilename("GBP/USD")).toBe("GBPUSD");
    expect(sanitizeAssetForFilename("USD/JPY")).toBe("USDJPY");
  });

  it("leaves a non-forex asset unchanged", () => {
    expect(sanitizeAssetForFilename("BTC")).toBe("BTC");
    expect(sanitizeAssetForFilename("GOLD")).toBe("GOLD");
  });
});

describe("candleFileTimeframe", () => {
  it("maps NEWS_SENTIMENT's 'daily' label onto '24h'", () => {
    expect(candleFileTimeframe("daily")).toBe("24h");
  });

  it("passes every other roster timeframe through unchanged", () => {
    expect(candleFileTimeframe("24h")).toBe("24h");
    expect(candleFileTimeframe("12h")).toBe("12h");
    expect(candleFileTimeframe("1week")).toBe("1week");
    expect(candleFileTimeframe("1day")).toBe("1day");
    expect(candleFileTimeframe("snapshot")).toBe("snapshot");
  });
});

describe("candleFilename", () => {
  it("combines the sanitized asset and the aliased timeframe", () => {
    expect(candleFilename("EUR/USD", "1week")).toBe("EURUSD_1week.json");
    expect(candleFilename("GOLD", "daily")).toBe("GOLD_24h.json");
    expect(candleFilename("BTC", "24h")).toBe("BTC_24h.json");
  });
});
