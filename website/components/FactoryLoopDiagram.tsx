"use client";

// CC-1 Part D3: replaces the previous hand-rolled SVG (which had its own
// documented reasoning for staying hand-rolled -- "what is fundamentally a
// static 5-node flowchart") with @xyflow/react (React Flow, MIT, free core
// only -- no Pro-tier import anywhere in this file) per explicit directive.
// STRUCTURAL ONLY this pass: node positions/labels/edges are hand-authored
// constants below, matching the previous SVG's exact same 5 nodes and edge
// semantics -- wiring node counts to live fetchJson data is a separate
// follow-up, not attempted here. Interactivity (drag/connect/zoom/pan) is
// deliberately disabled -- this is a diagram embedded in a docs-style page,
// not an interactive canvas.
import { Background, Handle, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

const NODE_STYLE_BASE: React.CSSProperties = {
  background: "#0a0e27",
  color: "#e8e2d0",
  borderRadius: 8,
  fontFamily: "Georgia, Cambria, 'Times New Roman', Times, serif",
  fontSize: 13,
  padding: "10px 14px",
  width: 170,
  textAlign: "center",
};

function stageNode(stroke: string) {
  return { ...NODE_STYLE_BASE, border: `1.5px solid ${stroke}` };
}

function StageNode({ data }: { data: { label: string; sublabel?: string } }) {
  return (
    <>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div>{data.label}</div>
      {data.sublabel ? (
        <div style={{ color: "#8a94ad", fontSize: 10, fontFamily: "system-ui, sans-serif", marginTop: 2 }}>
          {data.sublabel}
        </div>
      ) : null}
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </>
  );
}

const NODE_TYPES = { stage: StageNode };

const NODES: Node[] = [
  {
    id: "agents", type: "stage", position: { x: 0, y: 0 },
    data: { label: "Adam & Eve", sublabel: "research agents" },
    style: stageNode("#d4af37"),
  },
  {
    id: "test", type: "stage", position: { x: 230, y: 0 },
    data: { label: "Test Harness", sublabel: "backtest + verdict" },
    style: stageNode("#d4af37"),
  },
  {
    id: "trial", type: "stage", position: { x: 460, y: 0 },
    data: { label: "Forward Trial", sublabel: "forward-tracked" },
    style: stageNode("#2ec4b6"),
  },
  {
    id: "graveyard", type: "stage", position: { x: 230, y: 140 },
    data: { label: "Graveyard", sublabel: "distilled, not raw" },
    style: stageNode("#d47a6a"),
  },
  {
    id: "repair", type: "stage", position: { x: 460, y: 140 },
    data: { label: "Repair Lab", sublabel: "human-invoked only" },
    style: stageNode("#8a94ad"),
  },
];

const EDGE_STYLE = { stroke: "#8a94ad", strokeWidth: 1.5 };
const EDGE_LABEL_STYLE = { fill: "#8a94ad", fontSize: 10 };

const EDGES: Edge[] = [
  { id: "agents-test", source: "agents", target: "test", label: "propose", style: EDGE_STYLE, labelStyle: EDGE_LABEL_STYLE, markerEnd: { type: "arrowclosed" as const, color: "#8a94ad" } },
  { id: "test-trial", source: "test", target: "trial", label: "SURVIVED / PROMISING", style: EDGE_STYLE, labelStyle: EDGE_LABEL_STYLE, markerEnd: { type: "arrowclosed" as const, color: "#8a94ad" } },
  { id: "test-graveyard", source: "test", target: "graveyard", label: "DIED", style: EDGE_STYLE, labelStyle: EDGE_LABEL_STYLE, markerEnd: { type: "arrowclosed" as const, color: "#8a94ad" } },
  { id: "graveyard-repair", source: "graveyard", target: "repair", label: "human review", style: { ...EDGE_STYLE, strokeDasharray: "4 3" }, labelStyle: EDGE_LABEL_STYLE, markerEnd: { type: "arrowclosed" as const, color: "#8a94ad" } },
  // The lineage edge: a repaired candidate goes back into Forward Trial, not a fresh Test Harness pass.
  {
    id: "repair-trial", source: "repair", target: "trial", label: "repaired & passes",
    style: { ...EDGE_STYLE, strokeDasharray: "4 3" }, labelStyle: EDGE_LABEL_STYLE,
    markerEnd: { type: "arrowclosed" as const, color: "#8a94ad" }, type: "smoothstep",
  },
];

export default function FactoryLoopDiagram() {
  return (
    <div
      role="img"
      aria-label="Factory Loop: Adam and Eve propose hypotheses, the test harness scores them, survivors enter Forward Trial while failures go to the Graveyard, and diagnosed Graveyard failures can be human-repaired back into Forward Trial."
      style={{ height: 260, background: "#0a0e27", borderRadius: 8 }}
      className="w-full max-w-2xl"
    >
      <ReactFlow
        nodes={NODES}
        edges={EDGES}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        panOnScroll={false}
        zoomOnScroll={false}
        zoomOnDoubleClick={false}
        zoomOnPinch={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#8a94ad" gap={24} size={0.5} style={{ opacity: 0.15 }} />
      </ReactFlow>
    </div>
  );
}
