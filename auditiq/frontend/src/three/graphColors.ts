// Colours of the policy graph, shared by the 3D view and the page around it (so the page does not load three.js).
import type { GraphNode } from "../api/types";

export const NODE_COLORS: Record<string, string> = {
  version: "#f8fafc",
  section: "#94a3b8",
  parameter: "#2dd4bf",
  role: "#fbbf24",
  agent: "#a78bfa",
  control: "#38bdf8",
  page: "#60a5fa",
  critical: "#f87171",
  high: "#fb923c",
  medium: "#facc15",
  low: "#cbd5e1",
};

export const NODE_LABELS: [string, string][] = [
  ["version", "Policy version"],
  ["section", "Section"],
  ["critical", "Rule, critical"],
  ["high", "Rule, high"],
  ["medium", "Rule, medium"],
  ["low", "Rule, low"],
  ["parameter", "Parameter"],
  ["role", "Role and its limit"],
  ["control", "Control function"],
  ["agent", "Agent"],
  ["page", "Document page"],
];

export const EDGE_COLORS: Record<string, string> = {
  "has section": "#64748b",
  "has rule": "#94a3b8",
  sets: "#2dd4bf",
  limit: "#fbbf24",
  "checked by": "#a78bfa",
  "stated on": "#60a5fa",
  changes: "#f472b6",
};

export function nodeColor(n: GraphNode): string {
  if (n.kind === "clause") return NODE_COLORS[n.severity ?? "low"] ?? NODE_COLORS.low;
  if (n.kind === "checker") return NODE_COLORS[n.checker_kind ?? "control"];
  return NODE_COLORS[n.kind] ?? "#94a3b8";
}
