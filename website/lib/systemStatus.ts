import type { HeartbeatStatus } from "./types";

export type SystemStatusLevel = "live" | "delayed" | "down";

const LIVE_THRESHOLD_HOURS = 1;
const DELAYED_THRESHOLD_HOURS = 3;

// Mirrors the color bands the task asked for (green < 1hr, amber < 3hr, red
// beyond) -- "down" here is a display label, not a claim the scheduler process
// itself crashed; nero_core/execution/scheduler_heartbeat_alert.py is the actual
// dead-man's-switch check, this is just a passive readout of the same file.
export function deriveSystemStatus(
  heartbeat: HeartbeatStatus | null,
  now: Date
): SystemStatusLevel | null {
  if (!heartbeat) {
    return null;
  }
  const lastRun = new Date(heartbeat.last_successful_run);
  if (Number.isNaN(lastRun.getTime())) {
    return null;
  }
  const ageHours = (now.getTime() - lastRun.getTime()) / (1000 * 60 * 60);
  if (ageHours < LIVE_THRESHOLD_HOURS) {
    return "live";
  }
  if (ageHours < DELAYED_THRESHOLD_HOURS) {
    return "delayed";
  }
  return "down";
}
