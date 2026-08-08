import {
  checkGuardrail,
  logGuardrailEvent,
  WiseManContentBlock,
  ANTHROPIC_API_URL,
  ANTHROPIC_VERSION,
} from "@/lib/wiseMan/guardrail";
import { ANTHROPIC_API_URL as CHAT_API_URL, ANTHROPIC_VERSION as CHAT_API_VERSION } from "@/lib/chatApi";

describe("guardrail.ts reinlined constants stay byte-identical to chatApi.ts (drift guard)", () => {
  it("ANTHROPIC_API_URL matches", () => {
    expect(ANTHROPIC_API_URL).toBe(CHAT_API_URL);
  });
  it("ANTHROPIC_VERSION matches", () => {
    expect(ANTHROPIC_VERSION).toBe(CHAT_API_VERSION);
  });
});

function mockFetchOk(body: unknown): jest.Mock {
  return jest.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
  });
}

function anthropicTextResponse(text: string) {
  return { content: [{ type: "text", text }] };
}

describe("checkGuardrail (CC-1 Wise Man directive Sec 4.1)", () => {
  const TEXT_BLOCK: WiseManContentBlock = { type: "text", text: "Should I buy BTC?" };
  const IMAGE_BLOCK: WiseManContentBlock = { type: "image", mediaType: "image/png", dataBase64: "AAA=" };
  const DOC_BLOCK: WiseManContentBlock = { type: "document", mediaType: "application/pdf", dataBase64: "BBB=" };

  it("all four input shapes (typed text, voice-transcribed text, image, document) call the SAME shared fetch code path", async () => {
    // Voice-transcribed text arrives as plain text -- same shape as typed
    // text, proving there is no separate voice-input branch.
    const VOICE_TRANSCRIBED_BLOCK: WiseManContentBlock = { type: "text", text: "kya mujhe BTC lena chahiye" };

    for (const blocks of [[TEXT_BLOCK], [VOICE_TRANSCRIBED_BLOCK], [IMAGE_BLOCK, TEXT_BLOCK], [DOC_BLOCK, TEXT_BLOCK]]) {
      const fetchImpl = mockFetchOk(anthropicTextResponse('{"block": false, "category": null, "reason": "ok"}'));
      await checkGuardrail({ blocks, direction: "inbound", apiKey: "test-key", fetchImpl });
      expect(fetchImpl).toHaveBeenCalledTimes(1);
      const [url, init] = fetchImpl.mock.calls[0];
      expect(url).toContain("api.anthropic.com");
      const body = JSON.parse((init as RequestInit).body as string);
      expect(body.model).toBe("claude-haiku-4-5");
      expect(Array.isArray(body.messages[0].content)).toBe(true);
    }
  });

  it("inbound and outbound directions both go through checkGuardrail (same function, direction is just a parameter)", async () => {
    const fetchImpl = mockFetchOk(anthropicTextResponse('{"block": false, "category": null, "reason": "ok"}'));
    const inbound = await checkGuardrail({ blocks: [TEXT_BLOCK], direction: "inbound", apiKey: "k", fetchImpl });
    const outbound = await checkGuardrail({ blocks: [TEXT_BLOCK], direction: "outbound", apiKey: "k", fetchImpl });
    expect(inbound.blocked).toBe(false);
    expect(outbound.blocked).toBe(false);
  });

  it("parses a blocked verdict", async () => {
    const fetchImpl = mockFetchOk(
      anthropicTextResponse('{"block": true, "category": "personal_advice", "reason": "direct ask"}'),
    );
    const verdict = await checkGuardrail({ blocks: [TEXT_BLOCK], direction: "inbound", apiKey: "k", fetchImpl });
    expect(verdict.blocked).toBe(true);
    expect(verdict.category).toBe("personal_advice");
    expect(verdict.failedClosed).toBe(false);
  });

  it("strips markdown code fences before parsing (observed real-world model behavior)", async () => {
    const fetchImpl = mockFetchOk(anthropicTextResponse('```json\n{"block": false, "category": null, "reason": "fine"}\n```'));
    const verdict = await checkGuardrail({ blocks: [TEXT_BLOCK], direction: "inbound", apiKey: "k", fetchImpl });
    expect(verdict.blocked).toBe(false);
  });

  it("FAILS CLOSED on a network error (Sec 4.1.6)", async () => {
    const fetchImpl = jest.fn().mockRejectedValue(new Error("network down"));
    const verdict = await checkGuardrail({ blocks: [TEXT_BLOCK], direction: "inbound", apiKey: "k", fetchImpl });
    expect(verdict.blocked).toBe(true);
    expect(verdict.failedClosed).toBe(true);
  });

  it("FAILS CLOSED on a non-200 upstream response", async () => {
    const fetchImpl = jest.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) });
    const verdict = await checkGuardrail({ blocks: [TEXT_BLOCK], direction: "inbound", apiKey: "k", fetchImpl });
    expect(verdict.blocked).toBe(true);
    expect(verdict.failedClosed).toBe(true);
  });

  it("FAILS CLOSED on malformed JSON in the model's reply", async () => {
    const fetchImpl = mockFetchOk(anthropicTextResponse("not json at all"));
    const verdict = await checkGuardrail({ blocks: [TEXT_BLOCK], direction: "inbound", apiKey: "k", fetchImpl });
    expect(verdict.blocked).toBe(true);
    expect(verdict.failedClosed).toBe(true);
  });

  it("FAILS CLOSED when the response is missing the required 'block' field", async () => {
    const fetchImpl = mockFetchOk(anthropicTextResponse('{"category": null, "reason": "oops, no block field"}'));
    const verdict = await checkGuardrail({ blocks: [TEXT_BLOCK], direction: "inbound", apiKey: "k", fetchImpl });
    expect(verdict.blocked).toBe(true);
    expect(verdict.failedClosed).toBe(true);
  });

  it("never sends the API key anywhere except the x-api-key header", async () => {
    const fetchImpl = mockFetchOk(anthropicTextResponse('{"block": false, "category": null, "reason": "ok"}'));
    await checkGuardrail({ blocks: [TEXT_BLOCK], direction: "inbound", apiKey: "sk-secret-value", fetchImpl });
    const [, init] = fetchImpl.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["x-api-key"]).toBe("sk-secret-value");
    expect((init as RequestInit).body as string).not.toContain("sk-secret-value");
  });
});

describe("logGuardrailEvent (Sec 4.1.7 observability, never logs raw content)", () => {
  it("logs only classification metadata, never the raw user text", () => {
    const spy = jest.spyOn(console, "log").mockImplementation(() => {});
    const secretUserText = "my extremely private financial question about BTC";
    logGuardrailEvent({
      direction: "inbound",
      inputTypes: ["text"],
      blocked: true,
      category: "personal_advice",
      failedClosed: false,
      timestamp: "2026-08-08T00:00:00.000Z",
    });
    expect(spy).toHaveBeenCalledTimes(1);
    const logged = spy.mock.calls[0][0] as string;
    expect(logged).not.toContain(secretUserText);
    const parsed = JSON.parse(logged);
    expect(parsed.tag).toBe("[wise-man-guardrail]");
    expect(parsed.blocked).toBe(true);
    spy.mockRestore();
  });
});
