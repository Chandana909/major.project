import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html, RoundedBox } from "@react-three/drei";
import * as THREE from "three";
import type { Stage } from "../api/types";
import { stageEdges, stagePositions } from "./layout";
import { SceneFrame } from "./SceneFrame";

const KIND_COLOR: Record<Stage["kind"], string> = { code: "#2dd4bf", llm: "#a78bfa", person: "#fbbf24" };
// The agents stand side by side in depth; their labels go beside them instead of above or below.
const AGENTS = new Set(["math_approvals", "tax_identity", "vendor_intelligence", "single_auditor"]);

function Flow({ from, to, speed = 0.45, offset = 0 }: { from: THREE.Vector3; to: THREE.Vector3; speed?: number; offset?: number }) {
  const curve = useMemo(() => {
    const mid = from.clone().lerp(to, 0.5).add(new THREE.Vector3(0, 0.9, 0));
    return new THREE.QuadraticBezierCurve3(from, mid, to);
  }, [from, to]);
  const points = useMemo(() => curve.getPoints(32), [curve]);
  const geometry = useMemo(() => new THREE.BufferGeometry().setFromPoints(points), [points]);
  const dots = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    dots.current?.children.forEach((dot, i) => {
      const t = (clock.elapsedTime * speed + offset + i / 3) % 1;
      dot.position.copy(curve.getPoint(t));
    });
  });
  return (
    <group>
      <primitive object={new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: "#334155", transparent: true, opacity: 0.9 }))} />
      <group ref={dots}>
        {[0, 1, 2].map((i) => (
          <mesh key={i}>
            <sphereGeometry args={[0.06, 10, 10]} />
            <meshBasicMaterial color="#5eead4" toneMapped={false} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

function StageNode({ stage, position, active }: { stage: Stage; position: [number, number, number]; active: boolean }) {
  const ring = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (ring.current) {
      ring.current.rotation.z = clock.elapsedTime * 0.8;
      const s = 1 + 0.08 * Math.sin(clock.elapsedTime * 2.5);
      ring.current.scale.set(s, s, s);
    }
  });
  const color = KIND_COLOR[stage.kind];
  return (
    <group position={position} name={`stage-${stage.id}`}>
      <RoundedBox args={[1.5, 0.75, 0.75]} radius={0.14} smoothness={4}>
        <meshStandardMaterial
          color={color}
          transparent
          opacity={active ? 0.95 : 0.12}
          emissive={color}
          emissiveIntensity={active ? 0.35 : 0.02}
          roughness={0.3}
          metalness={0.1}
        />
      </RoundedBox>
      {stage.feature && active && (
        <mesh ref={ring} rotation={[Math.PI / 2, 0, 0]} position={[0, -0.45, 0]}>
          <torusGeometry args={[1.05, 0.03, 8, 64]} />
          <meshBasicMaterial color="#5eead4" toneMapped={false} />
        </mesh>
      )}
    </group>
  );
}

/** The stages and the flow between those a configuration runs. */
export function PipelineGraph({ stages, active }: { stages: Stage[]; active: string[] }) {
  const positions = useMemo(() => stagePositions(stages), [stages]);
  const edges = useMemo(() => stageEdges(active), [active]);
  const on = useMemo(() => new Set(active), [active]);
  return (
    <group>
      {stages.map((s) => (
        <StageNode key={s.id} stage={s} position={positions[s.id]} active={on.has(s.id)} />
      ))}
      {edges.map(([a, b], i) => (
        <Flow key={`${a}-${b}`} from={new THREE.Vector3(...positions[a])} to={new THREE.Vector3(...positions[b])} offset={i * 0.13} />
      ))}
    </group>
  );
}

export function PipelineScene({ stages, active }: { stages: Stage[]; active: string[] }) {
  const positions = useMemo(() => stagePositions(stages), [stages]);
  const on = new Set(active);
  return (
    <SceneFrame label="The audit pipeline in 3D" height={470} camera={[0, 6.8, 11.8]} autoRotate={false}>
      <gridHelper args={[24, 24, "#1e293b", "#111a2e"]} position={[0, -0.2, 0]} />
      <PipelineGraph stages={stages} active={active} />
      {stages.map((s, i) => (
        <Html key={s.id} position={AGENTS.has(s.id) ? [positions[s.id][0] + 1.55, positions[s.id][1], positions[s.id][2]] : [positions[s.id][0], positions[s.id][1] + (i % 2 ? -0.95 : 0.8), positions[s.id][2]]} center
              className={`scene-label stage ${on.has(s.id) ? "" : "muted"}`}>
          {s.label}
        </Html>
      ))}
    </SceneFrame>
  );
}
