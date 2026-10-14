import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import type { VendorPoint } from "../api/types";
import { count, riskColor, rupeesCompact } from "../lib/format";
import { layoutVendors, type PlacedVendor } from "./layout";
import { SceneFrame } from "./SceneFrame";

const dummy = new THREE.Object3D();
const tint = new THREE.Color();

/** The vendor field: one instanced sphere per vendor and a stem for each vendor with invoices waiting for review. */
export function VendorField({ placed, onHover, onSelect }: {
  placed: PlacedVendor[];
  onHover?: (vendor: PlacedVendor | null) => void;
  onSelect?: (vendor: PlacedVendor) => void;
}) {
  const spheres = useRef<THREE.InstancedMesh>(null);
  const stems = useRef<THREE.InstancedMesh>(null);
  const waiting = useMemo(() => placed.filter((v) => v.waiting > 0), [placed]);

  useLayoutEffect(() => {
    const mesh = spheres.current;
    if (!mesh) return;
    placed.forEach((v, i) => {
      dummy.position.set(...v.position);
      dummy.scale.setScalar(v.size);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      mesh.setColorAt(i, tint.set(v.blacklisted ? "#a78bfa" : riskColor(v.max_risk)));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    (mesh.material as THREE.Material).needsUpdate = true;     // compile the shader with per-instance colours
    const stemMesh = stems.current;
    if (stemMesh) {
      waiting.forEach((v, i) => {
        dummy.position.set(v.position[0], v.position[1] / 2, v.position[2]);
        dummy.scale.set(1, v.position[1], 1);
        dummy.updateMatrix();
        stemMesh.setMatrixAt(i, dummy.matrix);
      });
      stemMesh.instanceMatrix.needsUpdate = true;
    }
  }, [placed, waiting]);

  // Vendors with invoices waiting for review pulse gently.
  useFrame(({ clock }) => {
    const mesh = spheres.current;
    if (!mesh) return;
    const pulse = 1 + 0.18 * Math.sin(clock.elapsedTime * 3);
    placed.forEach((v, i) => {
      if (!v.waiting) return;
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
        name="vendors"
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

function Floor() {
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

/** Every vendor of the ledger as a point in 3D. */
export function RiskConstellation({ vendors, onSelect }: { vendors: VendorPoint[]; onSelect?: (v: VendorPoint) => void }) {
  const { placed, categories } = useMemo(() => layoutVendors(vendors), [vendors]);
  const [hover, setHover] = useState<PlacedVendor | null>(null);
  return (
    <SceneFrame label={`Risk constellation of ${vendors.length} vendors`} height={460} camera={[0, 9, 17]}>
      <Floor />
      <VendorField placed={placed} onHover={setHover} onSelect={onSelect} />
      {categories.map((c) => (
        <Html key={c.name} position={[Math.cos(c.angle) * 11.6, 0.2, Math.sin(c.angle) * 11.6]} center className="scene-label">
          {c.name}
        </Html>
      ))}
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
