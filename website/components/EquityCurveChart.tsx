import type { EquityCurve } from "@/lib/equityCurve";
import type { TradeResult } from "@/lib/tradeHistory";

const WIDTH = 640;
const HEIGHT = 220;
const PADDING = 28;

// Direct hex values (matching the site's design tokens: teal/loss-red/muted) --
// these are SVG fill/stroke attributes, not Tailwind classes, so there's no risk
// of tailwind.config.ts's content scanner missing them the way it would a
// Tailwind class-name string placed outside app/ or components/.
const RESULT_DOT_COLORS: Record<TradeResult, string> = {
  win: "#2ec4b6",
  loss: "#d47a6a",
  flat: "#8a94ad",
};

export interface EquityCurveChartProps {
  curve: EquityCurve;
}

// A hand-drawn, dependency-free SVG line chart -- no charting library, zero
// bundle-size impact -- rendered server-side as static markup. See the Step 7
// commit message for why this replaces a literal candlestick chart: there is no
// OHLC price data exported anywhere in docs/site_data/*.json to plot in the
// first place (only ledger signal events), and building that pipeline is a
// materially larger undertaking than a charting decision.
export default function EquityCurveChart({ curve }: EquityCurveChartProps) {
  const { points, unit } = curve;
  if (points.length === 0) {
    return null;
  }

  const values = points.map((p) => p.cumulativeValue);
  const maxValue = Math.max(...values, 0);
  const minValue = Math.min(...values, 0);
  const valueRange = maxValue - minValue || 1;

  const xFor = (index: number) =>
    points.length === 1
      ? WIDTH / 2
      : PADDING + ((index - 1) / (points.length - 1)) * (WIDTH - 2 * PADDING);
  const yFor = (value: number) =>
    HEIGHT - PADDING - ((value - minValue) / valueRange) * (HEIGHT - 2 * PADDING);

  const zeroY = yFor(0);
  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${xFor(p.index).toFixed(1)} ${yFor(p.cumulativeValue).toFixed(1)}`)
    .join(" ");

  const unitLabel = unit === "r_multiple" ? "Cumulative R" : "Cumulative % return";

  return (
    <svg
      data-testid="equity-curve-chart"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full h-auto"
      role="img"
      aria-label={`Equity curve: ${unitLabel} across ${points.length} resolved trades`}
    >
      <line
        x1={PADDING}
        y1={zeroY}
        x2={WIDTH - PADDING}
        y2={zeroY}
        stroke="#8a94ad"
        strokeWidth="1"
        strokeDasharray="4 4"
        opacity="0.5"
      />
      <path d={pathD} fill="none" stroke="#d4af37" strokeWidth="2" />
      {points.map((p) => (
        <circle
          key={p.index}
          data-testid="equity-curve-point"
          data-result={p.tradeResult}
          cx={xFor(p.index)}
          cy={yFor(p.cumulativeValue)}
          r="4"
          fill={RESULT_DOT_COLORS[p.tradeResult]}
        />
      ))}
      <text x={PADDING} y={16} fontSize="11" fill="#8a94ad">
        {unitLabel}
      </text>
    </svg>
  );
}
