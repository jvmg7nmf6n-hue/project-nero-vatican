import {
  formatCountdown,
  formatPrice,
  latestPrice,
  mapSignalStateToMarketStatus,
  nextCandleBoundaryMs,
  priceChangePercent,
} from "@/lib/marketStatus";
import type { Candle } from "@/lib/candleData";

function candle(overrides: Partial<Candle> = {}): Candle {
  return { time: 1700000000, open: 100, high: 101, low: 99, close: 100.5, volume: 1000, ...overrides };
}

describe("latestPrice", () => {
  it("returns null for an empty candle array", () => {
    expect(latestPrice([])).toBeNull();
  });

  it("returns the close of the last candle", () => {
    expect(latestPrice([candle({ close: 100 }), candle({ close: 105.25 })])).toBe(105.25);
  });
});

describe("priceChangePercent", () => {
  it("returns null with fewer than 2 candles", () => {
    expect(priceChangePercent([])).toBeNull();
    expect(priceChangePercent([candle()])).toBeNull();
  });

  it("computes percent change between the last two candles", () => {
    const result = priceChangePercent([candle({ close: 100 }), candle({ close: 105 })]);
    expect(result).toBeCloseTo(5, 5);
  });

  it("computes a negative percent change", () => {
    const result = priceChangePercent([candle({ close: 100 }), candle({ close: 95 })]);
    expect(result).toBeCloseTo(-5, 5);
  });

  it("returns null rather than dividing by zero when the prior close is 0", () => {
    expect(priceChangePercent([candle({ close: 0 }), candle({ close: 10 })])).toBeNull();
  });
});

describe("formatPrice", () => {
  it("formats crypto as a rounded integer with a $ and thousands separator", () => {
    expect(formatPrice("BTC", 65432.17)).toBe("$65,432");
  });

  it("formats metals/stocks with 2 decimal places and a $", () => {
    expect(formatPrice("GOLD", 3287.5)).toBe("$3,287.50");
    expect(formatPrice("AAPL", 189.3)).toBe("$189.30");
  });

  it("formats forex with 4 decimal places and no $ sign", () => {
    expect(formatPrice("EUR/USD", 1.0823)).toBe("1.0823");
  });
});

describe("nextCandleBoundaryMs", () => {
  it("returns null for an unsupported timeframe", () => {
    expect(nextCandleBoundaryMs(1700000000, "4h")).toBeNull();
  });

  it("computes the next 00:00 UTC boundary for 24h", () => {
    // 2026-07-20T15:30:00Z
    const lastSeconds = Date.UTC(2026, 6, 20, 15, 30, 0) / 1000;
    const boundary = nextCandleBoundaryMs(lastSeconds, "24h");
    expect(boundary).toBe(Date.UTC(2026, 6, 21, 0, 0, 0));
  });

  it("computes the next 12:00 UTC boundary for 12h when before noon", () => {
    const lastSeconds = Date.UTC(2026, 6, 20, 3, 0, 0) / 1000;
    const boundary = nextCandleBoundaryMs(lastSeconds, "12h");
    expect(boundary).toBe(Date.UTC(2026, 6, 20, 12, 0, 0));
  });

  it("computes the next 00:00 UTC boundary for 12h when after noon", () => {
    const lastSeconds = Date.UTC(2026, 6, 20, 18, 0, 0) / 1000;
    const boundary = nextCandleBoundaryMs(lastSeconds, "12h");
    expect(boundary).toBe(Date.UTC(2026, 6, 21, 0, 0, 0));
  });

  it("computes next Monday 00:00 UTC for 1week from a mid-week date", () => {
    // 2026-07-22 is a Wednesday
    const lastSeconds = Date.UTC(2026, 6, 22, 0, 0, 0) / 1000;
    const boundary = nextCandleBoundaryMs(lastSeconds, "1week");
    // Next Monday is 2026-07-27
    expect(boundary).toBe(Date.UTC(2026, 6, 27, 0, 0, 0));
    expect(new Date(boundary!).getUTCDay()).toBe(1);
  });

  it("computes 7 days ahead for 1week when the candle is already exactly on a Monday boundary", () => {
    // 2026-07-20 is a Monday
    const lastSeconds = Date.UTC(2026, 6, 20, 0, 0, 0) / 1000;
    const boundary = nextCandleBoundaryMs(lastSeconds, "1week");
    expect(boundary).toBe(Date.UTC(2026, 6, 27, 0, 0, 0));
  });
});

describe("formatCountdown", () => {
  it("formats hours and minutes", () => {
    expect(formatCountdown(4 * 60 * 60 * 1000 + 23 * 60 * 1000)).toBe("4h 23m");
  });

  it("formats minutes only when under an hour", () => {
    expect(formatCountdown(45 * 60 * 1000)).toBe("45m");
  });

  it("shows 'due now' for a non-positive remaining time", () => {
    expect(formatCountdown(0)).toBe("due now");
    expect(formatCountdown(-1000)).toBe("due now");
  });
});

describe("mapSignalStateToMarketStatus", () => {
  it("maps entry to ENTRY ACTIVE", () => {
    expect(mapSignalStateToMarketStatus("entry")).toBe("ENTRY ACTIVE");
  });

  it("maps no_signal_yet to NO SIGNAL", () => {
    expect(mapSignalStateToMarketStatus("no_signal_yet")).toBe("NO SIGNAL");
  });

  it("maps watching and exit both to WATCHING", () => {
    expect(mapSignalStateToMarketStatus("watching")).toBe("WATCHING");
    expect(mapSignalStateToMarketStatus("exit")).toBe("WATCHING");
  });
});
