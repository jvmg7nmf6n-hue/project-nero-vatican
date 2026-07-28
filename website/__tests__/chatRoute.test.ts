/**
 * @jest-environment node
 *
 * Route Handlers use the Web-standard fetch/Request/Response/ReadableStream,
 * which jsdom (this project's default test environment) doesn't fully
 * implement. Node's own runtime provides all of these natively (Node 18+),
 * so this file overrides just its own environment -- the standard, documented
 * way to unit-test a Next.js Route Handler directly.
 */
import fs from "fs";
import path from "path";
import { maxDuration, POST } from "@/app/api/chat/route";
import {
  buildSystemPrompt,
  createSseTextExtractor,
  HISTORY_LIMIT,
  isStrategyChatContext,
  MAX_TOKENS,
  MODEL,
  readAnthropicReplyAsText,
  sanitizeHistory,
  sanitizeMessage,
  STREAM_IDLE_TIMEOUT_MS,
  UPSTREAM_TIMEOUT_MS,
} from "@/lib/chatApi";
import { CLIENT_TIMEOUT_MS } from "@/components/ChatBot";
import type { StrategyChatContext } from "@/lib/types";

const originalFetch = global.fetch;
const originalApiKey = process.env.ANTHROPIC_API_KEY;

const CONTEXT: StrategyChatContext = {
  strategy_name: "BREAKOUT_MOMENTUM",
  asset: "GOLD",
  timeframe: "1week",
  mechanism: "Enters long on a breakout above the recent high.",
  verification_note: "Verified on both backtest halves.",
  win_rate: 0.62,
  current_signal: "WATCHING",
};

