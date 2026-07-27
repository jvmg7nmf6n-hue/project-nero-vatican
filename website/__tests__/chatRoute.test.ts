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
import { POST } from "@/app/api/chat/route";
import {
  buildSystemPrompt,
  createSseTextExtractor,
  isStrategyChatContext,
  sanitizeHistory,
  sanitizeMessage,
} from "@/lib/chatApi";
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

  it("keeps only the last 6 entries (3 exchanges)", () => {
    const long = Array.from({ length: 10 }, (_, i) => ({ role: "user" as const, content: `msg${i}` }));
    expect(sanitizeHistory(long)).toHaveLength(6);
    expect(sanitizeHistory(long)[0]).toEqual({ role: "user", content: "msg4" });
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
    expect(parsedBody.model).toBe("claude-sonnet-4-6");
    expect(parsedBody.max_tokens).toBe(300);
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

  it("returns 502 when the upstream response is not ok", async () => {
    process.env.ANTHROPIC_API_KEY = "test-key";
    global.fetch = jest.fn().mockResolvedValue(new Response("nope", { status: 401 })) as unknown as typeof fetch;

    const response = await POST(jsonRequest({ message: "hi", strategyContext: CONTEXT, history: [] }));
    expect(response.status).toBe(502);
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
