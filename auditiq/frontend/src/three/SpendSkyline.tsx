import { useMemo, useState } from "react";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import type { Analytics } from "../api/types";
import { rupeesCompact } from "../lib/format";
import { skylineLayout, SKYLINE_STEP, type SkylineBar } from "./layout";
import { SceneFrame } from "./SceneFrame";

const LOW = new THREE.Color("#115e59");
const HIGH = new THREE.Color("#5eead4");
const PEAK = new THREE.Color("#fbbf24");
const CENTRE: [number, number, number] = [0, 1.2, 0];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function barColor(heat: number): THREE.Color {
  return heat > 0.85 ? LOW.clone().lerp(PEAK, heat) : LOW.clone().lerp(HIGH, heat);
}

/** Spend by vendor category (rows) and month (columns) as a city of bars: the tall ones are where the money went. */
export function SpendSkyline({ skyline }: { skyline: Analytics["skyline"] }) {
  const [hover, setHover] = useState<SkylineBar | null>(null);
  const bars = useMemo(() => skylineLayout(skyline), [skyline]);
  const width = skyline.months.length * SKYLINE_STEP.month;
  const depth = skyline.categories.length * SKYLINE_STEP.category;
  const front = depth / 2 + 0.5;
  return (
    <SceneFrame label={`Spend by category and month: ${skyline.categories.length} categories over ${skyline.months.length} months`} height={420}
      camera={[width * 0.55, 7.5, depth * 0.9 + 6]} target={CENTRE} autoRotate={false}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]}>
        <planeGeometry args={[width + 3, depth + 3]} />
        <meshStandardMaterial color="#0b1224" roughness={1} />
      </mesh>
      <gridHelper args={[Math.max(width, depth) + 3, Math.round(Math.max(width, depth) + 3), "#1e293b", "#111a2e"]} position={[0, 0.001, 0]} />
      {bars.map((b) => {
        const color = barColor(b.heat);
        const hot = hover === b;
        return (
          <mesh key={`${b.category}-${b.month}`} position={b.position}
            onPointerOver={(e) => {
              e.stopPropagation();
              setHover(b);
            }}
            onPointerOut={() => setHover(null)}>
            <boxGeometry args={[SKYLINE_STEP.month * 0.7, b.height, SKYLINE_STEP.category * 0.62]} />
            <meshStandardMaterial color={hot ? "#ffffff" : color} emissive={color} emissiveIntensity={hot ? 0.8 : 0.32} roughness={0.4} metalness={0.1} />
          </mesh>
        );
      })}
      {skyline.categories.map((c, i) => (
        <Html key={c} position={[-width / 2 - 0.4, 0.1, -depth / 2 + (i + 0.5) * SKYLINE_STEP.category]} center className="scene-label small side-label">
          {c}
        </Html>
      ))}
      {skyline.months.map((m, i) =>
        i % Math.max(1, Math.ceil(skyline.months.length / 8)) === 0 ? (
          <Html key={m} position={[-width / 2 + (i + 0.5) * SKYLINE_STEP.month, 0.1, front]} center className="scene-label small">
            {MONTHS[Number(m.slice(5, 7)) - 1]} {m.slice(2, 4)}
          </Html>
        ) : null,
      )}
      {hover && (
        <Html position={[hover.position[0], hover.height + 0.7, hover.position[2]]} center className="scene-tooltip">
          <strong>{hover.category}</strong>
          <span>
            {MONTHS[Number(hover.month.slice(5, 7)) - 1]} {hover.month.slice(0, 4)} · {rupeesCompact(hover.amount)}
          </span>
        </Html>
      )}
    </SceneFrame>
  );
}
