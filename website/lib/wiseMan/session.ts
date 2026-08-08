// Wise Man's session definition (CC-1 directive v3, Sec 11.2).
//
// A session is a signed, httpOnly cookie issued on first widget load,
// carrying a random session id and an issued-at timestamp, HMAC-signed with
// a server secret so the server can detect tampering (not to make the
// session unforgeable against a determined attacker -- see the honest
// limitation note below).
//
// LIFETIME: SESSION_TTL_MS (default 24h) from issuance -- a session past
// its TTL is treated as invalid and a fresh one is minted.
//
// HOW TRIVIALLY IT RESETS (stated explicitly, per Sec 11.2's own
// instruction, not silently assumed away): clearing cookies, opening an
// incognito/private window, or switching browsers all mint a brand-new
// session with zero history. Per-session rate limiting is therefore a
// convenience limit, not a security boundary -- PER-IP limiting
// (website/lib/wiseMan/rateLimit.ts) is the real backstop against sustained
// abuse, because an IP is far more expensive for an attacker to rotate than
// a cookie.

import { createHmac, randomUUID, timingSafeEqual } from "node:crypto";

export const SESSION_COOKIE_NAME = "wise_man_session";
export const SESSION_TTL_MS = 24 * 60 * 60 * 1000;

export interface SessionToken {
  id: string;
  issuedAtMs: number;
}

function sign(payload: string, secret: string): string {
  return createHmac("sha256", secret).update(payload).digest("hex");
}

/** Mint a new session token. `token` is the opaque cookie value to set. */
export function createSessionToken(secret: string, now: number = Date.now()): { session: SessionToken; token: string } {
  const session: SessionToken = { id: randomUUID(), issuedAtMs: now };
  const payload = `${session.id}.${session.issuedAtMs}`;
  const token = `${payload}.${sign(payload, secret)}`;
  return { session, token };
}

/**
 * Verifies a cookie value. Returns the session if valid and unexpired, or
 * null if missing, malformed, tampered, or expired -- callers should mint a
 * fresh session in every null case (fail open to a NEW session, not to no
 * rate limiting -- see rateLimit.ts, which treats "no valid session" the
 * same as any other session for limiting purposes).
 */
export function verifySessionToken(token: string | null | undefined, secret: string, now: number = Date.now()): SessionToken | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [id, issuedAtStr, signature] = parts;
  const issuedAtMs = Number(issuedAtStr);
  if (!id || !Number.isFinite(issuedAtMs)) return null;

  const payload = `${id}.${issuedAtStr}`;
  const expected = sign(payload, secret);
  const expectedBuf = Buffer.from(expected, "hex");
  const actualBuf = Buffer.from(signature, "hex");
  if (expectedBuf.length !== actualBuf.length || !timingSafeEqual(expectedBuf, actualBuf)) {
    return null;
  }
  if (now - issuedAtMs > SESSION_TTL_MS || now < issuedAtMs) {
    return null;
  }
  return { id, issuedAtMs };
}
