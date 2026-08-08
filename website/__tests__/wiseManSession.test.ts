import { createSessionToken, verifySessionToken, SESSION_TTL_MS } from "@/lib/wiseMan/session";

const SECRET = "test-secret-not-real";

describe("Wise Man session tokens (Sec 11.2)", () => {
  it("round-trips: a freshly created token verifies to the same session id", () => {
    const now = 1_700_000_000_000;
    const { session, token } = createSessionToken(SECRET, now);
    const verified = verifySessionToken(token, SECRET, now);
    expect(verified).not.toBeNull();
    expect(verified?.id).toBe(session.id);
    expect(verified?.issuedAtMs).toBe(now);
  });

  it("rejects a token signed with a different secret (tamper detection)", () => {
    const now = 1_700_000_000_000;
    const { token } = createSessionToken(SECRET, now);
    expect(verifySessionToken(token, "different-secret", now)).toBeNull();
  });

  it("rejects a token with a flipped character in the signature", () => {
    const now = 1_700_000_000_000;
    const { token } = createSessionToken(SECRET, now);
    const tampered = token.slice(0, -1) + (token.at(-1) === "a" ? "b" : "a");
    expect(verifySessionToken(tampered, SECRET, now)).toBeNull();
  });

  it("rejects null/undefined/empty/malformed tokens", () => {
    expect(verifySessionToken(null, SECRET)).toBeNull();
    expect(verifySessionToken(undefined, SECRET)).toBeNull();
    expect(verifySessionToken("", SECRET)).toBeNull();
    expect(verifySessionToken("not.a.valid.token.shape", SECRET)).toBeNull();
    expect(verifySessionToken("justonestring", SECRET)).toBeNull();
  });

  it("rejects an expired token (past SESSION_TTL_MS)", () => {
    const issuedAt = 1_700_000_000_000;
    const { token } = createSessionToken(SECRET, issuedAt);
    const wellPastTtl = issuedAt + SESSION_TTL_MS + 1;
    expect(verifySessionToken(token, SECRET, wellPastTtl)).toBeNull();
  });

  it("accepts a token right at the TTL boundary but rejects just past it", () => {
    const issuedAt = 1_700_000_000_000;
    const { token } = createSessionToken(SECRET, issuedAt);
    expect(verifySessionToken(token, SECRET, issuedAt + SESSION_TTL_MS)).not.toBeNull();
    expect(verifySessionToken(token, SECRET, issuedAt + SESSION_TTL_MS + 1)).toBeNull();
  });

  it("two sessions minted back-to-back get different ids", () => {
    const a = createSessionToken(SECRET);
    const b = createSessionToken(SECRET);
    expect(a.session.id).not.toBe(b.session.id);
  });
});
