// Geometry of the 3D views, kept apart from the components so that it can be tested without WebGL.
import type { Analytics, GraphEdge, GraphNode, QueueItem, RingEdge, RingNode, Stage, VendorPoint } from "../api/types";

export interface Placed {
  position: [number, number, number];
  size: number;
}

export type PlacedVendor = VendorPoint & Placed;
export type PlacedInvoice = QueueItem & Placed;
export type Sector = { name: string; angle: number };

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
 * Place points in a constellation: one sector per group around a circle; within a sector, heavier points sit
 * further out; height is the risk score from 0 to 100.
 */
function placeInSectors<T>(items: T[], how: {
  group: (t: T) => string;
  weight: (t: T) => number;
  id: (t: T) => string;
  risk: (t: T) => number;
  size: (t: T) => number;
}): { placed: (T & Placed)[]; sectors: Sector[] } {
  const names = [...new Set(items.map(how.group))].sort();
  const sector = (Math.PI * 2) / Math.max(names.length, 1);
  // Points are drawn for up to 250 of them; beyond that they shrink so that the area they cover stays about the
  // same (15,000 vendors would otherwise merge into one surface).
  const density = Math.min(1, Math.sqrt(250 / Math.max(items.length, 1)));
  const placed: (T & Placed)[] = [];
  names.forEach((name, c) => {
    const members = items
      .filter((t) => how.group(t) === name)
      .sort((a, b) => how.weight(a) - how.weight(b) || how.id(a).localeCompare(how.id(b)));
    members.forEach((t, i) => {
      const f = members.length > 1 ? i / (members.length - 1) : 0.5;
      // A deterministic spread inside the sector (golden-ratio jitter), so the layout is stable between visits.
      const angle = c * sector + sector * (0.12 + 0.76 * ((i * 0.618034) % 1));
      const radius = 2.2 + f * 7.5;
      const height = 0.15 + (how.risk(t) / 100) * 4.2;
      placed.push({ ...t, position: [Math.cos(angle) * radius, height, Math.sin(angle) * radius], size: how.size(t) * density });
    });
  });
  return { placed, sectors: names.map((name, c) => ({ name, angle: c * sector + sector / 2 })) };
}

/** The vendors: one sector per spending category, height the highest risk among the vendor's latest results. */
export function layoutVendors(vendors: VendorPoint[]): { placed: PlacedVendor[]; categories: Sector[] } {
  const { placed, sectors } = placeInSectors(vendors, {
    group: (v) => v.category,
    weight: (v) => v.invoices,
    id: (v) => v.vendor_id,
    risk: (v) => v.max_risk,
    size: (v) => 0.035 + 0.024 * Math.log2(1 + v.invoices),
  });
  return { placed, categories: sectors };
}

/** The invoices waiting for review: one sector per rule (the most severe one each breaks), height the weighted
 * risk, further out and larger with the amount. */
export function layoutQueue(items: QueueItem[]): { placed: PlacedInvoice[]; sectors: Sector[] } {
  return placeInSectors(items, {
    group: (i) => i.rules[0] ?? "other",
    weight: (i) => i.amount,
    id: (i) => i.invoice_id,
    risk: (i) => i.rc,
    size: (i) => 0.04 + 0.014 * Math.log2(1 + i.amount / 10000),
  });
}

