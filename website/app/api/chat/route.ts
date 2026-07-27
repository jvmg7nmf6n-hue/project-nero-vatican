import {
  ANTHROPIC_API_URL,
  ANTHROPIC_VERSION,
  buildSystemPrompt,
  isStrategyChatContext,
  MAX_TOKENS,
  MODEL,
  sanitizeHistory,
  sanitizeMessage,
  streamAnthropicReplyAsText,
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

function jsonError(status: number, error: string): Response {
  return new Response(JSON.stringify({ error }), {
    status,
    headers: { "Content-Type": "application/json" },
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
      const bodyText = upstream.body ? await upstream.text().catch(() => "<unreadable body>") : "<no body>";
      console.error(`[chat] upstream request failed: status=${upstream.status} body=${bodyText}`);
      return jsonError(502, "Upstream AI request failed.");
    }

    return new Response(streamAnthropicReplyAsText(upstream.body), {
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
    return jsonError(502, "Upstream AI request failed.");
  } finally {
    clearTimeout(timeoutId);
  }
}
