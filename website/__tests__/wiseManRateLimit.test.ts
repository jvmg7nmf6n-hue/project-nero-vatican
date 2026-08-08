import { createInMemoryCounterStore } from "@/lib/wiseMan/budget";
import { checkRateLimit, loadRateLimitConfig } from "@/lib/wiseMan/rateLimit";

describe("loadRateLimitConfig (Sec 8.3)", () => {
  it("has sane defaults with a lower attachment cap than the plain session cap", () => {
    const cfg = loadRateLimitConfig({});
    expect(cfg.perSessionPerHour).toBeGreaterThan(0);
    expect(cfg.perIpPerHour).toBeGreaterThan(0);
    expect(cfg.perSessionAttachmentPerHour).toBeLessThan(cfg.perSessionPerHour);
  });

  it("reads env overrides", () => {
    const cfg = loadRateLimitConfig({
      WISE_MAN_RATE_LIMIT_PER_SESSION_PER_HOUR: "5",
      WISE_MAN_RATE_LIMIT_PER_IP_PER_HOUR: "10",
      WISE_MAN_RATE_LIMIT_ATTACHMENT_PER_SESSION_PER_HOUR: "2",
    });
    expect(cfg.perSessionPerHour).toBe(5);
    expect(cfg.perIpPerHour).toBe(10);
    expect(cfg.perSessionAttachmentPerHour).toBe(2);
  });
});

describe("checkRateLimit (Sec 8.3, per-session AND per-IP, lower cap for attachments)", () => {
  const config = { perSessionPerHour: 3, perIpPerHour: 100, perSessionAttachmentPerHour: 1 };

  it("allows requests under the session limit", async () => {
    const store = createInMemoryCounterStore();
    const r1 = await checkRateLimit({ store, config, sessionId: "s1", ip: "1.2.3.4", hasAttachment: false });
    const r2 = await checkRateLimit({ store, config, sessionId: "s1", ip: "1.2.3.4", hasAttachment: false });
    expect(r1.allowed).toBe(true);
    expect(r2.allowed).toBe(true);
  });

  it("blocks once the per-session limit is exceeded", async () => {
    const store = createInMemoryCounterStore();
    for (let i = 0; i < config.perSessionPerHour; i++) {
      const r = await checkRateLimit({ store, config, sessionId: "s1", ip: "1.2.3.4", hasAttachment: false });
      expect(r.allowed).toBe(true);
    }
    const blocked = await checkRateLimit({ store, config, sessionId: "s1", ip: "1.2.3.4", hasAttachment: false });
    expect(blocked.allowed).toBe(false);
    expect(blocked.reason).toBe("session_limit");
  });

  it("PER-IP IS THE REAL BACKSTOP: blocks a rotating-session attacker on the same IP (Sec 11.2)", async () => {
    const store = createInMemoryCounterStore();
    const tightIpConfig = { perSessionPerHour: 1000, perIpPerHour: 3, perSessionAttachmentPerHour: 1000 };
    // A different session id every request (simulating cookie-clearing) --
    // per-session limiting alone would never catch this.
    for (let i = 0; i < tightIpConfig.perIpPerHour; i++) {
      const r = await checkRateLimit({
        store,
        config: tightIpConfig,
        sessionId: `rotating-session-${i}`,
        ip: "9.9.9.9",
        hasAttachment: false,
      });
      expect(r.allowed).toBe(true);
    }
    const blocked = await checkRateLimit({
      store,
      config: tightIpConfig,
      sessionId: "rotating-session-final",
      ip: "9.9.9.9",
      hasAttachment: false,
    });
    expect(blocked.allowed).toBe(false);
    expect(blocked.reason).toBe("ip_limit");
  });

  it("applies the lower attachment-specific cap even when the plain session cap has room", async () => {
    const store = createInMemoryCounterStore();
    const first = await checkRateLimit({ store, config, sessionId: "s1", ip: "1.2.3.4", hasAttachment: true });
    expect(first.allowed).toBe(true);
    const second = await checkRateLimit({ store, config, sessionId: "s1", ip: "1.2.3.4", hasAttachment: true });
    expect(second.allowed).toBe(false);
    expect(second.reason).toBe("session_attachment_limit");
  });

  it("a non-attachment request does not consume the attachment budget", async () => {
    const store = createInMemoryCounterStore();
    await checkRateLimit({ store, config, sessionId: "s1", ip: "1.2.3.4", hasAttachment: false });
    const attachmentRequest = await checkRateLimit({ store, config, sessionId: "s1", ip: "1.2.3.4", hasAttachment: true });
    expect(attachmentRequest.allowed).toBe(true);
  });

  it("different sessions on different IPs are tracked independently", async () => {
    const store = createInMemoryCounterStore();
    for (let i = 0; i < config.perSessionPerHour; i++) {
      await checkRateLimit({ store, config, sessionId: "s1", ip: "1.1.1.1", hasAttachment: false });
    }
    const blocked = await checkRateLimit({ store, config, sessionId: "s1", ip: "1.1.1.1", hasAttachment: false });
    expect(blocked.allowed).toBe(false);
    const otherSession = await checkRateLimit({ store, config, sessionId: "s2", ip: "2.2.2.2", hasAttachment: false });
    expect(otherSession.allowed).toBe(true);
  });
});
