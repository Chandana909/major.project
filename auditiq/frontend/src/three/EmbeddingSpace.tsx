import { useMemo, useState } from "react";
import { Html, Line } from "@react-three/drei";
import { SceneFrame } from "./SceneFrame";

export interface SpacePoint {
  id: number;
  /** The first three principal components of the passage's embedding, scaled to [-1, 1]. */
  point: [number, number, number];
  color: string;
  label: string;
  detail?: string;
}

const SCALE = 5;
const CENTRE: [number, number, number] = [0, 0, 0];

function at(p: [number, number, number]): [number, number, number] {
  return [p[0] * SCALE, p[1] * SCALE, p[2] * SCALE];
}

/** Passages in the embedding space (three principal components), with an optional question and its links to the passages it retrieved. */
export function EmbeddingSpace({ points, query, linked = [], label, explained = [] }: {
  points: SpacePoint[];
  query?: [number, number, number] | null;
  linked?: number[];
  label: string;
  explained?: number[];
}) {
  const [hover, setHover] = useState<SpacePoint | null>(null);
  const linkedSet = useMemo(() => new Set(linked), [linked]);
  const axis = (i: number) => `PC${i + 1}${explained[i] !== undefined ? ` · ${(explained[i] * 100).toFixed(0)}%` : ""}`;
  return (
    <SceneFrame label={label} height={460} camera={[8, 6, 11]} target={CENTRE} autoRotate={!query}>
      {[0, 1, 2].map((i) => {
        const end: [number, number, number] = [0, 0, 0];
        end[i] = SCALE * 1.15;
        const start: [number, number, number] = [0, 0, 0];
        start[i] = -SCALE * 1.15;
        return (
          <group key={i}>
            <Line points={[start, end]} color="#334155" lineWidth={1} />
            <Html position={end} center className="scene-label small">
              {axis(i)}
            </Html>
          </group>
        );
      })}
      {points.map((p) => {
        const on = linkedSet.has(p.id);
        return (
          <mesh key={p.id} position={at(p.point)}
            onPointerOver={(e) => {
              e.stopPropagation();
              setHover(p);
            }}
            onPointerOut={() => setHover(null)}>
            <sphereGeometry args={[on ? 0.22 : 0.14, 18, 14]} />
            <meshStandardMaterial color={p.color} emissive={p.color} emissiveIntensity={on || hover === p ? 0.9 : 0.35}
              transparent={Boolean(query) && !on} opacity={query && !on ? 0.4 : 1} />
          </mesh>
        );
      })}
      {query && (
        <group>
          <mesh position={at(query)}>
            <octahedronGeometry args={[0.32, 0]} />
            <meshStandardMaterial color="#fbbf24" emissive="#fbbf24" emissiveIntensity={1} />
          </mesh>
          <Html position={[query[0] * SCALE, query[1] * SCALE + 0.6, query[2] * SCALE]} center className="scene-label">
            question
          </Html>
          {points
            .filter((p) => linkedSet.has(p.id))
            .map((p) => (
              <Line key={p.id} points={[at(query), at(p.point)]} color="#fbbf24" lineWidth={1.4} transparent opacity={0.75} />
            ))}
        </group>
      )}
      {points
        .filter((p) => linkedSet.has(p.id))
        .map((p) => (
          <Html key={`l${p.id}`} position={[p.point[0] * SCALE, p.point[1] * SCALE + 0.45, p.point[2] * SCALE]} center className="scene-label small">
            {p.label}
          </Html>
        ))}
      {hover && (
        <Html position={[hover.point[0] * SCALE, hover.point[1] * SCALE + 1.1, hover.point[2] * SCALE]} center className="scene-tooltip">
          <strong>{hover.label}</strong>
          {hover.detail && <span>{hover.detail}</span>}
        </Html>
      )}
    </SceneFrame>
  );
}
