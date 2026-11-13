// Geometry of the ledger graph, kept apart from the component so that it can be tested without WebGL.
import type { CaseEdge, CaseNode } from "../api/types";

export type PlacedCaseNode = CaseNode & { position: [number, number, number] };

/** Radius and height of the shell of each kind: rules in the middle, vendors and approvers around them, invoices outside. */
const SHELL: Record<string, [number, number]> = {
  ring: [0, 3.4], rule: [3.2, 2.0], approver: [5.2, 3.2], vendor: [6.4, 1.2], invoice: [8.2, 0.4],
};

/** Each node starts on its kind's shell, at the angle of the nodes it is joined to, then settles under springs along
 * the edges, repulsion between all nodes and a pull back towards its shell. Deterministic: the same graph gives the
 * same picture. */
export function caseLayout(nodes: CaseNode[], edges: CaseEdge[], steps = 200): PlacedCaseNode[] {
  const neighbours = new Map<string, string[]>();
  for (const e of edges) {
    neighbours.set(e.source, [...(neighbours.get(e.source) ?? []), e.target]);
    neighbours.set(e.target, [...(neighbours.get(e.target) ?? []), e.source]);
  }
  const angleOf = new Map<string, number>();
  const fixed = nodes.filter((n) => n.kind === "rule" || n.kind === "approver" || n.kind === "ring");
  fixed.forEach((n, i) => angleOf.set(n.id, (i / Math.max(1, fixed.length)) * Math.PI * 2));
  const angle = (n: CaseNode, i: number): number => {
    if (angleOf.has(n.id)) return angleOf.get(n.id)!;
    const linked = (neighbours.get(n.id) ?? []).map((id) => angleOf.get(id)).filter((a): a is number => a !== undefined);
    if (linked.length) return Math.atan2(linked.reduce((t, a) => t + Math.sin(a), 0), linked.reduce((t, a) => t + Math.cos(a), 0)) + (i % 7) * 0.05;
    return i * 2.399963;
  };
  const home = new Map<string, [number, number, number]>();
  nodes.forEach((n, i) => {
    const [r, y] = SHELL[n.kind] ?? [7, 0];
    const a = angle(n, i);
    home.set(n.id, [r * Math.cos(a), y, r * Math.sin(a)]);
  });
  const ids = nodes.map((n) => n.id);
  const pos = new Map(nodes.map((n) => [n.id, [...home.get(n.id)!] as [number, number, number]]));
  for (let step = 0; step < steps && ids.length > 1; step++) {
    const cool = 1 - step / steps;
    const move = new Map(ids.map((id) => [id, [0, 0, 0] as [number, number, number]]));
    for (let i = 0; i < ids.length; i++) {
      const p = pos.get(ids[i])!, d = move.get(ids[i])!, h = home.get(ids[i])!;
      for (let k = 0; k < 3; k++) d[k] += (h[k] - p[k]) * 0.04;
      for (let j = i + 1; j < ids.length; j++) {
        const q = pos.get(ids[j])!;
        const dx = p[0] - q[0], dy = p[1] - q[1], dz = p[2] - q[2];
        const dist2 = Math.max(0.04, dx * dx + dy * dy + dz * dz);
        if (dist2 > 9) continue;
        const f = 0.1 / dist2;
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
      const f = ((dist - 2.2) / dist) * 0.015;
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

export const CASE_EDGE_COLORS: Record<string, string> = {
  billed: "#64748b",
  violates: "#f87171",
  "approved by": "#e2e8f0",
  "member of": "#a78bfa",
  breaks: "#fb923c",
  "approved breaches of": "#fbbf24",
  "shares PAN": "#2dd4bf",
  "shares GSTIN": "#38bdf8",
};

export const CASE_NODE_LABELS: [string, string][] = [
  ["vendor", "Vendor (colour: highest risk)"],
  ["approver", "Approver"],
  ["rule", "Rule broken"],
  ["invoice", "Invoice with findings"],
  ["ring", "Ring"],
];
