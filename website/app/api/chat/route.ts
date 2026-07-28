import { randomUUID } from "node:crypto";
import {
  ANTHROPIC_API_URL,
  ANTHROPIC_VERSION,
  buildSystemPrompt,
  isStrategyChatContext,
  MAX_TOKENS,
  MODEL,
  readAnthropicReplyAsText,
  sanitizeHistory,
  sanitizeMessage,
  UPSTREAM_TIMEOUT_MS,
} from "@/lib/chatApi";

// SERVER-ONLY: this file never has "use client" and never runs in the browser
// bundle -- process.env.ANTHROPIC_API_KEY is read here and nowhere else in the
// codebase. The ChatBot client component never sees the key; it only learns
// whether live chat is available via a boolean the strategy page computes
// server-side (see app/strategy/[id]/page.tsx's `hasLiveChat`).
//
// A Next.js Route Handler file may only export HTTP method handlers (GET,
// POST, ...) and a small whitelisted set of route-segment config constants
// (runtime, dynamic, ...) -- Next's build-time route-type validation rejects
// any other named export. All testable helper logic therefore lives in
// @/lib/chatApi, imported here; this file exports only `runtime` and `POST`.
export const runtime = "nodejs";
// Hard backstop: without this, an unresponsive upstream connection can hang
// the function for Vercel's full platform default (300s) even if our own
// AbortController-based UPSTREAM_TIMEOUT_MS fails to fire (observed in
// production runtime logs as FUNCTION_INVOCATION_TIMEOUT). Bounds worst-case
// user-facing latency to a fast failure instead of a multi-minute hang.
export const maxDuration = 30;

function jsonError(status: number, error: string): Response {
  return new Response(JSON.stringify({ error }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Structured, one-line-per-request diagnostic log, added while investigating
// the "(No response)" ChatBot bug -- there was previously NO structured
// logging on this route at all beyond two ad-hoc console.error/console.log
// calls, neither of which captured stop_reason, content-block types, or
// whether an in-stream error event ever arrived. Never logs the API key or
// message/reply CONTENT -- only lengths and classification fields.
function logChatDiagnostic(fields: Record<string, unknown>): void {
  console.log(JSON.stringify({ tag: "[chat-diag]", ...fields }));
}

export async function POST(request: Request): Promise<Response> {
  const requestId = randomUUID();
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    logChatDiagnostic({ requestId, model: MODEL, outcome: "no_api_key" });
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

    // Headers have arrived -- clear the connection-phase abort timer now, not
    // in the shared `finally` below. Previously this timer was only ever
    // cleared after the ENTIRE request (including the full body read) had
    // finished, so UPSTREAM_TIMEOUT_MS's AbortController stayed armed through
    // readAnthropicReplyAsText and could fire mid-stream on a slow-but-alive
    // response (confirmed in production: 502s logged as "upstream request
    // threw: DOMException [AbortError]: This operation was aborted" on
    // requests that had already connected). STREAM_IDLE_TIMEOUT_MS's
    // per-chunk rolling window is what's meant to govern the body-read phase.
    clearTimeout(timeoutId);

    if (!upstream.ok || !upstream.body) {
      const bodyText = upstream.body ? await upstream.text().catch(() => "<unreadable body>") : "<no body>";
      console.error(`[chat] upstream request failed: status=${upstream.status} body=${bodyText}`);
      logChatDiagnostic({
        requestId,
        model: MODEL,
        messageLength: sanitizedMessage.length,
        httpStatus: upstream.status,
        outcome: "upstream_not_ok",
      });
      return jsonError(502, "Upstream AI request failed.");
    }

    const { text: replyText, usage, diagnostics } = await readAnthropicReplyAsText(upstream.body);
    // Observability only (testing phase) -- not a limiter. Lets us spot-check
    // real per-message cost in Vercel Runtime Logs; see chatSession.ts for
    // the pre-launch TODO on an actual enforced cap.
    console.log(`[chat] usage: input_tokens=${usage.inputTokens ?? "unknown"} output_tokens=${usage.outputTokens ?? "unknown"}`);
    logChatDiagnostic({
      requestId,
      model: MODEL,
      messageLength: sanitizedMessage.length,
      httpStatus: upstream.status,
      stopReason: diagnostics.stopReason,
      contentBlockTypesSeen: diagnostics.contentBlockTypesSeen,
      textDeltaCount: diagnostics.textDeltaCount,
      textByteLength: Buffer.byteLength(replyText, "utf8"),
      hadStreamError: diagnostics.hadStreamError,
      streamErrorType: diagnostics.streamErrorType,
      inputTokens: usage.inputTokens ?? "unknown",
      outputTokens: usage.outputTokens ?? "unknown",
      outcome: replyText.length === 0 ? "empty_text" : "ok",
    });

    if (replyText.length === 0) {
      // The stream completed with no exception (usually a 200 from
      // Anthropic), but produced zero text_delta events. Previously this
      // silently returned a bare 200 + empty body, which the client could
      // only render as the same uninformative "(No response)" it used for
      // every other failure. stop_reason (and whether an in-stream error
      // event arrived) is the one piece of information that lets the client
      // tell "the model chose to stop without answering" apart from
      // "truncated by max_tokens" apart from "upstream reported an error
      // mid-response" -- see this route's own investigation notes.
      const reason = diagnostics.hadStreamError
        ? `an upstream error occurred mid-response (${diagnostics.streamErrorType ?? "unknown"})`
        : `the model returned no text (stop_reason: ${diagnostics.stopReason ?? "unknown"})`;
      return jsonError(502, `No response was generated -- ${reason}.`);
    }

    return new Response(replyText, {
      status: 200,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  } catch (err) {
    // Covers network failure and the 10s AbortController timeout alike --
    // the client always shows the same generic fallback message either way,
    // never a technical error (see ChatBot.tsx's GENERIC_ERROR constant).
    // The full error is still logged server-side so Vercel Runtime Logs show
    // the real cause instead of only the generic client-facing fallback.
    console.error("[chat] upstream request threw:", err);
    logChatDiagnostic({
      requestId,
      model: MODEL,
      outcome: "threw",
      errorName: err instanceof Error ? err.name : "unknown",
    });
    return jsonError(502, "Upstream AI request failed.");
  } finally {
    clearTimeout(timeoutId);
  }
}