/** Where each stage stands: the pipeline runs left to right, the agents side by side in depth, with room after them for their labels. */
export function stagePositions(stages: Stage[]): Record<string, [number, number, number]> {
  const columns: Record<string, [number, number]> = {
    extraction: [0, 0], controls: [1, 0],
    math_approvals: [2, -1.4], tax_identity: [2, 0], vendor_intelligence: [2, 1.4], single_auditor: [2, 2.8],
    challenger: [3, 0], confidence: [4, 0], risk_score: [5, 0], human_review: [6, 0], audit_pack: [7, 0],
  };
  const out: Record<string, [number, number, number]> = {};
  stages.forEach((s, i) => {
    const [column, depth] = columns[s.id] ?? [i, 0];
    out[s.id] = [(column - 3.5) * 3.1 + (column > 2 ? 0.7 : -0.7), 0.6, depth * 1.9 - 0.95];
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

// ------------------------------------------------------------------ spend skyline
export interface SkylineBar {
  month: string;
  category: string;
  amount: number;
  position: [number, number, number];
  height: number;
  /** 0 for the smallest bar, 1 for the largest. */
  heat: number;
}

export const SKYLINE_STEP = { month: 0.92, category: 1.15, height: 5 };

/** One bar per category and month: months run along x, categories along z, the tallest bar is five units. */
export function skylineLayout(skyline: Analytics["skyline"]): SkylineBar[] {
  const max = Math.max(1, ...skyline.amounts.flat());
  const x0 = -((skyline.months.length - 1) * SKYLINE_STEP.month) / 2;
  const z0 = -((skyline.categories.length - 1) * SKYLINE_STEP.category) / 2;
  return skyline.categories.flatMap((category, c) =>
    skyline.months.map((month, m) => {
      const amount = skyline.amounts[c][m] ?? 0;
      const height = Math.max(0.02, (amount / max) * SKYLINE_STEP.height);
      return { month, category, amount, height, heat: Math.sqrt(amount / max),
               position: [x0 + m * SKYLINE_STEP.month, height / 2, z0 + c * SKYLINE_STEP.category] as [number, number, number] };
    }),
  );
}

// ------------------------------------------------------------------ ring network
export type PlacedNode = RingNode & { position: [number, number, number] };

/** Ring centres on a golden-angle spiral; inside each ring a few hundred steps of springs and repulsion. */
export function networkLayout(nodes: RingNode[], edges: RingEdge[], steps = 240): { placed: PlacedNode[]; centres: Record<number, [number, number, number]> } {
  const rings = [...new Set(nodes.map((n) => n.ring))].sort((a, b) => a - b);
  const centres: Record<number, [number, number, number]> = {};
  rings.forEach((ring, i) => {
    const r = 1.9 * Math.sqrt(i + 0.5);
    const a = i * 2.399963;                              // the golden angle
    centres[ring] = [r * Math.cos(a), 1.6 + 0.9 * Math.sin(i * 1.7), r * Math.sin(a)];
  });
  const pos = new Map<string, [number, number, number]>();
  const byRing = new Map<number, RingNode[]>();
  nodes.forEach((n) => byRing.set(n.ring, [...(byRing.get(n.ring) ?? []), n]));
  byRing.forEach((members, ring) => {
    const [cx, cy, cz] = centres[ring];
    members.forEach((n, i) => {
      const a = (i / members.length) * Math.PI * 2;
      pos.set(n.id, [cx + 0.6 * Math.cos(a), cy + (i % 3) * 0.15 - 0.15, cz + 0.6 * Math.sin(a)]);
    });
  });
  const springs = edges.filter((e) => pos.has(e.source) && pos.has(e.target));
  for (let step = 0; step < steps; step++) {
    const cool = 1 - step / steps;
    const move = new Map<string, [number, number, number]>(nodes.map((n) => [n.id, [0, 0, 0]]));
    byRing.forEach((members, ring) => {
      const c = centres[ring];
      for (let i = 0; i < members.length; i++) {
        const p = pos.get(members[i].id)!;
        const d = move.get(members[i].id)!;
        for (let k = 0; k < 3; k++) d[k] += (c[k] - p[k]) * 0.02;             // stay near the ring's centre
        for (let j = i + 1; j < members.length; j++) {
          const q = pos.get(members[j].id)!;
          const dx = p[0] - q[0], dy = p[1] - q[1], dz = p[2] - q[2];
          const dist2 = Math.max(0.01, dx * dx + dy * dy + dz * dz);
          const f = 0.06 / dist2;
          const e = move.get(members[j].id)!;
          d[0] += dx * f; d[1] += dy * f; d[2] += dz * f;
          e[0] -= dx * f; e[1] -= dy * f; e[2] -= dz * f;
        }
      }
    });
    for (const e of springs) {
      const p = pos.get(e.source)!, q = pos.get(e.target)!;
      const dx = q[0] - p[0], dy = q[1] - p[1], dz = q[2] - p[2];
      const dist = Math.max(0.01, Math.hypot(dx, dy, dz));
      const f = ((dist - 0.9) / dist) * 0.08;
      const a = move.get(e.source)!, b = move.get(e.target)!;
      a[0] += dx * f; a[1] += dy * f; a[2] += dz * f;
      b[0] -= dx * f; b[1] -= dy * f; b[2] -= dz * f;
    }
    move.forEach((d, id) => {
      const p = pos.get(id)!;
      const len = Math.hypot(d[0], d[1], d[2]);
      const cap = (0.25 * cool + 0.01) / Math.max(len, 0.25 * cool + 0.01);   // no step longer than the temperature
      pos.set(id, [p[0] + d[0] * Math.min(1, cap), Math.max(0.15, p[1] + d[1] * Math.min(1, cap)), p[2] + d[2] * Math.min(1, cap)]);
    });
  }
  return { placed: nodes.map((n) => ({ ...n, position: pos.get(n.id)! })), centres };
}

// ------------------------------------------------------------------ policy graph
export type PlacedGraphNode = GraphNode & { position: [number, number, number] };

/** Radius and height of each kind's shell: the version in the middle, rules around it, what they set or name outside. */
const SHELL: Record<string, [number, number]> = {
  version: [0, 3.2], section: [2.3, 2.4], clause: [4.4, 1.5], parameter: [6.6, 2.7], role: [8.2, 3.9],
  checker: [6.4, 0.3], page: [8.6, 1.0],
};

/** Each node starts on its kind's shell, at the angle of the rule it belongs to, then settles under springs along the
 * edges, repulsion between all nodes and a pull back to its shell, so the picture stays radial and readable. */
export function graphLayout(nodes: GraphNode[], edges: GraphEdge[], steps = 220): PlacedGraphNode[] {
  const clauses = nodes.filter((n) => n.kind === "clause");
  const angleOf = new Map<string, number>();
  clauses.forEach((c, i) => angleOf.set(c.id, (i / Math.max(1, clauses.length)) * Math.PI * 2));
  const neighbours = new Map<string, string[]>();
  for (const e of edges) {
    neighbours.set(e.source, [...(neighbours.get(e.source) ?? []), e.target]);
    neighbours.set(e.target, [...(neighbours.get(e.target) ?? []), e.source]);
  }
  const angle = (n: GraphNode, i: number): number => {
    if (angleOf.has(n.id)) return angleOf.get(n.id)!;
    const linked = (neighbours.get(n.id) ?? []).map((id) => angleOf.get(id)).filter((a): a is number => a !== undefined);
    if (linked.length) return Math.atan2(linked.reduce((t, a) => t + Math.sin(a), 0), linked.reduce((t, a) => t + Math.cos(a), 0));
    return i * 2.399963;
  };
  const home = new Map<string, [number, number, number]>();
  const others = nodes.filter((n) => n.kind === "version" && n.other);
  nodes.forEach((n, i) => {
    const [r, y] = SHELL[n.kind] ?? [9, 0];
    if (n.kind === "version") {
      const k = others.indexOf(n);
      home.set(n.id, k < 0 ? [0, y, 0] : [2.2 * Math.cos(k * 2.1), y + 2.2, 2.2 * Math.sin(k * 2.1)]);
      return;
    }
    const a = angle(n, i) + (n.kind === "parameter" || n.kind === "page" ? 0.12 : n.kind === "checker" ? -0.1 : 0);
    home.set(n.id, [r * Math.cos(a), y, r * Math.sin(a)]);
  });
  const pos = new Map(nodes.map((n) => [n.id, [...home.get(n.id)!] as [number, number, number]]));
  const ids = nodes.map((n) => n.id);
  for (let step = 0; step < steps; step++) {
    const cool = 1 - step / steps;
    const move = new Map(ids.map((id) => [id, [0, 0, 0] as [number, number, number]]));
    for (let i = 0; i < ids.length; i++) {
      const p = pos.get(ids[i])!, d = move.get(ids[i])!, h = home.get(ids[i])!;
      for (let k = 0; k < 3; k++) d[k] += (h[k] - p[k]) * 0.05;
      for (let j = i + 1; j < ids.length; j++) {
        const q = pos.get(ids[j])!;
        const dx = p[0] - q[0], dy = p[1] - q[1], dz = p[2] - q[2];
        const dist2 = Math.max(0.04, dx * dx + dy * dy + dz * dz);
        if (dist2 > 9) continue;
        const f = 0.09 / dist2;
        const e = move.get(ids[j])!;
        d[0] += dx * f; d[1] += dy * f; d[2] += dz * f;
        e[0] -= dx * f; e[1] -= dy * f; e[2] -= dz * f;
      }
    }
    for (const e of edges) {
      const p = pos.get(e.source), q = pos.get(e.target);
      if (!p || !q) continue;
      const dx = q[0] - p[0], dy = q[1] - p[1], dz = q[2] - p[2];
      const dist = Math.max(0.01, Math.hypot(dx, dy, dz));
      const f = ((dist - 1.8) / dist) * 0.02;
      const a = move.get(e.source)!, b = move.get(e.target)!;
      a[0] += dx * f; a[1] += dy * f; a[2] += dz * f;
      b[0] -= dx * f; b[1] -= dy * f; b[2] -= dz * f;
    }
    move.forEach((d, id) => {
      const p = pos.get(id)!;
      const len = Math.hypot(d[0], d[1], d[2]);
      const cap = Math.min(1, (0.2 * cool + 0.01) / Math.max(len, 1e-9));
      pos.set(id, [p[0] + d[0] * cap, p[1] + d[1] * cap, p[2] + d[2] * cap]);
    });
  }
  return nodes.map((n) => ({ ...n, position: pos.get(n.id)! }));
}
