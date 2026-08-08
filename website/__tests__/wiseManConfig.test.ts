import { isWiseManEnabled, loadAllowedOrigins, isAllowedOrigin } from "@/lib/wiseMan/config";
import { WISE_MAN_ERROR_MESSAGES, formatWiseManError, WiseManErrorCode } from "@/lib/wiseMan/errors";

describe("isWiseManEnabled (Sec 8.1 feature flag, both states)", () => {
  it("defaults to disabled when unset", () => {
    expect(isWiseManEnabled({})).toBe(false);
  });
  it.each(["1", "true", "TRUE", "yes", "Yes", "on"])("is enabled for %s", (val) => {
    expect(isWiseManEnabled({ WISE_MAN_ENABLED: val })).toBe(true);
  });
  it.each(["0", "false", "no", "off", "banana", ""])("is disabled for %s", (val) => {
    expect(isWiseManEnabled({ WISE_MAN_ENABLED: val })).toBe(false);
  });
});

describe("origin allowlist (Sec 8.5)", () => {
  it("falls back to the production domain + localhost when unconfigured", () => {
    const origins = loadAllowedOrigins({});
    expect(origins).toContain("https://project-nero-vatican.vercel.app");
  });
  it("reads a comma-separated override", () => {
    const origins = loadAllowedOrigins({ WISE_MAN_ALLOWED_ORIGINS: "https://a.com, https://b.com" });
    expect(origins).toEqual(["https://a.com", "https://b.com"]);
  });
  it("rejects a null or unlisted origin", () => {
    const allowed = loadAllowedOrigins({ WISE_MAN_ALLOWED_ORIGINS: "https://a.com" });
    expect(isAllowedOrigin(null, allowed)).toBe(false);
    expect(isAllowedOrigin("https://evil.com", allowed)).toBe(false);
    expect(isAllowedOrigin("https://a.com", allowed)).toBe(true);
  });
});

describe("bilingual error messages (Sec 8.8, all user-facing failure states)", () => {
  const REQUIRED_CODES: WiseManErrorCode[] = [
    "rate_limit_session",
    "rate_limit_ip",
    "budget_daily",
    "budget_monthly",
    "timeout",
    "guardrail_failed_closed",
  ];

  it("every error code has both an English and a Roman Urdu message", () => {
    for (const code of Object.keys(WISE_MAN_ERROR_MESSAGES) as WiseManErrorCode[]) {
      const msg = formatWiseManError(code);
      expect(msg.en.length).toBeGreaterThan(0);
      expect(msg.ur.length).toBeGreaterThan(0);
    }
  });

  it("covers every failure state named at GATE B kickoff: rate limit, cap breach, timeout, guardrail-fail-closed", () => {
    for (const code of REQUIRED_CODES) {
      expect(WISE_MAN_ERROR_MESSAGES[code]).toBeDefined();
    }
  });

  it("English and Roman Urdu messages are never identical (a real translation, not a copy-paste)", () => {
    for (const code of Object.keys(WISE_MAN_ERROR_MESSAGES) as WiseManErrorCode[]) {
      const msg = formatWiseManError(code);
      expect(msg.en).not.toBe(msg.ur);
    }
  });
});
