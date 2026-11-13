import { useMemo, useState } from "react";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import type { GraphEdge, GraphNode } from "../api/types";
import { inr } from "../lib/format";
import { EDGE_COLORS, nodeColor } from "./graphColors";
import { graphLayout, type PlacedGraphNode } from "./layout";
import { SceneFrame } from "./SceneFrame";

const CENTRE: [number, number, number] = [0, 2, 0];
const ALWAYS_LABELLED = new Set(["version", "section", "clause", "role", "checker"]);

function describe(n: GraphNode): string[] {
  switch (n.kind) {
    case "clause":
      return [n.title ?? "", `${n.severity} · ${n.clause_kind} rule`, `${n.findings ?? 0} findings in the latest results`];
    case "parameter":
      return [`rule ${n.clause}`, `= ${typeof n.value === "object" ? JSON.stringify(n.value) : String(n.value)}`];
    case "role":
      return [`approves up to ₹${inr(n.limit ?? 0)}`];
    case "checker":
      return [n.checker_kind === "agent" ? "language-model agent" : "deterministic control"];
    case "page":
      return [`${n.document}, page ${n.page}`];
    case "version":
      return [`effective ${n.effective ?? ""}`, n.active ? "active" : "stored"];
    default:
      return [];
  }
}

function Links({ edges, at, highlight }: { edges: GraphEdge[]; at: Map<string, PlacedGraphNode>; highlight: Set<string> | null }) {
  const [bright, dim] = useMemo(() => {
    const make = (list: GraphEdge[]) => {
      const points: number[] = [];
      const colors: number[] = [];
      const tint = new THREE.Color();
      for (const e of list) {
        const a = at.get(e.source), b = at.get(e.target);
        if (!a || !b) continue;
        points.push(...a.position, ...b.position);
        tint.set(EDGE_COLORS[e.kind] ?? "#94a3b8");
        colors.push(tint.r, tint.g, tint.b, tint.r, tint.g, tint.b);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
      g.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      return g;
    };
    const lit = highlight ? edges.filter((e) => highlight.has(e.source) && highlight.has(e.target)) : edges;
    const rest = highlight ? edges.filter((e) => !(highlight.has(e.source) && highlight.has(e.target))) : [];
    return [make(lit), make(rest)];
  }, [edges, at, highlight]);
  return (
    <>
      <lineSegments geometry={bright}>
        <lineBasicMaterial vertexColors transparent opacity={0.9} />
      </lineSegments>
      <lineSegments geometry={dim}>
        <lineBasicMaterial vertexColors transparent opacity={0.12} />
      </lineSegments>
    </>
  );
}

function Shape({ node }: { node: PlacedGraphNode }) {
  switch (node.kind) {
    case "version":
      return <icosahedronGeometry args={[node.other ? 0.32 : 0.48, 0]} />;
    case "section":
      return <boxGeometry args={[0.32, 0.32, 0.32]} />;
    case "clause":
      return <sphereGeometry args={[0.27, 20, 16]} />;
    case "parameter":
      return <octahedronGeometry args={[0.2, 0]} />;
    case "role":
      return <coneGeometry args={[0.22, 0.42, 6]} />;
    case "checker":
      return <dodecahedronGeometry args={[0.24, 0]} />;
    default:
      return <boxGeometry args={[0.34, 0.44, 0.06]} />;
  }
}

/** The policy as a graph in 3D: rules around their version, with what they set, what checks them and where they are written. */
export function PolicyGraph3D({ nodes, edges, highlight, selected, onSelect }: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  highlight: Set<string> | null;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const [hover, setHover] = useState<PlacedGraphNode | null>(null);
  const placed = useMemo(() => graphLayout(nodes, edges), [nodes, edges]);
  const at = useMemo(() => new Map(placed.map((n) => [n.id, n])), [placed]);
  const focus = highlight ?? (selected ? new Set([selected, ...edges.filter((e) => e.source === selected || e.target === selected).flatMap((e) => [e.source, e.target])]) : null);
  return (
    <SceneFrame label={`Policy knowledge graph: ${nodes.length} nodes and ${edges.length} relations`} height={540} camera={[0, 10, 15]} target={CENTRE}
      autoRotate={!focus}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.3, 0]} onClick={() => onSelect(null)}>
        <circleGeometry args={[11, 72]} />
        <meshStandardMaterial color="#0b1224" roughness={1} />
      </mesh>
      <Links edges={edges} at={at} highlight={focus} />
      {placed.map((n) => {
        const faded = focus !== null && !focus.has(n.id);
        const color = nodeColor(n);
        const lit = hover === n || selected === n.id;
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
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={lit ? 0.95 : 0.35} roughness={0.35}
              transparent={faded} opacity={faded ? 0.18 : 1} />
          </mesh>
        );
      })}
      {placed
        .filter((n) => (ALWAYS_LABELLED.has(n.kind) && (!focus || focus.has(n.id))) || (focus?.has(n.id) && n.kind !== "page"))
        .map((n) => (
          <Html key={n.id} position={[n.position[0], n.position[1] + 0.45, n.position[2]]} center className={`scene-label small graph-label ${n.kind}`}>
            {n.kind === "checker" ? n.label.replace(" in controls.py", "").replace("the ", "") : n.label}
          </Html>
        ))}
      {hover && (
        <Html position={[hover.position[0], hover.position[1] + 1.2, hover.position[2]]} center className="scene-tooltip">
          <strong>{hover.kind === "clause" ? `Rule ${hover.label}` : hover.label}</strong>
          {describe(hover).map((line) => (
            <span key={line}>{line}</span>
          ))}
        </Html>
      )}
    </SceneFrame>
  );
}
