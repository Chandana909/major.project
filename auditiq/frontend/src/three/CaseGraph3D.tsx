import { useMemo, useState } from "react";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import type { CaseEdge, CaseNode } from "../api/types";
import { BLACKLISTED_COLOR, count, riskColor, rupeesCompact } from "../lib/format";
import { CASE_EDGE_COLORS, caseLayout, type PlacedCaseNode } from "./caseLayout";
import { SceneFrame } from "./SceneFrame";

const SEVERITY_COLORS: Record<string, string> = { critical: "#f87171", high: "#fb923c", medium: "#facc15", low: "#cbd5e1" };
const CENTRE: [number, number, number] = [0, 1.6, 0];

function colorOf(n: CaseNode): string {
  switch (n.kind) {
    case "vendor":
      return n.blacklisted ? BLACKLISTED_COLOR : riskColor(n.risk ?? 0);
    case "invoice":
      return riskColor(n.risk ?? 0);
    case "rule":
      return SEVERITY_COLORS[n.severity ?? "low"] ?? "#cbd5e1";
    case "approver":
      return "#e2e8f0";
    default:
      return "#a78bfa";
  }
}

function describe(n: CaseNode): string[] {
  switch (n.kind) {
    case "vendor":
      return [n.category ?? "", `${count(n.flagged ?? 0)} of ${count(n.invoices ?? 0)} invoices with findings`, `${rupeesCompact(n.amount ?? 0)} with findings`, n.blacklisted ? "blacklisted" : ""];
    case "approver":
      return [`${n.role ?? ""}${n.limit ? `, limit ${rupeesCompact(n.limit)}` : ""}`, `${count(n.flagged ?? 0)} approvals with findings, ${count(n.over_limit ?? 0)} above the limit`];
    case "rule":
      return [`${n.severity} rule`, `${count(n.invoices ?? 0)} invoices break it`];
    case "invoice":
      return [`${rupeesCompact(n.amount ?? 0)} · ${n.date ?? ""}`, `score ${(n.risk ?? 0).toFixed(0)} · ${n.level} · ${n.route}`];
    default:
      return [`${n.vendors ?? 0} vendors, ${n.approvers ?? 0} approvers`, `${rupeesCompact(n.amount ?? 0)} with findings`];
  }
}

function Shape({ node }: { node: PlacedCaseNode }) {
  switch (node.kind) {
    case "vendor":
      return <sphereGeometry args={[0.22 + Math.min(0.2, (node.flagged ?? 0) * 0.01), 20, 16]} />;
    case "approver":
      return <octahedronGeometry args={[0.3, 0]} />;
    case "rule":
      return <boxGeometry args={[0.36, 0.36, 0.36]} />;
    case "invoice":
      return <boxGeometry args={[0.16, 0.2, 0.05]} />;
    default:
      return <icosahedronGeometry args={[0.42, 0]} />;
  }
}

function Links({ edges, at, lit }: { edges: CaseEdge[]; at: Map<string, PlacedCaseNode>; lit: Set<string> | null }) {
  const [bright, dim] = useMemo(() => {
    const make = (list: CaseEdge[]) => {
      const points: number[] = [];
      const colors: number[] = [];
      const tint = new THREE.Color();
      for (const e of list) {
        const a = at.get(e.source), b = at.get(e.target);
        if (!a || !b) continue;
        points.push(...a.position, ...b.position);
        tint.set(CASE_EDGE_COLORS[e.kind] ?? "#94a3b8");
        colors.push(tint.r, tint.g, tint.b, tint.r, tint.g, tint.b);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
      g.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      return g;
    };
    const inside = (e: CaseEdge) => !lit || (lit.has(e.source) && lit.has(e.target));
    return [make(edges.filter(inside)), make(lit ? edges.filter((e) => !inside(e)) : [])];
  }, [edges, at, lit]);
  return (
    <>
      <lineSegments geometry={bright}>
        <lineBasicMaterial vertexColors transparent opacity={0.85} />
      </lineSegments>
      <lineSegments geometry={dim}>
        <lineBasicMaterial vertexColors transparent opacity={0.1} />
      </lineSegments>
    </>
  );
}

/** The audited ledger as a graph in 3D: rules in the middle, approvers and vendors around them, invoices outside. */
export function CaseGraph3D({ nodes, edges, highlight, selected, onSelect }: {
  nodes: CaseNode[];
  edges: CaseEdge[];
  highlight: Set<string> | null;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const [hover, setHover] = useState<PlacedCaseNode | null>(null);
  const placed = useMemo(() => caseLayout(nodes, edges), [nodes, edges]);
  const at = useMemo(() => new Map(placed.map((n) => [n.id, n])), [placed]);
  const lit = highlight ?? (selected ? new Set([selected, ...edges.filter((e) => e.source === selected || e.target === selected).flatMap((e) => [e.source, e.target])]) : null);
  return (
    <SceneFrame label={`Ledger graph: ${nodes.length} nodes and ${edges.length} relations`} height={540} camera={[0, 10, 16]} target={CENTRE} autoRotate={!lit}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.3, 0]} onClick={() => onSelect(null)}>
        <circleGeometry args={[11, 72]} />
        <meshStandardMaterial color="#0b1224" roughness={1} />
      </mesh>
      <Links edges={edges} at={at} lit={lit} />
      {placed.map((n) => {
        const faded = lit !== null && !lit.has(n.id);
        const color = colorOf(n);
        const bright = hover === n || selected === n.id;
        return (
          <mesh key={n.id} position={n.position} name={n.id}
            onPointerOver={(e) => {
              e.stopPropagation();
              setHover(n);
            }}
            onPointerOut={() => setHover(null)}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(selected === n.id ? null : n.id);
            }}>
            <Shape node={n} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={bright ? 0.95 : 0.35} roughness={0.35}
              transparent={faded} opacity={faded ? 0.16 : 1} />
          </mesh>
        );
      })}
      {placed
        .filter((n) => n.kind !== "invoice" && (n.kind === "rule" || n.kind === "ring" || n.kind === "approver"
          || (lit !== null && lit.size <= 30 && lit.has(n.id))))
        .map((n) => (
          <Html key={n.id} position={[n.position[0], n.position[1] + 0.5, n.position[2]]} center className={`scene-label small graph-label ${n.kind}`}>
            {n.label}
          </Html>
        ))}
      {hover && (
        <Html position={[hover.position[0], hover.position[1] + 1.2, hover.position[2]]} center className="scene-tooltip">
          <strong>{hover.label}</strong>
          {describe(hover).filter(Boolean).map((line) => (
            <span key={line}>{line}</span>
          ))}
        </Html>
      )}
    </SceneFrame>
  );
}