function jsonRequest(body: unknown): Request {
  return new Request("http://localhost/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function sseResponse(events: string[]): Response {
  const body = events.join("");
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

afterEach(() => {
  global.fetch = originalFetch;
  process.env.ANTHROPIC_API_KEY = originalApiKey;
  jest.resetAllMocks();
});

describe("sanitizeMessage", () => {
  it("trims whitespace", () => {
    expect(sanitizeMessage("  hello  ")).toBe("hello");
  });

  it("returns null for a non-string value", () => {
    expect(sanitizeMessage(42)).toBeNull();
    expect(sanitizeMessage(null)).toBeNull();
    expect(sanitizeMessage(undefined)).toBeNull();
  });

  it("returns null for an empty or whitespace-only string", () => {
    expect(sanitizeMessage("")).toBeNull();
    expect(sanitizeMessage("   ")).toBeNull();
  });

  it("caps the message at 500 characters", () => {
    const long = "a".repeat(600);
    expect(sanitizeMessage(long)).toHaveLength(500);
  });
});

describe("isStrategyChatContext", () => {
  it("accepts a well-formed context", () => {
    expect(isStrategyChatContext(CONTEXT)).toBe(true);
  });

  it("accepts a null win_rate", () => {
    expect(isStrategyChatContext({ ...CONTEXT, win_rate: null })).toBe(true);
  });

  it("rejects a missing or malformed context", () => {
    expect(isStrategyChatContext(null)).toBe(false);
    expect(isStrategyChatContext({})).toBe(false);
    expect(isStrategyChatContext({ ...CONTEXT, asset: 5 })).toBe(false);
  });
});

describe("sanitizeHistory", () => {
  it("returns an empty array for non-array input", () => {
    expect(sanitizeHistory(null)).toEqual([]);
    expect(sanitizeHistory("not an array")).toEqual([]);
  });

  it("filters out malformed entries and keeps well-formed ones", () => {
    const result = sanitizeHistory([
      { role: "user", content: "hi" },
      { role: "bogus", content: "nope" },
      { role: "assistant" }, // missing content
      { role: "assistant", content: "hello" },
    ]);
    expect(result).toEqual([
      { role: "user", content: "hi" },
      { role: "assistant", content: "hello" },
    ]);
  });

  it(`keeps only the last ${HISTORY_LIMIT} entries, regardless of how long the session's total conversation is`, () => {
    const long = Array.from({ length: HISTORY_LIMIT + 10 }, (_, i) => ({ role: "user" as const, content: `msg${i}` }));
    expect(sanitizeHistory(long)).toHaveLength(HISTORY_LIMIT);
    expect(sanitizeHistory(long)[0]).toEqual({ role: "user", content: "msg10" });
  });
});

describe("MODEL", () => {
  // Regression test for a real incident: MODEL was set to the non-existent
  // "claude-sonnet-4-6", which Anthropic's API rejects with a 404
  // model_not_found error on every single request. The route swallowed that
  // as a generic 502 with no server-side log (see the POST 502-logging test
  // below), so the bot looked "broken" with no visible cause. This test pins
  // MODEL to the verified-working id so a typo'd/stale model string fails
  // CI instead of silently breaking production chat.
  it("is set to a verified-valid Anthropic model id", () => {
    expect(MODEL).toBe("claude-sonnet-5");
  });
});

describe("MAX_TOKENS", () => {
  // Regression test for the "(No response)" truncation incident: 300 tokens
  // left no room for a text reply once a thinking block opened first (see
  // readAnthropicReplyAsText's "captures stop_reason 'max_tokens' with zero
  // text..." test). Pins the raised value so a future edit can't silently
  // drift back down to a budget too thin for the "under 150 words" system
  // prompt cap at non-English token density.
  it("is raised well above the 300-token budget that produced zero-text max_tokens truncations", () => {
    expect(MAX_TOKENS).toBeGreaterThanOrEqual(1024);
  });
});

describe("timeout ordering across the chat path", () => {
  // Regression test for a real incident: the client's own AbortController
  // (CLIENT_TIMEOUT_MS) fired at 10s, SHORTER than the server's per-chunk idle
  // timeout (STREAM_IDLE_TIMEOUT_MS, 15s), so the client could abandon a
  // stream the server was still legitimately serving. maxDuration (30s) is
  // the real worst-case ceiling on total server-side duration -- a slow but
  // alive stream can legally run right up to it. Every stage must be strictly
  // faster than the next, with the client's own give-up point last, so the
  // client is never the one that gives up early on a healthy request.
  it("keeps UPSTREAM_TIMEOUT_MS < STREAM_IDLE_TIMEOUT_MS < maxDuration < CLIENT_TIMEOUT_MS", () => {
    expect(UPSTREAM_TIMEOUT_MS).toBeLessThan(STREAM_IDLE_TIMEOUT_MS);
    expect(STREAM_IDLE_TIMEOUT_MS).toBeLessThan(maxDuration * 1000);
    expect(maxDuration * 1000).toBeLessThan(CLIENT_TIMEOUT_MS);
  });
});

describe("buildSystemPrompt", () => {
  it("interpolates every strategy field into the prompt", () => {
    const prompt = buildSystemPrompt(CONTEXT);
    expect(prompt).toContain("BREAKOUT_MOMENTUM");
    expect(prompt).toContain("GOLD");
    expect(prompt).toContain("1week");
    expect(prompt).toContain("Enters long on a breakout above the recent high.");
    expect(prompt).toContain("62%");
    expect(prompt).toContain("WATCHING");
  });

  it("shows 'not enough data yet' for a null win_rate, never a fabricated percentage", () => {
    const prompt = buildSystemPrompt({ ...CONTEXT, win_rate: null });
    expect(prompt).toContain("not enough data yet");
  });

  it("carries every strict rule and the language-matching instruction", () => {
    const prompt = buildSystemPrompt(CONTEXT);
    expect(prompt).toContain("NEVER guarantee profits");
    expect(prompt).toContain("licensed financial advisor");
    expect(prompt).toContain("respond in THE SAME LANGUAGE");
    expect(prompt).toContain("Never use bullet points");
  });
});

describe("createSseTextExtractor", () => {
  it("extracts text from a single well-formed content_block_delta event", () => {
    const extractor = createSseTextExtractor();
    const chunk =
      'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n';
    expect(extractor.push(chunk)).toBe("Hello");
  });

  it("accumulates text across multiple pushes", () => {
    const extractor = createSseTextExtractor();
    extractor.push('data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hel"}}\n');
    const second = extractor.push('lo\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":" world"}}\n');
    expect(second).toBe(" world");
  });

  it("buffers a data: line split across two chunk boundaries", () => {
    const extractor = createSseTextExtractor();
    const first = extractor.push('data: {"type":"content_block_delta","delta":{"typ');
    expect(first).toBe("");
    const second = extractor.push('e":"text_delta","text":"split"}}\n');
    expect(second).toBe("split");
  });

  it("ignores non-content_block_delta events (message_start, content_block_stop, etc.)", () => {
    const extractor = createSseTextExtractor();
    const chunk = 'data: {"type":"message_start"}\ndata: {"type":"content_block_stop"}\n';
    expect(extractor.push(chunk)).toBe("");
  });

  it("does not crash on a malformed JSON data line", () => {
    const extractor = createSseTextExtractor();
    expect(() => extractor.push("data: {not valid json\n")).not.toThrow();
    expect(extractor.push("data: {not valid json\n")).toBe("");
  });
});

describe("readAnthropicReplyAsText", () => {
  // Regression test for a real incident: UPSTREAM_TIMEOUT_MS's AbortController
  // only guards the initial fetch() in route.ts -- it's cleared the moment
  // headers arrive, before this function ever starts pulling the body. A
  // production request that stalled mid-stream (after successfully starting
  // to download from api.anthropic.com) had no application-level cutoff at
  // all and ran until Vercel's platform maxDuration force-killed the whole
  // function. This proves a stalled upstream body is caught by this
  // function's own idle timeout instead of hanging indefinitely.
  it("throws instead of hanging forever when the upstream body stalls mid-stream", async () => {
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"partial"}}\n'
          )
        );
        // Never closes and never enqueues again -- simulates a stalled upstream connection.
      },
    });

    await expect(readAnthropicReplyAsText(upstreamBody, 50)).rejects.toThrow(/idle/i);
  });

  // A prior version returned a passthrough ReadableStream for incremental
  // rendering. That added a second, independent place a hang could hide: in
  // production the idle timeout fired correctly but the function still ran
  // to the full platform maxDuration, because an errored custom
  // ReadableStream didn't reliably finalize the underlying HTTP response
  // under Next.js's Route Handler streaming. Reading to completion and
  // returning one plain string removes that entire failure-prone path --
  // the route's own await/return is what ends the function.
  it("returns the full accumulated text once the upstream body ends normally", async () => {
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode('data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi "}}\n')
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"there"}}\n'
          )
        );
        controller.close();
      },
    });

    await expect(readAnthropicReplyAsText(upstreamBody, 50)).resolves.toEqual({
      text: "Hi there",
      usage: { inputTokens: null, outputTokens: null },
      diagnostics: {
        stopReason: null,
        contentBlockTypesSeen: [],
        textDeltaCount: 2,
        hadStreamError: false,
        streamErrorType: null,
      },
    });
  });

  // Cost-visibility logging (testing phase) reads this usage data -- it's
  // observability, not a limiter, but it only works if these fields are
  // actually parsed out of the stream instead of silently staying null.
  it("captures input/output token usage from message_start and message_delta events", async () => {
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"message_start","message":{"usage":{"input_tokens":42,"output_tokens":1}}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode('data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n')
        );
        controller.enqueue(new TextEncoder().encode('data: {"type":"message_delta","usage":{"output_tokens":7}}\n'));
        controller.close();
      },
    });

    await expect(readAnthropicReplyAsText(upstreamBody, 50)).resolves.toEqual({
      text: "Hi",
      usage: { inputTokens: 42, outputTokens: 7 },
      diagnostics: {
        stopReason: null,
        contentBlockTypesSeen: [],
        textDeltaCount: 1,
        hadStreamError: false,
        streamErrorType: null,
      },
    });
  });

  // Regression coverage for the "(No response)" investigation: the sibling bug
  // in news_sentiment_llm.py was a content-block PARSING crash (indexing
  // content[0] positionally). This route's SSE extractor never indexed by
  // position in the first place -- it filters purely on delta.type -- so a
  // thinking block (or any other non-text block) appearing before the text
  // block must be silently skipped, not crash and not corrupt the result.
  it("skips a thinking block that arrives before the text block, extracting only the text", async () => {
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"reasoning..."}}\n'
          )
        );
        controller.enqueue(new TextEncoder().encode('data: {"type":"content_block_stop","index":0}\n'));
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"text"}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Real answer"}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode('data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n')
        );
        controller.close();
      },
    });

    const result = await readAnthropicReplyAsText(upstreamBody, 50);
    expect(result.text).toBe("Real answer");
    expect(result.diagnostics.contentBlockTypesSeen).toEqual(["thinking", "text"]);
    expect(result.diagnostics.stopReason).toBe("end_turn");
  });

  // A tool_use block ahead of the text block must be skipped the same way --
  // its deltas are input_json_delta, never text_delta.
  it("skips a tool_use block that arrives before the text block", async () => {
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","name":"lookup"}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{}"}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_start","index":1,"content_block":{"type":"text"}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Answer after tool use"}}\n'
          )
        );
        controller.close();
      },
    });

    const result = await readAnthropicReplyAsText(upstreamBody, 50);
    expect(result.text).toBe("Answer after tool use");
    expect(result.diagnostics.contentBlockTypesSeen).toEqual(["tool_use", "text"]);
  });

  // Multiple separate text blocks must concatenate in order, not just take
  // the first one -- matching the fix applied to news_sentiment_llm.py.
  it("concatenates multiple text blocks in order rather than taking only the first", async () => {
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Part one. "}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"Part two."}}\n'
          )
        );
        controller.close();
      },
    });

    const result = await readAnthropicReplyAsText(upstreamBody, 50);
    expect(result.text).toBe("Part one. Part two.");
    expect(result.diagnostics.textDeltaCount).toBe(2);
  });

  // The exact failure mode this investigation was launched to find: a
  // thinking block consumes the reply's token budget before any text_delta
  // ever arrives, and the stream ends with stop_reason "max_tokens" and zero
  // text. Previously stop_reason was never captured at all, so this was
  // indistinguishable from any other empty stream.
  it("captures stop_reason 'max_tokens' with zero text when thinking exhausts the budget", async () => {
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"long chain of reasoning that never finishes..."}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode('data: {"type":"message_delta","delta":{"stop_reason":"max_tokens"}}\n')
        );
        controller.close();
      },
    });

    const result = await readAnthropicReplyAsText(upstreamBody, 50);
    expect(result.text).toBe("");
    expect(result.diagnostics.textDeltaCount).toBe(0);
    expect(result.diagnostics.stopReason).toBe("max_tokens");
    expect(result.diagnostics.contentBlockTypesSeen).toEqual(["thinking"]);
  });

  // An in-stream `error` event (e.g. overloaded_error mid-response) was
  // previously silently dropped by the extractor's if/else-if chain -- it
  // must now be captured, not just ignored.
  it("captures an in-stream error event instead of silently dropping it", async () => {
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"partial"}}\n'
          )
        );
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}\n'
          )
        );
        controller.close();
      },
    });

    const result = await readAnthropicReplyAsText(upstreamBody, 50);
    expect(result.diagnostics.hadStreamError).toBe(true);
    expect(result.diagnostics.streamErrorType).toBe("overloaded_error");
    // Partial text that arrived before the error is still preserved, exactly
    // as the existing "keeps already-streamed text visible" ChatBot behavior
    // expects -- an in-stream error must not retroactively erase real output.
    expect(result.text).toBe("partial");
  });

  // A stream that closes with no message_delta/message_stop at all (an
  // abrupt disconnect) must be distinguishable in principle from one that
  // completed normally with nothing to say -- both currently yield
  // stopReason: null, which is itself the honest signal ("we don't know
  // why") rather than a fabricated "end_turn".
  it("reports stopReason null (not a guessed value) when the stream closes with no message_delta at all", async () => {
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}\n'
          )
        );
        // Closes abruptly -- no content_block_delta, no message_delta, no [DONE].
        controller.close();
      },
    });

    const result = await readAnthropicReplyAsText(upstreamBody, 50);
    expect(result.text).toBe("");
    expect(result.diagnostics.stopReason).toBeNull();
    expect(result.diagnostics.textDeltaCount).toBe(0);
  });
});

