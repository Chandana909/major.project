import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import type { VendorPoint } from "../api/types";
import { BLACKLISTED_COLOR, count, riskColor, rupeesCompact } from "../lib/format";
import { layoutVendors, type Placed, type PlacedVendor, type Sector } from "./layout";
import { SceneFrame } from "./SceneFrame";

const dummy = new THREE.Object3D();
const tint = new THREE.Color();

/** A point of a constellation: its colour, whether a stem joins it to the floor, whether it pulses. */
export type FieldPoint = Placed & { color: string; stem: boolean; pulse: boolean };

/** One instanced sphere per point, a stem for each point that asks for one, and a gentle pulse where asked. */
export function PointField<T extends FieldPoint>({ points, name, onHover, onSelect }: {
  points: T[];
  name: string;
  onHover?: (point: T | null) => void;
  onSelect?: (point: T) => void;
}) {
  const placed = points;
  const spheres = useRef<THREE.InstancedMesh>(null);
  const stems = useRef<THREE.InstancedMesh>(null);
  const waiting = useMemo(() => placed.filter((v) => v.stem), [placed]);

  useLayoutEffect(() => {
    const mesh = spheres.current;
    if (!mesh) return;
    placed.forEach((v, i) => {
      dummy.position.set(...v.position);
      dummy.scale.setScalar(v.size);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      mesh.setColorAt(i, tint.set(v.color));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    (mesh.material as THREE.Material).needsUpdate = true;     // compile the shader with per-instance colours
    const stemMesh = stems.current;
    if (stemMesh) {
      const width = Math.min(1, Math.sqrt(250 / Math.max(placed.length, 1)));     // thinner as the field fills
      waiting.forEach((v, i) => {
        dummy.position.set(v.position[0], v.position[1] / 2, v.position[2]);
        dummy.scale.set(width, v.position[1], width);
        dummy.updateMatrix();
        stemMesh.setMatrixAt(i, dummy.matrix);
      });
      stemMesh.instanceMatrix.needsUpdate = true;
    }
  }, [placed, waiting]);

  useFrame(({ clock }) => {
    const mesh = spheres.current;
    if (!mesh) return;
    const pulse = 1 + 0.18 * Math.sin(clock.elapsedTime * 3);
    placed.forEach((v, i) => {
      if (!v.pulse) return;
      dummy.position.set(...v.position);
      dummy.scale.setScalar(v.size * pulse);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  });

  const pick = (event: ThreeEvent<PointerEvent | MouseEvent>) =>
    event.instanceId === undefined ? null : placed[event.instanceId] ?? null;

  return (
    <group>
      <instancedMesh
        ref={spheres}
        args={[undefined, undefined, Math.max(placed.length, 1)]}
        name={name}
        onPointerMove={(e) => {
          e.stopPropagation();
          onHover?.(pick(e));
        }}
        onPointerOut={() => onHover?.(null)}
        onClick={(e) => {
          e.stopPropagation();
          const v = pick(e);
          if (v) onSelect?.(v);
        }}
      >
        <sphereGeometry args={[1, 18, 18]} />
        {/* Unlit, so that each vendor shows the pure colour of its risk level. */}
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
      <instancedMesh ref={stems} args={[undefined, undefined, Math.max(waiting.length, 1)]} name="stems" visible={waiting.length > 0}>
        <cylinderGeometry args={[0.012, 0.012, 1, 6]} />
        <meshBasicMaterial color="#fb923c" transparent opacity={0.45} />
      </instancedMesh>
    </group>
  );
}

/** The vendor field: a vendor with invoices waiting for review has a stem and pulses; blacklisted ones are violet. */
export function VendorField({ placed, onHover, onSelect }: {
  placed: PlacedVendor[];
  onHover?: (vendor: (PlacedVendor & FieldPoint) | null) => void;
  onSelect?: (vendor: PlacedVendor & FieldPoint) => void;
}) {
  const points = useMemo(
    () => placed.map((v) => ({ ...v, color: v.blacklisted ? BLACKLISTED_COLOR : riskColor(v.max_risk), stem: v.waiting > 0, pulse: v.waiting > 0 })),
    [placed],
  );
  return <PointField points={points} name="vendors" onHover={onHover} onSelect={onSelect} />;
}

export function Floor() {
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]}>
        <circleGeometry args={[11, 72]} />
        <meshStandardMaterial color="#0b1224" roughness={1} />
      </mesh>
      <polarGridHelper args={[10.5, 6, 8, 72, "#1e293b", "#172033"]} />
    </group>
  );
}

/** The name of each sector, just outside the floor. */
export function SectorLabels({ sectors, label = (s) => s.name }: { sectors: Sector[]; label?: (s: Sector) => ReactNode }) {
  return (
    <>
      {sectors.map((s) => (
        <Html key={s.name} position={[Math.cos(s.angle) * 11.6, 0.2, Math.sin(s.angle) * 11.6]} center className="scene-label">
          {label(s)}
        </Html>
      ))}
    </>
  );
}

/** Every vendor of the ledger as a point in 3D. */
export function RiskConstellation({ vendors, onSelect }: { vendors: VendorPoint[]; onSelect?: (v: VendorPoint) => void }) {
  const { placed, categories } = useMemo(() => layoutVendors(vendors), [vendors]);
  const [hover, setHover] = useState<PlacedVendor | null>(null);
  return (
    <SceneFrame label={`Risk constellation of ${vendors.length} vendors`} height={460} camera={[0, 9, 17]}>
      <Floor />
      <VendorField placed={placed} onHover={setHover} onSelect={onSelect} />
      <SectorLabels sectors={categories} />
      {hover && (
        <Html position={hover.position} center distanceFactor={14} className="scene-tooltip" zIndexRange={[20, 0]}>
          <strong>{hover.vendor_name}</strong>
          <span>{hover.category}</span>
          <span>{count(hover.invoices)} invoices · {rupeesCompact(hover.amount)}</span>
          <span>Highest risk {hover.max_risk.toFixed(0)} · {count(hover.findings)} findings</span>
          {hover.waiting > 0 && <span className="warn">{hover.waiting} waiting for review</span>}
          {hover.blacklisted ? <span className="warn">Blacklisted</span> : null}
        </Html>
      )}
    </SceneFrame>
  );
}
