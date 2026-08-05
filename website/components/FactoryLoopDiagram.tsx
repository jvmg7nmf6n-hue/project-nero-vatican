// CC-1 Factory Loop directive, item 8: hand-rolled SVG, matching this
// codebase's existing precedent (components/Logo.tsx, EquityCurveChart.tsx,
// MarketsOverview.tsx are the only 3 hand-rolled <svg> components on the
// whole site) rather than pulling in a diagramming dependency
// (Mermaid/React Flow) for what is fundamentally a static 5-node flowchart.
// No animation, no live data -- a static map of the target loop shape.

interface NodeSpec {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  sublabel?: string;
  stroke: string;
}

const NODES: NodeSpec[] = [
  { id: "agents", x: 20, y: 20, w: 160, h: 56, label: "Adam & Eve", sublabel: "research agents", stroke: "#d4af37" },
  { id: "test", x: 220, y: 20, w: 160, h: 56, label: "Test Harness", sublabel: "backtest + verdict", stroke: "#d4af37" },
  { id: "trial", x: 420, y: 20, w: 170, h: 56, label: "Forward Trial", sublabel: "forward-tracked", stroke: "#2ec4b6" },
  { id: "graveyard", x: 220, y: 130, w: 160, h: 56, label: "Graveyard", sublabel: "distilled, not raw", stroke: "#d47a6a" },
  { id: "repair", x: 420, y: 130, w: 170, h: 56, label: "Repair", sublabel: "human-invoked only", stroke: "#8a94ad" },
];

function Node({ node }: { node: NodeSpec }) {
  return (
    <g>
      <rect
        x={node.x}
        y={node.y}
        width={node.w}
        height={node.h}
        rx={8}
        fill="#0a0e27"
        stroke={node.stroke}
        strokeWidth={1.5}
      />
      <text x={node.x + node.w / 2} y={node.y + node.h / 2 - 4} textAnchor="middle" fill="#e8e2d0" fontSize="13" fontFamily="serif">
        {node.label}
      </text>
      {node.sublabel ? (
        <text x={node.x + node.w / 2} y={node.y + node.h / 2 + 14} textAnchor="middle" fill="#8a94ad" fontSize="10">
          {node.sublabel}
        </text>
      ) : null}
    </g>
  );
}

function Arrow({ from, to, label, dashed }: { from: [number, number]; to: [number, number]; label?: string; dashed?: boolean }) {
  const midX = (from[0] + to[0]) / 2;
  const midY = (from[1] + to[1]) / 2;
  return (
    <g>
      <defs>
        <marker id={`arrowhead-${from.join("-")}-${to.join("-")}`} markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#8a94ad" />
        </marker>
      </defs>
      <path
        d={`M ${from[0]} ${from[1]} L ${to[0]} ${to[1]}`}
        stroke="#8a94ad"
        strokeWidth={1.5}
        strokeDasharray={dashed ? "4 3" : undefined}
        markerEnd={`url(#arrowhead-${from.join("-")}-${to.join("-")})`}
        fill="none"
      />
      {label ? (
        <text x={midX} y={midY - 6} textAnchor="middle" fill="#8a94ad" fontSize="9">
          {label}
        </text>
      ) : null}
    </g>
  );
}

export default function FactoryLoopDiagram() {
  return (
    <svg
      viewBox="0 0 620 210"
      role="img"
      aria-label="Factory Loop: Adam and Eve propose hypotheses, the test harness scores them, survivors enter Forward Trial while failures go to the Graveyard, and diagnosed Graveyard failures can be human-repaired back into Forward Trial."
      className="w-full h-auto max-w-2xl"
      xmlns="http://www.w3.org/2000/svg"
    >
      {NODES.map((n) => (
        <Node key={n.id} node={n} />
      ))}
      <Arrow from={[180, 48]} to={[220, 48]} label="propose" />
      <Arrow from={[380, 48]} to={[420, 48]} label="SURVIVED / PROMISING" />
      <Arrow from={[300, 76]} to={[300, 130]} label="DIED" />
      <Arrow from={[505, 76]} to={[505, 130]} label="human review" dashed />
      <Arrow from={[420, 158]} to={[380, 158]} label="repaired & passes" />
      <path d="M 300 130 C 300 90, 420 60, 420 48" stroke="#8a94ad" strokeWidth={1.5} strokeDasharray="4 3" fill="none" markerEnd="url(#arrowhead-repaired)" />
      <defs>
        <marker id="arrowhead-repaired" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#8a94ad" />
        </marker>
      </defs>
      <text x={300} y={95} textAnchor="middle" fill="#8a94ad" fontSize="9">
        repaired &amp; passes
      </text>
    </svg>
  );
}
