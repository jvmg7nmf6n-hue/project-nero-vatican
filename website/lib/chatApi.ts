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
// Raised from 300 after production logs showed stop_reason "max_tokens" with
// zero text_delta output on real requests (a "thinking" content block opened
// before the budget ran out -- see readAnthropicReplyAsText's own tests).
// 300 was thin even for text alone: the system prompt's "under 150 words"
// cap runs ~250-300 tokens at English density, and non-Latin scripts (Urdu,
// Arabic, Hindi, ...) that this bot explicitly promises to answer in commonly
// tokenize at 2-3x that for equivalent content. 1024 is sized off that
// structural floor, not off per-request outputTokens numbers -- those weren't
// available for the failing requests at the time of this change. Revisit with
// real inputTokens/outputTokens once logged.
export const MAX_TOKENS = 1024;
export const MAX_INPUT_LENGTH = 500;
// Independent of MAX_MESSAGES_PER_SESSION (chatSession.ts) -- this bounds the
// context sent in any SINGLE request as a conversation gets long, which is a
// real token-growth/context-window concern regardless of how many total
// messages a session sends. 12 messages = 6 exchanges.
export const HISTORY_LIMIT = 12;
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
export interface SseUsage {
  inputTokens: number | null;
  outputTokens: number | null;
}

// Diagnostics for the "(No response)" investigation (see route.ts's own
// comments): previously NONE of these were captured, which made an empty
// reply indistinguishable -- even in the server logs -- from a genuinely
// broken stream. contentBlockTypesSeen is diagnostic only, never used to
// select which block to read from (the text_delta filter below is already
// index-independent by construction: it matches on delta.type wherever in
// the stream it appears, not on content_block position or count).
export interface SseDiagnostics {
  stopReason: string | null;
  contentBlockTypesSeen: string[];
  textDeltaCount: number;
  hadStreamError: boolean;
  streamErrorType: string | null;
}

export function createSseTextExtractor() {
  let buffer = "";
  let inputTokens: number | null = null;
  let outputTokens: number | null = null;
  let stopReason: string | null = null;
  const contentBlockTypesSeen: string[] = [];
  let textDeltaCount = 0;
  let hadStreamError = false;
  let streamErrorType: string | null = null;
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
            textDeltaCount += 1;
          } else if (event?.type === "content_block_start" && typeof event?.content_block?.type === "string") {
            contentBlockTypesSeen.push(event.content_block.type);
          } else if (event?.type === "message_start" && typeof event?.message?.usage?.input_tokens === "number") {
            // Cost-visibility only (testing phase) -- not used for any limit.
            inputTokens = event.message.usage.input_tokens;
          } else if (event?.type === "message_delta") {
            if (typeof event?.usage?.output_tokens === "number") {
              outputTokens = event.usage.output_tokens;
            }
            // Previously never read at all -- this is the one field that lets
            // an honestly-empty reply ("the model chose to stop, see why")
            // be told apart from a broken stream.
            if (typeof event?.delta?.stop_reason === "string") {
              stopReason = event.delta.stop_reason;
            }
          } else if (event?.type === "error") {
            // Previously silently dropped by this if/else-if chain -- an
            // in-stream error (e.g. an overloaded_error mid-response) left no
            // trace at all, so it looked identical to a genuinely empty reply.
            hadStreamError = true;
            streamErrorType = typeof event?.error?.type === "string" ? event.error.type : "unknown";
          }
        } catch {
          // Malformed or unexpected event shape -- skip it rather than crash
          // an otherwise-working stream over one bad event.
        }
      }
      return output;
    },
    getUsage(): SseUsage {
      return { inputTokens, outputTokens };
    },
    getDiagnostics(): SseDiagnostics {
      return { stopReason, contentBlockTypesSeen: [...contentBlockTypesSeen], textDeltaCount, hadStreamError, streamErrorType };
    },
  };
}

// STREAM_IDLE_TIMEOUT_MS bounds each individual read from the upstream body,
// not just the initial connection. UPSTREAM_TIMEOUT_MS (via the route's
// AbortController) only covers the initial fetch() -- once headers arrive
// that abort timer is cleared, so a stalled upstream body had no
// application-level cutoff at all and would hang until Vercel's platform
// maxDuration force-killed the whole function. Confirmed in production via
// Runtime Logs: the request had already connected to api.anthropic.com and
// pulled real bytes, then stalled with no further progress.
export const STREAM_IDLE_TIMEOUT_MS = 15_000;

// A prior version of this function returned a passthrough ReadableStream so
// the reply could render incrementally. That added a second, independent
// place a hang could hide (a custom ReadableStream erroring doesn't reliably
// finalize the underlying HTTP response under Next.js's Route Handler
// streaming, observed in production: the app-level idle timeout fired but
// the function still ran until Vercel's own maxDuration killed it). Given
// MAX_TOKENS caps the whole reply at a few KB, the token-by-token streaming
// UI touch isn't worth that fragility -- this reads the upstream SSE body to
// completion (still bounded per-chunk by the same idle timeout) and returns
// one plain string, so the route's own await/return is what ends the
// function, with no separate stream-lifecycle path to get stuck in.
export interface AnthropicReply {
  text: string;
  usage: SseUsage;
  diagnostics: SseDiagnostics;
}

export async function readAnthropicReplyAsText(
  upstreamBody: ReadableStream<Uint8Array>,
  idleTimeoutMs: number = STREAM_IDLE_TIMEOUT_MS
): Promise<AnthropicReply> {
  const decoder = new TextDecoder();
  const extractor = createSseTextExtractor();
  const reader = upstreamBody.getReader();
  let fullText = "";

  try {
    for (;;) {
      let timeoutId: ReturnType<typeof setTimeout> | undefined;
      const idle = new Promise<"idle">((resolve) => {
        timeoutId = setTimeout(() => resolve("idle"), idleTimeoutMs);
      });

      const result = await Promise.race([reader.read(), idle]);
      clearTimeout(timeoutId);

      if (result === "idle") {
        throw new Error(`Upstream stream idle for over ${idleTimeoutMs}ms`);
      }

      const { done, value } = result;
      if (done) {
        return { text: fullText, usage: extractor.getUsage(), diagnostics: extractor.getDiagnostics() };
      }
      fullText += extractor.push(decoder.decode(value, { stream: true }));
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}
