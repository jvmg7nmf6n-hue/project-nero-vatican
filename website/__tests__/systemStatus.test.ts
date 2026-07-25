import { deriveSystemStatus } from "@/lib/systemStatus";
import type { HeartbeatStatus } from "@/lib/types";

const NOW = new Date("2026-07-25T12:00:00Z");

function heartbeatMinutesAgo(minutes: number): HeartbeatStatus {
  return {
    last_successful_run: new Date(NOW.getTime() - minutes * 60_000).toISOString(),
    run_count_24h: 48,
  };
}

describe("deriveSystemStatus", () => {
  it("returns null when there is no heartbeat at all", () => {
    expect(deriveSystemStatus(null, NOW)).toBeNull();
  });

  it("returns null when the timestamp fails to parse", () => {
    expect(
      deriveSystemStatus({ last_successful_run: "not-a-date", run_count_24h: 0 }, NOW)
    ).toBeNull();
  });

  it("is 'live' when the last run was under 1 hour ago", () => {
    expect(deriveSystemStatus(heartbeatMinutesAgo(30), NOW)).toBe("live");
  });

  it("is 'delayed' when the last run was between 1 and 3 hours ago", () => {
    expect(deriveSystemStatus(heartbeatMinutesAgo(90), NOW)).toBe("delayed");
  });

  it("is 'down' when the last run was 3+ hours ago", () => {
    expect(deriveSystemStatus(heartbeatMinutesAgo(200), NOW)).toBe("down");
  });

  it("is 'live' at exactly the boundary just under 1 hour", () => {
    expect(deriveSystemStatus(heartbeatMinutesAgo(59), NOW)).toBe("live");
  });
});
