// Wise Man's rate limits (CC-1 directive v3, Sec 8.3). Per-session AND
// per-IP, with a lower limit for attachment-bearing requests. Per Sec 11.2:
// per-session is a convenience limit (trivially reset -- see session.ts);
// PER-IP IS THE REAL BACKSTOP.
//
// Unlike budget.ts's spend cap, a rate-limit increment is never released on
// rejection -- the whole point is that repeated attempts (including the
// over-limit ones) count against the window, otherwise a caller could probe
// the limit for free. Reuses budget.ts's AtomicCounterStore so both features
// share one atomic-increment primitive and one production backend.

import type { AtomicCounterStore } from "./budget";

export interface RateLimitConfig {
  perSessionPerHour: number;
  perIpPerHour: number;
  perSessionAttachmentPerHour: number;
}

/** Chosen numbers and reasoning, Sec 8.3: a real user asking Wise Man
 * questions while reading a page does not plausibly exceed ~20/hour;
 * 30 gives headroom for a genuinely active reading session without being
 * useful as a scraping/abuse budget. Per-IP is set higher (100) since one
 * IP can legitimately represent many real users behind NAT/a shared
 * network/an office -- it exists to catch sustained single-actor abuse, not
 * to throttle ordinary shared-IP traffic. Attachment-bearing requests are
 * capped much lower (8/hour) because they cost more per call (larger
 * payload, more tokens) and are the more expensive vector to abuse. */
export function loadRateLimitConfig(env: Partial<Record<string, string>> = process.env): RateLimitConfig {
  const num = (key: string, fallback: number) => {
    const v = Number(env[key]);
    return Number.isFinite(v) && v > 0 ? v : fallback;
  };
  return {
    perSessionPerHour: num("WISE_MAN_RATE_LIMIT_PER_SESSION_PER_HOUR", 30),
    perIpPerHour: num("WISE_MAN_RATE_LIMIT_PER_IP_PER_HOUR", 100),
    perSessionAttachmentPerHour: num("WISE_MAN_RATE_LIMIT_ATTACHMENT_PER_SESSION_PER_HOUR", 8),
  };
}

function hourKey(now: Date): string {
  return now.toISOString().slice(0, 13); // YYYY-MM-DDTHH
}

export interface RateLimitResult {
  allowed: boolean;
  reason?: "session_limit" | "ip_limit" | "session_attachment_limit";
}

export async function checkRateLimit(params: {
  store: AtomicCounterStore;
  config: RateLimitConfig;
  sessionId: string;
  ip: string;
  hasAttachment: boolean;
  now?: Date;
}): Promise<RateLimitResult> {
  const { store, config, sessionId, ip, hasAttachment } = params;
  const now = params.now ?? new Date();
  const hour = hourKey(now);

  const ipCount = await store.incrementAndGet(`wise-man:ratelimit:ip:${ip}:${hour}`, 1);
  if (ipCount > config.perIpPerHour) {
    return { allowed: false, reason: "ip_limit" };
  }

  const sessionCount = await store.incrementAndGet(`wise-man:ratelimit:session:${sessionId}:${hour}`, 1);
  if (sessionCount > config.perSessionPerHour) {
    return { allowed: false, reason: "session_limit" };
  }

  if (hasAttachment) {
    const attachmentCount = await store.incrementAndGet(
      `wise-man:ratelimit:session-attachment:${sessionId}:${hour}`,
      1,
    );
    if (attachmentCount > config.perSessionAttachmentPerHour) {
      return { allowed: false, reason: "session_attachment_limit" };
    }
  }

  return { allowed: true };
}
