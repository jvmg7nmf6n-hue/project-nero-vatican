import { deriveSystemStatus } from "@/lib/systemStatus";
import type { HeartbeatStatus } from "@/lib/types";

const LEVEL_STYLES: Record<"live" | "delayed" | "down", string> = {
  live: "bg-teal",
  delayed: "bg-gold",
  down: "bg-loss",
};

const LEVEL_LABELS: Record<"live" | "delayed" | "down", string> = {
  live: "system status: live",
  delayed: "system status: delayed",
  down: "system status: stale",
};

export interface SystemStatusProps {
  heartbeat: HeartbeatStatus | null;
}

// Deliberately minimal (Phase 2 nicety, per spec) -- a dot and one line of text,
// nothing else. Renders nothing at all rather than a fabricated status when
// heartbeat.json doesn't exist yet.
export default function SystemStatus({ heartbeat }: SystemStatusProps) {
  const level = deriveSystemStatus(heartbeat, new Date());
  if (level === null) {
    return null;
  }

  return (
    <div
      data-testid="system-status"
      data-level={level}
      className="inline-flex items-center gap-2 text-xs text-muted"
    >
      <span className={`h-2 w-2 rounded-full ${LEVEL_STYLES[level]}`} aria-hidden="true" />
      {LEVEL_LABELS[level]}
    </div>
  );
}
