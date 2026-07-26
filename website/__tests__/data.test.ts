import { fetchCandleData, fetchJson } from "@/lib/data";

const originalFetch = global.fetch;

afterEach(() => {
  global.fetch = originalFetch;
  jest.resetAllMocks();
});

describe("fetchJson", () => {
  it("returns null when the fetch call rejects", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network down"));
    const result = await fetchJson("ledger_recent.json");
    expect(result).toBeNull();
  });

  it("returns null on a non-ok response", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      json: async () => ({}),
    });
    const result = await fetchJson("ledger_recent.json");
    expect(result).toBeNull();
  });

  it("returns null when the response body fails to parse as JSON", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => {
        throw new Error("invalid json");
      },
    });
    const result = await fetchJson("ledger_recent.json");
    expect(result).toBeNull();
  });

  it("returns the parsed payload on success", async () => {
    const payload = { schema_version: 1, rows: [] };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    });
    const result = await fetchJson("ledger_recent.json");
    expect(result).toEqual(payload);
  });
});

describe("fetchCandleData", () => {
  it("returns status 'ok' with the parsed payload on success, using the sanitized filename", async () => {
    const payload = { schema_version: 1, asset: "EUR/USD", timeframe: "1week", last_updated: "x", candles: [] };
    const mockFetch = jest.fn().mockResolvedValue({ status: 200, ok: true, json: async () => payload });
    global.fetch = mockFetch;

    const result = await fetchCandleData("EUR/USD", "1week");

    expect(result).toEqual({ status: "ok", data: payload });
    expect(mockFetch.mock.calls[0][0]).toContain("/candles/EURUSD_1week.json");
  });

  it("returns status 'not_found' distinctly from a fetch failure (404)", async () => {
    global.fetch = jest.fn().mockResolvedValue({ status: 404, ok: false, json: async () => ({}) });
    const result = await fetchCandleData("BTC", "24h");
    expect(result).toEqual({ status: "not_found" });
  });

  it("returns status 'error' on a non-404 non-ok response", async () => {
    global.fetch = jest.fn().mockResolvedValue({ status: 500, ok: false, json: async () => ({}) });
    const result = await fetchCandleData("BTC", "24h");
    expect(result).toEqual({ status: "error" });
  });

  it("returns status 'error' when the fetch call rejects", async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error("network down"));
    const result = await fetchCandleData("BTC", "24h");
    expect(result).toEqual({ status: "error" });
  });

  it("maps NEWS_SENTIMENT's 'daily' roster timeframe onto the '24h' candle file", async () => {
    const mockFetch = jest.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ schema_version: 1, asset: "GOLD", timeframe: "24h", last_updated: "x", candles: [] }),
    });
    global.fetch = mockFetch;

    await fetchCandleData("GOLD", "daily");

    expect(mockFetch.mock.calls[0][0]).toContain("/candles/GOLD_24h.json");
  });
});
