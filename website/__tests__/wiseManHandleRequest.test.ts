import { handleWiseManRequest, WiseManDeps, WiseManRequestInput } from "@/lib/wiseMan/handleRequest";
import { createInMemoryCounterStore } from "@/lib/wiseMan/budget";
import { createSessionToken } from "@/lib/wiseMan/session";

const SECRET = "test-secret";

function textResponse(text: string) {
  return { ok: true, status: 200, json: async () => ({ content: [{ type: "text", text }] }) };
}

/** Distinguishes guardrail calls (system: string) from generation calls
 * (system: array) by inspecting the request body, so one mock can drive a
 * full request through inbound guardrail -> generation -> outbound guardrail. */
function makeFetch(opts: { inboundBlocked?: boolean; outboundBlocked?: boolean; replyText?: string }) {
  let call = 0;
  return jest.fn(async (_url: string, init: RequestInit) => {
    call++;
    const body = JSON.parse(init.body as string);
    const isGuardrailCall = typeof body.system === "string";
    if (isGuardrailCall) {
      // First guardrail call in a request is inbound, second (if any) is outbound.
      const isFirstGuardrailCallSoFar = call === 1;
      const blocked = isFirstGuardrailCallSoFar ? opts.inboundBlocked ?? false : opts.outboundBlocked ?? false;
      return textResponse(JSON.stringify({ block: blocked, category: blocked ? "personal_advice" : null, reason: "x" }));
    }
    return textResponse(opts.replyText ?? "This is Wise Man's answer.");
  });
}

function baseDeps(overrides: Partial<WiseManDeps> = {}): WiseManDeps {
  return {
    apiKey: "test-key",
    sessionSecret: SECRET,
    store: createInMemoryCounterStore(),
    budgetConfig: { dailyCapCents: 1000, monthlyCapCents: 5000 },
    rateLimitConfig: { perSessionPerHour: 30, perIpPerHour: 100, perSessionAttachmentPerHour: 8 },
    allowedOrigins: ["https://project-nero-vatican.vercel.app"],
    enabled: true,
    ...overrides,
  };
}

function baseInput(overrides: Partial<WiseManRequestInput> = {}): WiseManRequestInput {
  return {
    message: "What does Profit Factor mean?",
    pageContext: { page: "methodology" },
    sessionToken: null,
    ip: "1.2.3.4",
    origin: "https://project-nero-vatican.vercel.app",
    ...overrides,
  };
}

