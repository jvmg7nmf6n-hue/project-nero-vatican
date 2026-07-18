import { fetchJson } from "@/lib/data";

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
