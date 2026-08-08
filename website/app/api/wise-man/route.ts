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

/** True only when a real, cross-request, cross-instance atomic store is
 * configured. GATE B follow-up finding (2026-08-08): the in-memory fallback
 * is NOT merely "doesn't share state across serverless instances" -- it is
 * a BRAND NEW, always-empty Map created fresh on every single request (see
 * loadStore() below, called at the top of every POST), so the rate limiter
 * and spend cap are a complete no-op, not a degraded one, whenever this is
 * false. See the fail-closed check in POST() immediately below. */
function hasRealCounterStoreConfigured(env: Partial<Record<string, string>> = process.env): boolean {
  // Matches @upstash/redis's own Redis.fromEnv() fallback exactly (verified
  // against the installed package, node_modules/@upstash/redis/nodejs.js:
  // 5708-5729) -- it accepts UPSTASH_REDIS_REST_URL/_TOKEN OR the legacy
  // KV_REST_API_URL/_TOKEN names (what the deprecated @vercel/kv package
  // used to set). Checking only the first pair would fail closed even on a
  // deployment where Redis.fromEnv() would actually succeed via the legacy
  // names -- a false negative, not just an overly strict default.
  const url = env.UPSTASH_REDIS_REST_URL || env.KV_REST_API_URL;
  const token = env.UPSTASH_REDIS_REST_TOKEN || env.KV_REST_API_TOKEN;
  return Boolean(url && token);
}

/** Upstash Redis when configured (production); falls back to an in-memory
 * store otherwise -- but POST() below refuses to reach this fallback path
 * at all while the feature flag is on, per the fail-closed decision above. */
async function loadStore(): Promise<AtomicCounterStore> {
  if (hasRealCounterStoreConfigured()) {
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

  // FAIL CLOSED (GATE B follow-up, 2026-08-08): the feature flag being on
  // with no real Redis configured used to mean every request silently got
  // its own fresh, empty, never-shared counter -- the spend cap and rate
  // limiter became a complete no-op with nothing in the response to signal
  // it. That is not an acceptable failure mode on the exact mechanism that
  // protects the owner's API spend, so this refuses to serve ANY Wise Man
  // request in that state -- consistent with the fail-closed posture
  // already used everywhere else in this build (the guardrail, the rate
  // limiter, and the budget check all fail closed on their own errors; this
  // extends the same posture to a misconfiguration, not just a runtime
  // error). The log line is deliberately loud and distinctly tagged so it
  // is not mistaken for routine per-request logging.
  if (isWiseManEnabled() && !hasRealCounterStoreConfigured()) {
    console.error(
      "[wise-man] CRITICAL: WISE_MAN_ENABLED is on but no real counter store is configured " +
        "(UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN missing) -- refusing to serve Wise Man " +
        "requests. The spend cap and rate limiter would otherwise be a silent no-op. " +
        "See docs/investigations/wise_man_implementation_report.md for the Upstash Redis linking steps.",
    );
    return jsonResponse(503, { error: formatWiseManError("storage_not_configured") });
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
