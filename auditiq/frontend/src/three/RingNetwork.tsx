import { useMemo, useState } from "react";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import type { RingEdge, RingNode } from "../api/types";
import { BLACKLISTED_COLOR, count, inr, riskColor, rupeesCompact } from "../lib/format";
import { networkLayout, type PlacedNode } from "./layout";
import { linkColor } from "./linkColors";
import { SceneFrame } from "./SceneFrame";

const APPROVER_COLOR = "#e2e8f0";
const CENTRE: [number, number, number] = [0, 1.6, 0];

function Links({ edges, at, dim }: { edges: RingEdge[]; at: Map<string, PlacedNode>; dim: boolean }) {
  const geometry = useMemo(() => {
    const points: number[] = [];
    const colors: number[] = [];
    const tint = new THREE.Color();
    for (const e of edges) {
      const a = at.get(e.source), b = at.get(e.target);
      if (!a || !b) continue;
      points.push(...a.position, ...b.position);
      tint.set(linkColor(e.kinds));
      colors.push(tint.r, tint.g, tint.b, tint.r, tint.g, tint.b);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    return g;
  }, [edges, at]);
  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial vertexColors transparent opacity={dim ? 0.16 : 0.95} />
    </lineSegments>
  );
}

/** Vendors (spheres, coloured by their highest risk) and approvers (diamonds) of every ring, joined by their links. */
export function RingNetwork({ nodes, edges, selected, onSelect }: {
  nodes: RingNode[];
  edges: RingEdge[];
  selected: number | null;
  onSelect: (ring: number | null) => void;
}) {
  const [hover, setHover] = useState<PlacedNode | null>(null);
  const { placed, centres } = useMemo(() => networkLayout(nodes, edges), [nodes, edges]);
  const at = useMemo(() => new Map(placed.map((n) => [n.id, n])), [placed]);
  const maxAmount = useMemo(() => Math.max(1, ...placed.map((n) => n.amount ?? 0)), [placed]);
  const focus = selected === null ? edges : edges.filter((e) => e.ring === selected);
  const rest = selected === null ? [] : edges.filter((e) => e.ring !== selected);
  const rings = Object.keys(centres).map(Number);
  return (
    <SceneFrame label={`Collusion network: ${rings.length} rings, ${placed.length} vendors and approvers`} height={520} camera={[0, 9, 17]} target={CENTRE} autoRotate={selected === null}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]} onClick={() => onSelect(null)}>
        <circleGeometry args={[Math.max(9, 2.2 * Math.sqrt(rings.length) + 3), 72]} />
        <meshStandardMaterial color="#0b1224" roughness={1} />
      </mesh>
      <Links edges={focus} at={at} dim={false} />
      {rest.length > 0 && <Links edges={rest} at={at} dim />}
      {placed.map((n) => {
        const faded = selected !== null && n.ring !== selected;
        const vendor = n.kind === "vendor";
        const color = vendor ? (n.blacklisted ? BLACKLISTED_COLOR : riskColor(n.max_risk ?? 0)) : APPROVER_COLOR;
        const size = vendor ? 0.13 + 0.2 * Math.sqrt((n.amount ?? 0) / maxAmount) : 0.2;
        return (
          <mesh key={n.id} position={n.position} name={n.id}
            onPointerOver={(e) => {
              e.stopPropagation();
              setHover(n);
            }}
            onPointerOut={() => setHover(null)}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(n.ring);
            }}>
            {vendor ? <sphereGeometry args={[size, 20, 16]} /> : <octahedronGeometry args={[size, 0]} />}
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={hover === n ? 0.9 : 0.35} roughness={0.35}
              transparent={faded} opacity={faded ? 0.22 : 1} />
          </mesh>
        );
      })}
      {selected === null
        ? rings.slice(0, 16).map((r) => (
            <Html key={r} position={[centres[r][0], centres[r][1] + 1.25, centres[r][2]]} center className="scene-label small">
              R{r}
            </Html>
          ))
        : placed
            .filter((n) => n.ring === selected)
            .map((n) => (
              <Html key={n.id} position={[n.position[0], n.position[1] + 0.42, n.position[2]]} center className={`scene-label small ${n.kind === "approver" ? "approver" : ""}`}>
                {n.kind === "approver" ? `${n.label} (${n.role ?? "approver"})` : n.label}
              </Html>
            ))}
      {hover && (
        <Html position={[hover.position[0], hover.position[1] + 1.1, hover.position[2]]} center className="scene-tooltip">
          <strong>{hover.label}</strong>
          {hover.kind === "vendor" ? (
            <>
              <span>{hover.vendor_id} · {hover.category} · ring R{hover.ring}</span>
              <span>{count(hover.invoices ?? 0)} invoices · {rupeesCompact(hover.amount ?? 0)} · {count(hover.flagged ?? 0)} with findings</span>
              <span>
                highest risk {(hover.max_risk ?? 0).toFixed(0)}
                {hover.top_approver_share != null && ` · top approver ${(hover.top_approver_share * 100).toFixed(0)}% of its invoices`}
                {hover.blacklisted && " · blacklisted"}
              </span>
            </>
          ) : (
            <span>
              {hover.role ?? "approver"}
              {hover.limit != null && ` · limit ₹${inr(hover.limit)}`} · ring R{hover.ring}
            </span>
          )}
        </Html>
      )}
    </SceneFrame>
  );
}
