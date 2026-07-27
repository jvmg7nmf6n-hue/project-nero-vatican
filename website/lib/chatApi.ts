import type { ChatMessage, StrategyChatContext } from "./types";

// Next.js Route Handlers (app/**/route.ts) may only export HTTP method
// handlers (GET, POST, ...) plus a small whitelisted set of route-segment
// config constants (runtime, dynamic, ...) -- ANY other named export fails
// Next's build-time route-type validation. These helpers were originally
// exported directly from app/api/chat/route.ts for unit testing, which broke
// the production build (the route module's shape no longer matched what
// Next.js requires). Moved here so route.ts can stay a clean handler-only
// module while these stay independently testable.

export const ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages";
export const ANTHROPIC_VERSION = "2023-06-01";
export const MODEL = "claude-sonnet-5";
export const MAX_TOKENS = 300;
export const MAX_INPUT_LENGTH = 500;
export const HISTORY_LIMIT = 6; // last 6 messages = 3 exchanges, per the task's own rule
export const UPSTREAM_TIMEOUT_MS = 10_000;

export function sanitizeMessage(raw: unknown): string | null {
  if (typeof raw !== "string") {
    return null;
  }
  const trimmed = raw.trim().slice(0, MAX_INPUT_LENGTH);
  return trimmed.length > 0 ? trimmed : null;
}

export function isStrategyChatContext(value: unknown): value is StrategyChatContext {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return (
    typeof v.strategy_name === "string" &&
    typeof v.asset === "string" &&
    typeof v.timeframe === "string" &&
    typeof v.mechanism === "string" &&
    typeof v.verification_note === "string" &&
    (typeof v.win_rate === "number" || v.win_rate === null) &&
    typeof v.current_signal === "string"
  );
}

// Malformed/unexpected entries are dropped rather than rejecting the whole
// request -- a client-side bug in history bookkeeping should degrade to "less
// context," never a hard failure of an otherwise-valid message.
export function sanitizeHistory(raw: unknown): ChatMessage[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  const valid = raw.filter(
    (item): item is ChatMessage =>
      typeof item === "object" &&
      item !== null &&
      (item as Record<string, unknown>).role !== undefined &&
      ((item as Record<string, unknown>).role === "user" || (item as Record<string, unknown>).role === "assistant") &&
      typeof (item as Record<string, unknown>).content === "string"
  );
  return valid.slice(-HISTORY_LIMIT);
}

export function buildSystemPrompt(context: StrategyChatContext): string {
  const winRateText = context.win_rate === null ? "not enough data yet" : `${(context.win_rate * 100).toFixed(0)}%`;

  return `You are Vatican Research Assistant — a friendly trading research guide for traders worldwide.

LANGUAGE RULE (highest priority):
Detect the language of the user's message and respond in THE SAME LANGUAGE.
- User writes Urdu → respond in Urdu
- User writes Arabic → respond in Arabic
- User writes Hindi → respond in Hindi
- User writes French → respond in French
- User writes Spanish → respond in Spanish
- User writes Roman Urdu → respond in Roman Urdu
- User writes Chinese → respond in Chinese
- User writes any language → respond in that language
- Mixed language → match their mix exactly
NEVER force English if user writes in another language.
Support all languages you know.

TONE:
- Friendly and simple — like explaining to a friend
- No jargon — if a technical term is needed, explain it immediately
- Short answers (under 150 words always)
- Encouraging, never dismissive
- Culturally aware for each region

YOU ARE EXPLAINING:
Strategy: ${context.strategy_name}
Asset: ${context.asset}
Timeframe: ${context.timeframe}
Mechanism: ${context.mechanism}
Verification: ${context.verification_note}
Win Rate: ${winRateText}
Current Signal: ${context.current_signal}

STRICT RULES (never break, in any language):
1. NEVER guarantee profits in any language
2. NEVER give personalized investment advice
3. ALWAYS remind the user Vatican is research and education, not financial advice
4. If asked how much to invest from their personal account → say 'consult a licensed financial advisor in your country'
5. If asked about illegal activities → decline politely
6. If unsure of a language → default to English

RESPONSE FORMAT:
- Direct answer first
- One disclaimer at end if discussing profits/losses (not every message)
- Never use bullet points in chat responses (conversational paragraphs only)`;
}

// Anthropic's streaming API sends Server-Sent Events; each `content_block_delta`
// event's `delta.text` is one chunk of the reply. This extractor buffers
// partial lines across chunk boundaries (a network read can split a single
// `data: {...}` line in two) and returns only the newly-decoded reply text
// for each push -- a pure, stateful-but-plain-string helper so it's directly
// unit-testable without a real ReadableStream.
export function createSseTextExtractor() {
  let buffer = "";
  return {
    push(chunkText: string): string {
      buffer += chunkText;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      let output = "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) {
          continue;
        }
        const jsonPart = trimmed.slice(5).trim();
        if (!jsonPart || jsonPart === "[DONE]") {
          continue;
        }
        try {
          const event = JSON.parse(jsonPart);
          if (
            event?.type === "content_block_delta" &&
            event?.delta?.type === "text_delta" &&
            typeof event.delta.text === "string"
          ) {
            output += event.delta.text;
          }
        } catch {
          // Malformed or unexpected event shape -- skip it rather than crash
          // an otherwise-working stream over one bad event.
        }
      }
      return output;
    },
  };
}

// STREAM_IDLE_TIMEOUT_MS bounds each individual read from the upstream body,
// not just the initial connection. UPSTREAM_TIMEOUT_MS (via the route's
// AbortController) only covers the initial fetch() -- once headers arrive
// and we start pulling the body here, that abort timer is already cleared,
// so a stalled upstream stream had no application-level cutoff at all and
// would hang until Vercel's platform maxDuration force-killed the whole
// function (observed in production: a request that hung the full 300s/30s
// while still pulling real bytes from api.anthropic.com).
export const STREAM_IDLE_TIMEOUT_MS = 15_000;

export function streamAnthropicReplyAsText(
  upstreamBody: ReadableStream<Uint8Array>,
  idleTimeoutMs: number = STREAM_IDLE_TIMEOUT_MS
): ReadableStream<Uint8Array> {
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const extractor = createSseTextExtractor();
  const reader = upstreamBody.getReader();

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      let timeoutId: ReturnType<typeof setTimeout> | undefined;
      const idle = new Promise<"idle">((resolve) => {
        timeoutId = setTimeout(() => resolve("idle"), idleTimeoutMs);
      });

      const result = await Promise.race([reader.read(), idle]);
      clearTimeout(timeoutId);

      if (result === "idle") {
        reader.cancel("idle timeout waiting for upstream data").catch(() => {});
        controller.error(new Error(`Upstream stream idle for over ${idleTimeoutMs}ms`));
        return;
      }

      const { done, value } = result;
      if (done) {
        controller.close();
        return;
      }
      const text = extractor.push(decoder.decode(value, { stream: true }));
      if (text) {
        controller.enqueue(encoder.encode(text));
      }
    },
    cancel(reason) {
      reader.cancel(reason);
    },
  });
}
