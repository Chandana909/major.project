// Geometry of the 3D views, kept apart from the components so that it can be tested without WebGL.
import type { Stage, VendorPoint } from "../api/types";

export interface PlacedVendor extends VendorPoint {
  position: [number, number, number];
  size: number;
}

/** Is WebGL available in this browser? (Not in tests, nor in some locked-down browsers.) */
export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

/**
 * Place vendors in the scene: one sector per spending category around a circle;
 * within a sector, larger vendors sit further out; height is the highest risk
 * score among the vendor's latest results.
 */
export function layoutVendors(vendors: VendorPoint[]): { placed: PlacedVendor[]; categories: { name: string; angle: number }[] } {
  const names = [...new Set(vendors.map((v) => v.category))].sort();
  const sector = (Math.PI * 2) / Math.max(names.length, 1);
  // Points are drawn for a ledger of up to 250 vendors; beyond that they shrink so that the area they cover stays
  // about the same (15,000 vendors would otherwise merge into one surface).
  const density = Math.min(1, Math.sqrt(250 / Math.max(vendors.length, 1)));
  const placed: PlacedVendor[] = [];
  names.forEach((name, c) => {
    const members = vendors
      .filter((v) => v.category === name)
      .sort((a, b) => a.invoices - b.invoices || a.vendor_id.localeCompare(b.vendor_id));
    members.forEach((v, i) => {
      const t = members.length > 1 ? i / (members.length - 1) : 0.5;
      // A deterministic spread inside the sector (golden-ratio jitter), so the layout is stable between visits.
      const angle = c * sector + sector * (0.12 + 0.76 * ((i * 0.618034) % 1));
      const radius = 2.2 + t * 7.5;
      const height = 0.15 + (v.max_risk / 100) * 4.2;
      placed.push({
        ...v,
        position: [Math.cos(angle) * radius, height, Math.sin(angle) * radius],
        size: (0.035 + 0.024 * Math.log2(1 + v.invoices)) * density,
      });
    });
  });
  return { placed, categories: names.map((name, c) => ({ name, angle: c * sector + sector / 2 })) };
}

/** Where each stage stands: the pipeline runs left to right, the agents side by side in depth. */
export function stagePositions(stages: Stage[]): Record<string, [number, number, number]> {
  const columns: Record<string, [number, number]> = {
    extraction: [0, 0], controls: [1, 0],
    math_approvals: [2, -1.4], tax_identity: [2, 0], vendor_intelligence: [2, 1.4], single_auditor: [2, 2.8],
    challenger: [3, 0], confidence: [4, 0], risk_score: [5, 0], human_review: [6, 0], audit_pack: [7, 0],
  };
  const out: Record<string, [number, number, number]> = {};
  stages.forEach((s, i) => {
    const [column, depth] = columns[s.id] ?? [i, 0];
    out[s.id] = [(column - 3.5) * 3.1, 0.6, depth * 1.9 - 0.95];
  });
  return out;
}

/** The edges between consecutive stages of a configuration; the three specialist agents run in parallel. */
export function stageEdges(active: string[]): [string, string][] {
  const parallel = new Set(["math_approvals", "tax_identity", "vendor_intelligence"]);
  const layers: string[][] = [];
  for (const id of active) {
    const last = layers[layers.length - 1];
    if (last && parallel.has(id) && parallel.has(last[0])) last.push(id);
    else layers.push([id]);
  }
  const edges: [string, string][] = [];
  for (let i = 0; i + 1 < layers.length; i++) {
    for (const a of layers[i]) for (const b of layers[i + 1]) edges.push([a, b]);
  }
  return edges;
}

export interface Bar {
  label: string;
  value: number; // share of invoices decided against the policy in force, 0..1
  count: number;
}

/** Bars along an arc, from the smallest to the largest. */
export function barLayout(bars: Bar[]): { bar: Bar; position: [number, number, number]; height: number }[] {
  const sorted = [...bars].sort((a, b) => a.value - b.value);
  const max = Math.max(...sorted.map((b) => b.value), 1e-9);
  const n = sorted.length;
  return sorted.map((bar, i) => {
    const angle = Math.PI * (0.15 + 0.7 * (n > 1 ? i / (n - 1) : 0.5));
    const height = 0.08 + (bar.value / max) * 6;
    return { bar, position: [Math.cos(angle) * -8, height / 2, Math.sin(angle) * -4.5], height };
  });
}
