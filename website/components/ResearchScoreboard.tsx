"use client";

import { useMemo, useState } from "react";
import {
  filterScoreboardByStatus,
  SCOREBOARD_STATUS_ORDER,
  sortScoreboardByWinRate,
  type ScoreboardRow,
  type ScoreboardStatus,
} from "@/lib/researchScoreboard";

const REPO_BLOB_BASE = "https://github.com/jvmg7nmf6n-hue/project-nero-vatican/blob/main";

const STATUS_FILTERS: Array<ScoreboardStatus | "All"> = ["All", ...SCOREBOARD_STATUS_ORDER];

export interface ResearchScoreboardProps {
  rows: ScoreboardRow[];
}

export default function ResearchScoreboard({ rows }: ResearchScoreboardProps) {
  const [statusFilter, setStatusFilter] = useState<ScoreboardStatus | "All">("All");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc" | null>(null);

  const visibleRows = useMemo(() => {
    const filtered = filterScoreboardByStatus(rows, statusFilter);
    return sortDirection ? sortScoreboardByWinRate(filtered, sortDirection) : filtered;
  }, [rows, statusFilter, sortDirection]);

  function toggleSort() {
    setSortDirection((prev) => (prev === "desc" ? "asc" : "desc"));
  }

  if (rows.length === 0) {
    return <p className="text-muted">No research history recorded yet.</p>;
  }

  return (
    <div data-testid="research-scoreboard">
      <div data-testid="scoreboard-filters" className="flex flex-wrap gap-2 mb-4">
        {STATUS_FILTERS.map((status) => (
          <button
            key={status}
            type="button"
            data-testid={`scoreboard-filter-${status}`}
            aria-pressed={statusFilter === status}
            onClick={() => setStatusFilter(status)}
            className={`rounded-full border px-3 py-1 text-xs capitalize transition ${
              statusFilter === status
                ? "border-gold/60 text-parchment bg-gold/10"
                : "border-muted/30 text-muted"
            }`}
          >
            {status}
          </button>
        ))}
      </div>

      {visibleRows.length === 0 ? (
        <p data-testid="scoreboard-empty" className="text-muted">
          No strategies match this filter.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="text-muted border-b border-muted/30">
                <th className="py-2 pr-4">Name</th>
                <th className="py-2 pr-4">Family</th>
                <th className="py-2 pr-4">Asset</th>
                <th className="py-2 pr-4">Timeframe</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">
                  <button
                    type="button"
                    data-testid="scoreboard-sort-winrate"
                    onClick={toggleSort}
                    className="hover:text-parchment"
                  >
                    Win rate{" "}
                    {sortDirection === "desc" ? "↓" : sortDirection === "asc" ? "↑" : ""}
                  </button>
                </th>
                <th className="py-2 pr-4">Source</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row, index) => (
                <tr
                  key={`${row.name}-${row.family}-${row.asset ?? "na"}-${index}`}
                  data-testid="scoreboard-row"
                  data-status={row.status}
                  className="border-b border-muted/10"
                >
                  <td className="py-2 pr-4 text-parchment">{row.name}</td>
                  <td className="py-2 pr-4">{row.family}</td>
                  <td className="py-2 pr-4">{row.asset ?? "—"}</td>
                  <td className="py-2 pr-4">{row.timeframe ?? "—"}</td>
                  <td className="py-2 pr-4 capitalize">{row.status}</td>
                  <td className="py-2 pr-4">
                    {row.winRate !== null ? `${(row.winRate * 100).toFixed(0)}%` : "—"}
                  </td>
                  <td className="py-2 pr-4">
                    {row.sourceDoc ? (
                      <a
                        href={`${REPO_BLOB_BASE}/${row.sourceDoc}`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-teal underline"
                      >
                        report
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