describe("POST /api/chat", () => {
  it("returns 503 and never calls fetch when ANTHROPIC_API_KEY is missing", async () => {
    delete process.env.ANTHROPIC_API_KEY;
    const mockFetch = jest.fn();
    global.fetch = mockFetch as unknown as typeof fetch;

    const response = await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));

    expect(response.status).toBe(503);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("returns 400 for an empty message", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    const response = await POST(jsonRequest({ message: "   ", strategyContext: CONTEXT, history: [] }));
    expect(response.status).toBe(400);
  });

  it("returns 400 for a missing/malformed strategyContext", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    const response = await POST(jsonRequest({ message: "hi", strategyContext: {}, history: [] }));
    expect(response.status).toBe(400);
  });

  it("returns 400 for an unparseable JSON body", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    const badRequest = new Request("http://localhost/api/chat", { method: "POST", body: "not json" });
    const response = await POST(badRequest);
    expect(response.status).toBe(400);
  });

  it("calls the Anthropic API with the correct URL, headers, and model on success", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    const mockFetch = jest.fn().mockResolvedValue(sseResponse([]));
    global.fetch = mockFetch as unknown as typeof fetch;

    const response = await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toContain("text/plain");
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe("https://api.anthropic.com/v1/messages");
    expect(init.headers["x-api-key"]).toBe("test-key");
    expect(init.headers["anthropic-version"]).toBe("2023-06-01");
    const parsedBody = JSON.parse(init.body);
    expect(parsedBody.model).toBe("claude-sonnet-5");
    expect(parsedBody.max_tokens).toBe(1024);
    expect(parsedBody.stream).toBe(true);
    expect(parsedBody.messages[parsedBody.messages.length - 1]).toEqual({ role: "user", content: "hi" });
  });

  it("streams the extracted assistant text back to the client", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    const mockFetch = jest.fn().mockResolvedValue(
      sseResponse([
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi "}}\n',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"there"}}\n',
      ])
    );
    global.fetch = mockFetch as unknown as typeof fetch;

    const response = await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));
    const text = await response.text();

    expect(text).toBe("Hi there");
  });

  // Cost-visibility logging (testing phase, not a limiter): confirms real
  // per-message token usage actually lands in Vercel Runtime Logs so it can
  // be spot-checked, now that the hard message-count cap is gone.
  it("logs input/output token usage on a successful response", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    global.fetch = jest.fn().mockResolvedValue(
      sseResponse([
        'data: {"type":"message_start","message":{"usage":{"input_tokens":123,"output_tokens":1}}}\n',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n',
        'data: {"type":"message_delta","usage":{"output_tokens":45}}\n',
      ])
    ) as unknown as typeof fetch;
    const consoleLogSpy = jest.spyOn(console, "log").mockImplementation(() => {});

    await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));

    expect(consoleLogSpy).toHaveBeenCalledWith(expect.stringContaining("input_tokens=123"));
    expect(consoleLogSpy).toHaveBeenCalledWith(expect.stringContaining("output_tokens=45"));
    consoleLogSpy.mockRestore();
  });

  it("returns 502 when the upstream response is not ok", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    global.fetch = jest.fn().mockResolvedValue(new Response("nope", { status: 401 })) as unknown as typeof fetch;

    const response = await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));
    expect(response.status).toBe(502);
  });

  it("logs the upstream status and body when the upstream response is not ok, so the real cause (e.g. an invalid model id) is visible server-side instead of only the generic client fallback", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    const errorBody = JSON.stringify({ type: "error", error: { type: "not_found_error", message: "model: claude-bogus-model" } });
    global.fetch = jest.fn().mockResolvedValue(new Response(errorBody, { status: 404 })) as unknown as typeof fetch;
    const consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});

    await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));

    expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining("404"));
    expect(consoleErrorSpy).toHaveBeenCalledWith(expect.stringContaining("not_found_error"));
    consoleErrorSpy.mockRestore();
  });

  it("returns 502 when the upstream fetch throws (network failure / timeout)", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    global.fetch = jest.fn().mockRejectedValue(new Error("network down")) as unknown as typeof fetch;

    const response = await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));
    expect(response.status).toBe(502);
  });

  it("never leaks a technical error message in the response body", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    global.fetch = jest.fn().mockRejectedValue(new Error("ECONNRESET super technical detail")) as unknown as typeof fetch;

    const response = await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));
    const body = await response.text();
    expect(body).not.toContain("ECONNRESET");
  });

  // Regression test for a real production incident: two of four /api/chat
  // requests came back 502 with "upstream request threw: DOMException
  // [AbortError]: This operation was aborted". Root cause was that
  // UPSTREAM_TIMEOUT_MS's AbortController was only ever cleared in the
  // shared `finally` (i.e. after the ENTIRE request finished), so it stayed
  // armed through the whole body read and could abort a stream that had
  // already connected and was still legitimately in progress (e.g. a long
  // "thinking" gap before the first text_delta). This proves headers arriving
  // is enough to retire that timer -- a body that pauses past
  // UPSTREAM_TIMEOUT_MS, but resumes within STREAM_IDLE_TIMEOUT_MS, must
  // still succeed.
  it("does not abort a stream that pauses past UPSTREAM_TIMEOUT_MS after headers have already arrived, as long as it resumes within STREAM_IDLE_TIMEOUT_MS", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    jest.useFakeTimers();

    let streamController: ReadableStreamDefaultController<Uint8Array>;
    const upstreamBody = new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
      },
    });
    global.fetch = jest
      .fn()
      .mockResolvedValue(
        new Response(upstreamBody, { status: 200, headers: { "Content-Type": "text/event-stream" } })
      ) as unknown as typeof fetch;

    const responsePromise = POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));

    // Simulate a "thinking" pause longer than UPSTREAM_TIMEOUT_MS but shorter
    // than STREAM_IDLE_TIMEOUT_MS, with no body bytes delivered yet.
    expect(UPSTREAM_TIMEOUT_MS).toBeLessThan(STREAM_IDLE_TIMEOUT_MS);
    await jest.advanceTimersByTimeAsync(UPSTREAM_TIMEOUT_MS + 1_000);

    streamController!.enqueue(
      new TextEncoder().encode('data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"answer"}}\n')
    );
    streamController!.close();

    const response = await responsePromise;
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("answer");

    jest.useRealTimers();
  });

  // Root-cause regression coverage for the "(No response)" investigation: a
  // stream that completes successfully (upstream.ok) but produces zero text
  // must NOT come back as a bare 200 + empty body -- previously this was the
  // one case the client could never explain, because nothing had gone wrong
  // at the HTTP layer. It must surface stop_reason instead.
  it("returns 502 with stop_reason surfaced when the stream completes with zero text (e.g. max_tokens exhausted by thinking)", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    global.fetch = jest.fn().mockResolvedValue(
      sseResponse([
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking"}}\n',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"..."}}\n',
        'data: {"type":"message_delta","delta":{"stop_reason":"max_tokens"}}\n',
      ])
    ) as unknown as typeof fetch;

    const response = await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));
    expect(response.status).toBe(502);
    const body = await response.json();
    expect(body.error).toContain("max_tokens");
  });

  it("returns 502 mentioning the in-stream error type when the stream errors before any text arrives", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    global.fetch = jest.fn().mockResolvedValue(
      sseResponse(['data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}\n'])
    ) as unknown as typeof fetch;

    const response = await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));
    expect(response.status).toBe(502);
    const body = await response.json();
    expect(body.error).toContain("overloaded_error");
  });

  it("still returns 200 with the text when some text arrived despite a later in-stream error", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    global.fetch = jest.fn().mockResolvedValue(
      sseResponse([
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"partial answer"}}\n',
        'data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}\n',
      ])
    ) as unknown as typeof fetch;

    const response = await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("partial answer");
  });

  it("logs a structured [chat-diag] line with stop_reason, content block types, and text length, never the API key or message content", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key-should-never-appear";
    global.fetch = jest.fn().mockResolvedValue(
      sseResponse([
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}\n',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hello there"}}\n',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n',
      ])
    ) as unknown as typeof fetch;
    const consoleLogSpy = jest.spyOn(console, "log").mockImplementation(() => {});

    await POST(jsonRequest({ message: "a secret user question", strategyContext: CONTEXT, history: [] }));

    const diagCall = consoleLogSpy.mock.calls.find((call) => typeof call[0] === "string" && call[0].includes("[chat-diag]"));
    expect(diagCall).toBeDefined();
    const logged = JSON.parse(diagCall![0] as string);
    expect(logged.stopReason).toBe("end_turn");
    expect(logged.contentBlockTypesSeen).toEqual(["text"]);
    expect(logged.textByteLength).toBe("hello there".length);
    expect(logged.hadStreamError).toBe(false);
    // Never the key, never the raw message/reply content -- lengths/flags only.
    const allLoggedText = consoleLogSpy.mock.calls.map((call) => String(call[0])).join("\n");
    expect(allLoggedText).not.toContain("test-key-should-never-appear");
    expect(allLoggedText).not.toContain("a secret user question");
    expect(allLoggedText).not.toContain("hello there");
    consoleLogSpy.mockRestore();
  });
});

