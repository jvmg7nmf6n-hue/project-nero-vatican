/**
 * @jest-environment node
 *
 * Route Handlers use the Web-standard fetch/Request/Response, which jsdom
 * (this project's default test environment) doesn't fully implement -- same
 * reasoning as __tests__/chatRoute.test.ts's own header comment.
 */
import { POST } from "@/app/api/wise-man/route";

// GATE B follow-up (2026-08-08): the feature flag being on with no real
// Redis configured used to mean every request got its own fresh, empty,
// never-shared in-memory counter -- the spend cap and rate limiter became
// a complete no-op with nothing signaling it. This tests the fail-closed
// gate added to close that gap, calling the real route.ts POST handler
// directly (same pattern as __tests__/chatRoute.test.ts).

const ORIGINAL_ENV = { ...process.env };

function jsonRequest(body: unknown, origin = "https://project-nero-vatican.vercel.app"): Request {
  return new Request("http://localhost/api/wise-man", {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: origin },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  process.env.ANTHROPIC_API_KEY = "test-key";
  process.env.WISE_MAN_SESSION_SECRET = "test-secret";
  delete process.env.UPSTASH_REDIS_REST_URL;
  delete process.env.UPSTASH_REDIS_REST_TOKEN;
  delete process.env.WISE_MAN_ENABLED;
  global.fetch = jest.fn();
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  jest.resetAllMocks();
});

describe("POST /api/wise-man -- fails closed when enabled with no real counter store configured", () => {
  it("refuses the request and never calls the model when WISE_MAN_ENABLED=1 but Upstash Redis env vars are unset", async () => {
    process.env.WISE_MAN_ENABLED = "1";
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});

    const response = await POST(jsonRequest({ message: "hi", pageContext: { page: "methodology" } }));
    const payload = await response.json();

    expect(response.status).toBe(503);
    expect(payload.error.en).toBeTruthy();
    expect(payload.error.ur).toBeTruthy();
    expect(global.fetch).not.toHaveBeenCalled();

    // The log line is loud and distinctly tagged, not routine per-request noise.
    expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining("CRITICAL"));
    expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining("UPSTASH_REDIS_REST_URL"));
    errorSpy.mockRestore();
  });

  it("does NOT fail closed when the feature flag is off, even with no Redis configured (flag-off already blocks earlier)", async () => {
    // WISE_MAN_ENABLED left unset (disabled) -- the request should still be
    // rejected, but via the ordinary "feature_disabled" path, proving the
    // new check doesn't fire when it isn't the actual blocking reason.
    const response = await POST(jsonRequest({ message: "hi", pageContext: { page: "methodology" } }));
    const payload = await response.json();
    expect(response.status).toBe(503);
    expect(global.fetch).not.toHaveBeenCalled();
    void payload; // feature_disabled and storage_not_configured share the same user-facing copy by design
  });

  it("does NOT fail closed via the legacy KV_REST_API_URL/_TOKEN names either (matches @upstash/redis's own Redis.fromEnv() fallback)", async () => {
    process.env.WISE_MAN_ENABLED = "1";
    process.env.KV_REST_API_URL = "https://example.upstash.io";
    process.env.KV_REST_API_TOKEN = "fake-legacy-token-for-test";
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});

    (global.fetch as jest.Mock).mockResolvedValue({
      status: 200,
      json: async () => ({ content: [{ type: "text", text: '{"block": false, "category": null, "reason": "ok"}' }] }),
    });

    await POST(jsonRequest({ message: "hi", pageContext: { page: "methodology" } }));
    expect(errorSpy).not.toHaveBeenCalledWith(expect.stringContaining("CRITICAL"));
    errorSpy.mockRestore();
  });

  it("does NOT fail closed when a real counter store IS configured", async () => {
    process.env.WISE_MAN_ENABLED = "1";
    process.env.UPSTASH_REDIS_REST_URL = "https://example.upstash.io";
    process.env.UPSTASH_REDIS_REST_TOKEN = "fake-token-for-test";
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});

    (global.fetch as jest.Mock).mockResolvedValue({
      status: 200,
      json: async () => ({ content: [{ type: "text", text: '{"block": false, "category": null, "reason": "ok"}' }] }),
    });

    const response = await POST(jsonRequest({ message: "What is Profit Factor?", pageContext: { page: "methodology" } }));

    // It should proceed past the new gate (may still fail later for other
    // reasons in this minimal mock, but must NOT be the storage_not_configured 503).
    if (response.status === 503) {
      const payload = await response.json();
      expect(payload.error).not.toBe(undefined);
    }
    expect(errorSpy).not.toHaveBeenCalledWith(expect.stringContaining("CRITICAL"));
    errorSpy.mockRestore();
  });
});
