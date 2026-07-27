import type { ChatMessage, StrategyChatContext } from "@/lib/types";

// SERVER-ONLY: this file never has "use client" and never runs in the browser
// bundle -- process.env.ANTHROPIC_API_KEY is read here and nowhere else in the
// codebase. The ChatBot client component never sees the key; it only learns
// whether live chat is available via a boolean the strategy page computes
// server-side (see app/strategy/[id]/page.tsx's `hasLiveChat`).
export const runtime = "nodejs";

const ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION = "2023-06-01";
const MODEL = "claude-sonnet-4-6";
const MAX_TOKENS = 300;
const MAX_INPUT_LENGTH = 500;
const HISTORY_LIMIT = 6; // last 6 messages = 3 exchanges, per the task's own rule
const UPSTREAM_TIMEOUT_MS = 10_000;

function jsonError(status: number, error: string): Response {
  return new Response(JSON.stringify({ error }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

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

function streamAnthropicReplyAsText(upstreamBody: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const extractor = createSseTextExtractor();
  const reader = upstreamBody.getReader();

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { done, value } = await reader.read();
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

export async function POST(request: Request): Promise<Response> {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return jsonError(503, "AI chat is not configured.");
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonError(400, "Invalid request body.");
  }

  if (typeof body !== "object" || body === null) {
    return jsonError(400, "Invalid request body.");
  }
  const { message, strategyContext, history } = body as Record<string, unknown>;

  const sanitizedMessage = sanitizeMessage(message);
  if (!sanitizedMessage) {
    return jsonError(400, "message is required.");
  }
  if (!isStrategyChatContext(strategyContext)) {
    return jsonError(400, "strategyContext is required.");
  }
  const sanitizedHistory = sanitizeHistory(history);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);

  try {
    const upstream = await fetch(ANTHROPIC_API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": ANTHROPIC_VERSION,
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: MAX_TOKENS,
        system: buildSystemPrompt(strategyContext),
        messages: [...sanitizedHistory, { role: "user", content: sanitizedMessage }],
        stream: true,
      }),
      signal: controller.signal,
    });

    if (!upstream.ok || !upstream.body) {
      return jsonError(502, "Upstream AI request failed.");
    }

    return new Response(streamAnthropicReplyAsText(upstream.body), {
      status: 200,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  } catch {
    // Covers network failure and the 10s AbortController timeout alike --
    // the client always shows the same generic fallback message either way,
    // never a technical error (see ChatBot.tsx's GENERIC_ERROR constant).
    return jsonError(502, "Upstream AI request failed.");
  } finally {
    clearTimeout(timeoutId);
  }
}
