import { useMemo, useState } from "react";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import { barLayout, type Bar } from "./layout";
import { SceneFrame } from "./SceneFrame";

export type { Bar };

export function BarField({ bars, onHover }: { bars: Bar[]; onHover?: (b: Bar | null) => void }) {
  const placed = useMemo(() => barLayout(bars), [bars]);
  return (
    <group>
      {placed.map(({ bar, position, height }) => {
        const heat = Math.min(1, bar.value / 0.3);
        const color = new THREE.Color("#2dd4bf").lerp(new THREE.Color("#f87171"), heat);
        return (
          <mesh
            key={bar.label}
            position={position}
            name={`bar-${bar.label}`}
            onPointerOver={(e) => {
              e.stopPropagation();
              onHover?.(bar);
            }}
            onPointerOut={() => onHover?.(null)}
          >
            <boxGeometry args={[0.7, height, 0.7]} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.3} roughness={0.35} />
          </mesh>
        );
      })}
    </group>
  );
}

/** Fourteen policy changes: the share of invoices a system with frozen thresholds decides against the policy in force. */
export function PolicyBars({ bars }: { bars: Bar[] }) {
  const [hover, setHover] = useState<Bar | null>(null);
  const placed = useMemo(() => barLayout(bars), [bars]);
  return (
    <SceneFrame label="Cost of frozen thresholds under fourteen policy changes" height={420} camera={[0, 6, 11]} autoRotate={false}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, -2]}>
        <planeGeometry args={[26, 16]} />
        <meshStandardMaterial color="#0b1224" roughness={1} />
      </mesh>
      <BarField bars={bars} onHover={setHover} />
      {placed.map(({ bar, position, height }) => (
        <Html key={bar.label} position={[position[0], height + 0.45, position[2]]} center className="scene-label small">
          {(bar.value * 100).toFixed(1)}%
        </Html>
      ))}
      {hover && (
        <Html position={[0, 7.4, -3]} center className="scene-tooltip">
          <strong>{hover.label}</strong>
          <span>{(hover.value * 100).toFixed(1)}% of invoices · {hover.count.toLocaleString("en-IN")} decided against the policy</span>
        </Html>
      )}
    </SceneFrame>
  );
}
