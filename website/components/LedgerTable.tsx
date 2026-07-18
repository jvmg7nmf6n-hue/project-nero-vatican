import type { LedgerRow } from "@/lib/types";

export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

// EXIT rows carry the outcome in free-text reasoning (there's no separate
// structured win/loss field in the ledger), so surface that text directly.
export function resultLabel(row: LedgerRow): string {
  if (row.signal_type === "EXIT") {
    return row.reasoning || "Position closed";
  }
  if (row.signal_type === "ENTRY") {
    return row.entry_price !== null ? `Opened @ ${row.entry_price}` : "Opened";
  }
  return row.reasoning || row.signal_type;
}

export function isLoss(row: LedgerRow): boolean {
  if (row.signal_type !== "EXIT") {
    return false;
  }
  if (row.entry_price === null || row.exit_price === null) {
    return false;
  }
  return row.exit_price < row.entry_price;
}

export interface LedgerTableProps {
  rows: LedgerRow[];
  trackingSince?: string;
  id?: string;
}

export default function LedgerTable({ rows, trackingSince, id }: LedgerTableProps) {
  if (rows.length === 0) {
    return (
      <div id={id} data-testid="ledger-empty-state" className="text-muted">
        {trackingSince
          ? `Tracking started on ${trackingSince}. No signals logged yet.`
          : "No signals logged yet."}
      </div>
    );
  }

  return (
    <div id={id} data-testid="ledger-table" className="overflow-x-auto">
      <table className="w-full text-left">
        <thead>
          <tr className="text-muted border-b border-muted/30">
            <th className="py-2 pr-4">Timestamp</th>
            <th className="py-2 pr-4">Strategy</th>
            <th className="py-2 pr-4">Signal</th>
            <th className="py-2 pr-4">Result</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const loss = isLoss(row);
            return (
              <tr
                key={`${row.strategy}-${row.asset}-${row.candle_timestamp}-${index}`}
                className="border-b border-muted/10"
              >
                <td className="py-2 pr-4">{formatTimestamp(row.timestamp)}</td>
                <td className="py-2 pr-4">
                  {row.strategy} ({row.asset})
                </td>
                <td className="py-2 pr-4">{row.signal_type}</td>
                <td className={`py-2 pr-4 ${loss ? "text-loss" : ""}`}>
                  {resultLabel(row)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-muted text-sm mt-3">
        Losses shown above are real and stay on the record.
      </p>
    </div>
  );
}