describe("Next.js Route Handler export contract", () => {
  // Next.js's build-time route-type validation rejects ANY named export from
  // app/**/route.ts other than HTTP method handlers and a small whitelisted
  // set of route-segment config constants -- exporting a helper function
  // (e.g. for direct unit testing) silently breaks the production build.
  // This regression test would have caught exactly that: a prior version of
  // this file exported sanitizeMessage/buildSystemPrompt/etc. directly and
  // shipped a working test suite while the real Vercel build failed.
  const ALLOWED_ROUTE_EXPORTS = new Set([
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "HEAD",
    "OPTIONS",
    "runtime",
    "dynamic",
    "dynamicParams",
    "revalidate",
    "fetchCache",
    "preferredRegion",
    "maxDuration",
  ]);

  it("app/api/chat/route.ts exports only POST and runtime -- nothing else", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "app", "api", "chat", "route.ts"), "utf-8");
    const exportNames = Array.from(
      source.matchAll(/^export\s+(?:async\s+function|function|const)\s+([A-Za-z_$][\w$]*)/gm)
    ).map((m) => m[1]);

    expect(exportNames.length).toBeGreaterThan(0);
    for (const name of exportNames) {
      expect(ALLOWED_ROUTE_EXPORTS.has(name)).toBe(true);
    }
  });
});

describe("API key server-only boundary", () => {
  it("route.ts is not a client component (no 'use client' directive)", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "app", "api", "chat", "route.ts"), "utf-8");
    expect(source).not.toContain('"use client"');
  });

  it("ChatBot.tsx never references ANTHROPIC_API_KEY or reads process.env directly", () => {
    const source = fs.readFileSync(path.join(__dirname, "..", "components", "ChatBot.tsx"), "utf-8");
    expect(source).not.toContain("ANTHROPIC_API_KEY");
    expect(source).not.toContain("process.env");
  });

  it("only route.ts references ANTHROPIC_API_KEY anywhere under app/ or components/", () => {
    const roots = ["app", "components"].map((dir) => path.join(__dirname, "..", dir));
    const offenders: string[] = [];

    function walk(dir: string) {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(full);
        } else if (/\.(ts|tsx)$/.test(entry.name)) {
          const contents = fs.readFileSync(full, "utf-8");
          if (contents.includes("ANTHROPIC_API_KEY") && !full.endsWith(path.join("api", "chat", "route.ts"))) {
            offenders.push(full);
          }
        }
      }
    }

    for (const root of roots) {
      walk(root);
    }
    expect(offenders).toEqual([]);
  });
});
