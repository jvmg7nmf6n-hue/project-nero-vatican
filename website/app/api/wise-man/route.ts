import { randomUUID } from "node:crypto";
import {
  handleWiseManRequest,
  type WiseManDeps,
  type WiseManRequestInput,
} from "@/lib/wiseMan/handleRequest";
import { createInMemoryCounterStore, createUpstashRedisCounterStore, loadBudgetConfig, type AtomicCounterStore } from "@/lib/wiseMan/budget";
import { loadRateLimitConfig } from "@/lib/wiseMan/rateLimit";
import { isWiseManEnabled, loadAllowedOrigins } from "@/lib/wiseMan/config";
import { SESSION_COOKIE_NAME, SESSION_TTL_MS } from "@/lib/wiseMan/session";
import { formatWiseManError } from "@/lib/wiseMan/errors";

// SERVER-ONLY, matching app/api/chat/route.ts's own convention: no
// "use client", process.env.ANTHROPIC_API_KEY read here only. Everything
// testable lives in @/lib/wiseMan/*; this file is a thin wrapper that
// parses the Request, calls handleWiseManRequest(), and shapes the
// Response -- same split the existing chat route already established.
export const runtime = "nodejs";
export const maxDuration = 30;

function jsonResponse(status: number, body: Record<string, unknown>, setCookie?: string): Response {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (setCookie) headers["Set-Cookie"] = setCookie;
  return new Response(JSON.stringify(body), { status, headers });
}

function parseCookie(cookieHeader: string | null, name: string): string | null {
  if (!cookieHeader) return null;
  for (const part of cookieHeader.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return null;
}

function clientIp(request: Request): string {
  // Vercel populates x-forwarded-for; fall back to a constant so rate
  // limiting still groups same-unknown-origin traffic together rather than
  // silently bypassing the per-IP check.
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0].trim();
  return "unknown";
}

/** Upstash Redis when configured (production); falls back to an in-memory
 * store otherwise. The in-memory fallback does NOT share state across
 * serverless invocations -- rate limits and the spend cap will not hold in
 * production without a real Redis integration linked (GATE A finding 1.4's
 * own equivalent gap for Eve's ledger). Documented, not silently assumed
 * working. */
async function loadStore(): Promise<AtomicCounterStore> {
  if (process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN) {
    return createUpstashRedisCounterStore();
  }
  return createInMemoryCounterStore();
}

export async function POST(request: Request): Promise<Response> {
  const requestId = randomUUID();
  const apiKey = process.env.ANTHROPIC_API_KEY;
  const sessionSecret = process.env.WISE_MAN_SESSION_SECRET;
  if (!apiKey || !sessionSecret) {
    console.log(JSON.stringify({ tag: "[wise-man]", requestId, outcome: "not_configured" }));
    return jsonResponse(503, { error: formatWiseManError("feature_disabled") });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return jsonResponse(400, { error: formatWiseManError("invalid_request") });
  }
  if (typeof body !== "object" || body === null) {
    return jsonResponse(400, { error: formatWiseManError("invalid_request") });
  }
  const { message, pageContext, attachments, history } = body as Record<string, unknown>;

  const store = await loadStore();
  const deps: WiseManDeps = {
    apiKey,
    sessionSecret,
    store,
    budgetConfig: loadBudgetConfig(),
    rateLimitConfig: loadRateLimitConfig(),
    allowedOrigins: loadAllowedOrigins(),
    enabled: isWiseManEnabled(),
  };

  const input: WiseManRequestInput = {
    message,
    pageContext,
    attachments,
    history,
    sessionToken: parseCookie(request.headers.get("cookie"), SESSION_COOKIE_NAME),
    ip: clientIp(request),
    origin: request.headers.get("origin"),
  };

  let result;
  try {
    result = await handleWiseManRequest(input, deps);
  } catch (err) {
    // Fail closed at the outermost layer too (Sec 8.8): no unhandled
    // exception ever produces a raw 500 body with a stack trace.
    console.error("[wise-man] unhandled error:", err);
    console.log(JSON.stringify({ tag: "[wise-man]", requestId, outcome: "threw" }));
    return jsonResponse(502, { error: formatWiseManError("upstream_error") });
  }

  const setCookie = result.newSessionToken
    ? `${SESSION_COOKIE_NAME}=${result.newSessionToken}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${Math.floor(SESSION_TTL_MS / 1000)}`
    : undefined;

  console.log(
    JSON.stringify({
      tag: "[wise-man]",
      requestId,
      httpStatus: result.httpStatus,
      outcome: result.errorCode ?? "ok",
    }),
  );

  if (result.errorCode) {
    return jsonResponse(result.httpStatus, { error: formatWiseManError(result.errorCode) }, setCookie);
  }
  return jsonResponse(200, { reply: result.reply }, setCookie);
}