describe("handleWiseManRequest (Sec 5/6/8 full orchestration)", () => {
  it("happy path: returns the reply and mints a new session cookie", async () => {
    const fetchImpl = makeFetch({ replyText: "Profit Factor is gross profit divided by gross loss." });
    const result = await handleWiseManRequest(baseInput(), baseDeps({ fetchImpl: fetchImpl as unknown as typeof fetch }));
    expect(result.httpStatus).toBe(200);
    expect(result.reply).toContain("Profit Factor");
    expect(result.newSessionToken).toBeTruthy();
  });

  it("feature flag off (Sec 8.1): rejects before touching the network", async () => {
    const fetchImpl = jest.fn();
    const result = await handleWiseManRequest(baseInput(), baseDeps({ enabled: false, fetchImpl }));
    expect(result.httpStatus).toBe(503);
    expect(result.errorCode).toBe("feature_disabled");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("origin restriction (Sec 8.5): rejects a mismatched Origin", async () => {
    const fetchImpl = jest.fn();
    const result = await handleWiseManRequest(baseInput({ origin: "https://evil.com" }), baseDeps({ fetchImpl }));
    expect(result.httpStatus).toBe(403);
    expect(result.errorCode).toBe("origin_forbidden");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("input caps (Sec 8.4): rejects an over-length message", async () => {
    const fetchImpl = jest.fn();
    const result = await handleWiseManRequest(baseInput({ message: "x".repeat(5000) }), baseDeps({ fetchImpl }));
    expect(result.httpStatus).toBe(400);
    expect(result.errorCode).toBe("input_too_long");
  });

  it("input caps: rejects a conversation past MAX_TURNS_PER_CONVERSATION", async () => {
    const fetchImpl = jest.fn();
    const history = Array.from({ length: 25 }, (_, i) => ({ role: "user" as const, text: `turn ${i}` }));
    const result = await handleWiseManRequest(baseInput({ history }), baseDeps({ fetchImpl }));
    expect(result.httpStatus).toBe(400);
    expect(result.errorCode).toBe("too_many_turns");
  });

  it("rejects an invalid page context identifier", async () => {
    const fetchImpl = jest.fn();
    const result = await handleWiseManRequest(baseInput({ pageContext: { page: "not-a-real-page" } }), baseDeps({ fetchImpl }));
    expect(result.httpStatus).toBe(400);
    expect(result.errorCode).toBe("invalid_request");
  });

  it("attachment validation (Sec 6): rejects garbage bytes claiming to be an attachment", async () => {
    const fetchImpl = jest.fn();
    const result = await handleWiseManRequest(
      baseInput({ attachments: [{ dataBase64: Buffer.from("not a real file").toString("base64") }] }),
      baseDeps({ fetchImpl }),
    );
    expect(result.httpStatus).toBe(400);
    expect(result.errorCode).toBe("attachment_invalid");
  });

  it("rate limiting (Sec 8.3): blocks once the per-session limit is exceeded", async () => {
    const store = createInMemoryCounterStore();
    const deps = baseDeps({
      store,
      rateLimitConfig: { perSessionPerHour: 1, perIpPerHour: 100, perSessionAttachmentPerHour: 8 },
      fetchImpl: makeFetch({}) as unknown as typeof fetch,
    });
    const { token } = createSessionToken(SECRET);
    await handleWiseManRequest(baseInput({ sessionToken: token }), deps);
    const second = await handleWiseManRequest(baseInput({ sessionToken: token }), deps);
    expect(second.httpStatus).toBe(429);
    expect(second.errorCode).toBe("rate_limit_session");
  });

  it("rate limit store failure (Sec 8.8): fails closed with a friendly error, never a raw exception, never calls the model", async () => {
    const throwingStore = { incrementAndGet: async () => { throw new Error("redis down"); } };
    const fetchImpl = jest.fn();
    const result = await handleWiseManRequest(baseInput(), baseDeps({ store: throwingStore, fetchImpl }));
    expect(result.httpStatus).toBe(503);
    expect(result.errorCode).toBe("upstream_error");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("budget store failure AFTER rate limiting passes (Sec 8.2, 8.8): fails closed, never calls the model", async () => {
    let calls = 0;
    // Allow the two rate-limit increments (IP, session) through, then throw
    // on the budget check's own increment -- isolates budget-specific
    // fail-closed behavior from the rate-limit path above.
    const store = {
      incrementAndGet: async (key: string, amount: number) => {
        calls++;
        if (calls <= 2) return amount;
        throw new Error("redis down mid-request");
      },
    };
    const fetchImpl = jest.fn();
    const result = await handleWiseManRequest(baseInput(), baseDeps({ store, fetchImpl }));
    expect(result.httpStatus).toBe(503);
    expect(result.errorCode).toBe("upstream_error");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("budget cap: blocks with a friendly message once the daily cap is reached", async () => {
    const store = createInMemoryCounterStore();
    const deps = baseDeps({ store, budgetConfig: { dailyCapCents: 0, monthlyCapCents: 1000 }, fetchImpl: makeFetch({}) as unknown as typeof fetch });
    const result = await handleWiseManRequest(baseInput(), deps);
    expect(result.httpStatus).toBe(503);
    expect(result.errorCode).toBe("budget_daily");
  });

  it("inbound guardrail (Sec 4): blocks before ever calling generation", async () => {
    const fetchImpl = makeFetch({ inboundBlocked: true });
    const result = await handleWiseManRequest(baseInput({ message: "Should I buy BTC right now?" }), baseDeps({ fetchImpl: fetchImpl as unknown as typeof fetch }));
    expect(result.httpStatus).toBe(200);
    expect(result.errorCode).toBe("guardrail_blocked");
    expect(result.reply).toBeUndefined();
    expect(fetchImpl).toHaveBeenCalledTimes(1); // only the inbound guardrail call, generation never ran
  });

  it("outbound guardrail (Sec 4): blocks even if generation itself produced advice-shaped text", async () => {
    const fetchImpl = makeFetch({ outboundBlocked: true, replyText: "You should buy right now." });
    const result = await handleWiseManRequest(baseInput(), baseDeps({ fetchImpl: fetchImpl as unknown as typeof fetch }));
    expect(result.httpStatus).toBe(200);
    expect(result.errorCode).toBe("guardrail_blocked");
    expect(result.reply).toBeUndefined(); // the advice-shaped text never reaches the caller
  });

  it("generation upstream failure: friendly error, not a raw exception (Sec 8.8)", async () => {
    const fetchImpl = jest.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      if (typeof body.system === "string") return textResponse('{"block": false, "category": null, "reason": "ok"}');
      return { ok: false, status: 500, json: async () => ({}) };
    });
    const result = await handleWiseManRequest(baseInput(), baseDeps({ fetchImpl: fetchImpl as unknown as typeof fetch }));
    expect(result.httpStatus).toBe(502);
    expect(result.errorCode).toBe("upstream_error");
  });

  it("a valid existing session token is reused, not replaced", async () => {
    const { token } = createSessionToken(SECRET);
    const fetchImpl = makeFetch({});
    const result = await handleWiseManRequest(baseInput({ sessionToken: token }), baseDeps({ fetchImpl: fetchImpl as unknown as typeof fetch }));
    expect(result.newSessionToken).toBeUndefined();
  });
});
