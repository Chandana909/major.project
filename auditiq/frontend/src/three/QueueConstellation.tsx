import { useMemo, useState } from "react";
import { Html } from "@react-three/drei";
import type { QueueItem } from "../api/types";
import { inr, riskColor, routeLabel } from "../lib/format";
import { layoutQueue } from "./layout";
import { Floor, PointField, SectorLabels } from "./RiskConstellation";
import { SceneFrame } from "./SceneFrame";

/** The invoices waiting for review as a constellation: a sector per rule broken; the riskiest pulse. */
export function QueueConstellation({ items, rules, onSelect }: {
  items: QueueItem[];
  rules: Record<string, string | null>;
  onSelect?: (item: QueueItem) => void;
}) {
  const { placed, sectors } = useMemo(() => layoutQueue(items), [items]);
  const points = useMemo(() => placed.map((p) => ({ ...p, color: riskColor(p.rc), stem: true, pulse: p.rc >= 70 })), [placed]);
  const [hover, setHover] = useState<(typeof points)[number] | null>(null);
  const title = (rule: string) => (rules[rule] ? `${rule} ${rules[rule]}` : rule);
  return (
    <SceneFrame label={`Constellation of ${items.length} invoices waiting for review`} height={460} camera={[0, 9, 17]}>
      <Floor />
      <PointField points={points} name="invoices" onHover={setHover} onSelect={onSelect} />
      <SectorLabels
        sectors={sectors}
        label={(s) => (
          <>
            {s.name}
            {rules[s.name] && <small>{rules[s.name]}</small>}
          </>
        )}
      />
      {hover && (
        <Html position={hover.position} center distanceFactor={14} className="scene-tooltip" zIndexRange={[20, 0]}>
          <strong>{hover.invoice_id}</strong>
          <span>{hover.vendor_name}</span>
          <span>
            ₹{inr(hover.amount)} · weighted risk {hover.rc.toFixed(0)}
          </span>
          {hover.rules.map((r) => (
            <span key={r}>Rule {title(r)}</span>
          ))}
          <span className="warn">{routeLabel(hover.route)} · click to open</span>
        </Html>
      )}
    </SceneFrame>
  );
}
