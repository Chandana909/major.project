// The architecture of the platform as one diagram, drawn from lib/architecture.ts. Clusters are the subsystems;
// edges run along corridors between them as rounded orthogonal paths; live figures sit on the components.
import { useMemo, useState } from "react";
import { CLUSTERS, EDGE_COLOR, EDGES, edgePoints, KIND_STYLE, midpoint, NODES, smoothPath, type ArchNode } from "../lib/architecture";

export interface DiagramProps {
  /** Short live figures shown on the nodes, by node id. */
  live?: Record<string, string>;
  /** Stage ids run by the chosen configuration; nodes of other stages are dimmed. */
  active?: Set<string> | null;
  /** Rules of the active policy, for the clauses node. */
  rules?: { rule: string; title: string; severity: string; kind: string }[];
  selected?: string | null;
  onSelect?: (id: string | null) => void;
}

const SEVERITY_FILL: Record<string, string> = { critical: "#fee2e2", high: "#ffedd5", medium: "#fef3c7", low: "#f1f5f9" };
const SEVERITY_INK: Record<string, string> = { critical: "#b91c1c", high: "#c2410c", medium: "#a16207", low: "#475569" };

/** Wraps chips into rows inside a box; returns their positions. */
function layoutChips(labels: string[], x: number, y: number, width: number, charWidth: number, height = 18, gap = 5): { label: string; x: number; y: number; w: number }[] {
  let cx = x, cy = y;
  return labels.map((label) => {
    const w = label.length * charWidth + 12;
    if (cx + w > x + width) {
      cx = x;
      cy += height + gap;
    }
    const placed = { label, x: cx, y: cy, w };
    cx += w + gap;
    return placed;
  });
}

export function ArchitectureDiagram({ live = {}, active = null, rules = [], selected = null, onSelect }: DiagramProps) {
  const [hover, setHover] = useState<string | null>(null);
  const focus = hover ?? selected;
  const linked = useMemo(() => new Set(EDGES.filter((e) => e.from === focus || e.to === focus).flatMap((e) => [e.from, e.to])), [focus]);
  const stageOn = (n: ArchNode) => !active || !n.stage || active.has(n.stage);
  const dimNode = new Set(NODES.filter((n) => !stageOn(n)).map((n) => n.id));
  const agentsOff = active !== null && !["math_approvals", "tax_identity", "vendor_intelligence"].some((s) => active.has(s));
  if (agentsOff) dimNode.add("agents");

  return (
    <svg className="arch" viewBox="0 0 1640 1180" role="img" aria-label="Architecture of AuditIQ: sources, ingestion, the audit engine, serving, policy, store, models and delivery">
      <defs>
        {Object.entries(EDGE_COLOR).map(([k, c]) => (
          <marker key={k} id={`arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill={c} />
          </marker>
        ))}
        <pattern id="arch-dots" width="16" height="16" patternUnits="userSpaceOnUse">
          <circle cx="1.5" cy="1.5" r="1" fill="#cbd5e1" opacity="0.55" />
        </pattern>
      </defs>
      <rect x="0" y="0" width="1640" height="1180" fill="url(#arch-dots)" />

      {CLUSTERS.map((c) => (
        <g key={c.id} className={`arch-cluster ${c.id === "kafka" || c.id === "agents" ? "inner" : ""} ${dimNode.has(c.id) ? "dim" : ""}`}>
          <rect x={c.x} y={c.y} width={c.w} height={c.h} rx={14} style={{ stroke: c.tone, fill: `${c.tone}0d` }} />
          <text x={c.x + 14} y={c.y + 20} className="arch-cluster-title" style={{ fill: c.tone }}>
            {c.title}
          </text>
          {c.note && (
            <text x={c.x + 14} y={c.y + 33} className="arch-cluster-note">
              {c.note}
            </text>
          )}
        </g>
      ))}

      {EDGES.map((e, i) => {
        const pts = edgePoints(e);
        const kind = e.kind ?? "data";
        const hot = focus !== null && (e.from === focus || e.to === focus);
        const dim = (focus !== null && !hot) || dimNode.has(e.from) || dimNode.has(e.to);
        const [lx, ly] = e.labelAt ?? midpoint(pts);
        return (
          <g key={i} className={`arch-edge ${kind} ${hot ? "hot" : ""} ${dim ? "dim" : ""}`}>
            <path d={smoothPath(pts)} style={{ stroke: EDGE_COLOR[kind] }} markerEnd={`url(#arrow-${kind})`} />
            {e.label && (
              <g className="arch-edge-label" transform={`translate(${lx},${ly})`}>
                <rect x={-(e.label.length * 2.9 + 6)} y={-8} width={e.label.length * 5.8 + 12} height={15} rx={7} />
                <text textAnchor="middle" y={3}>
                  {e.label}
                </text>
              </g>
            )}
          </g>
        );
      })}

      {NODES.map((n) => {
        const style = KIND_STYLE[n.kind];
        const dim = dimNode.has(n.id) || (focus !== null && n.id !== focus && !linked.has(n.id));
        const badge = live[n.id];
        const queue = n.kind === "queue";
        const chips = n.id === "rules"
          ? layoutChips(rules.map((r) => `${r.rule} ${r.title}${r.kind === "judgement" ? " · J" : ""}`), n.x + 12, n.y + 32, n.w - 24, 5.4, 18, 5)
          : n.chips
            ? layoutChips(n.chips.map((c) => c.label), n.x + 12, n.y + 18 + 16 * ((n.lines?.length ?? 0) + 1), n.w - 24, 6.1, 17, 4)
            : [];
        return (
          <g key={n.id} className={`arch-node ${n.kind} ${dim ? "dim" : ""} ${selected === n.id ? "selected" : ""}`} tabIndex={0} role="button"
            aria-label={`${n.title}: ${n.detail}`}
            onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(n.id)} onBlur={() => setHover(null)}
            onClick={() => onSelect?.(selected === n.id ? null : n.id)}
            onKeyDown={(ev) => (ev.key === "Enter" || ev.key === " ") && onSelect?.(selected === n.id ? null : n.id)}>
            <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={queue ? 8 : 10} className="arch-card" />
            <rect x={n.x} y={n.y} width={4} height={n.h} rx={2} style={{ fill: style.color }} />
            <text x={n.x + 14} y={n.y + (queue ? 18 : 20)} className={`arch-title ${queue ? "mono" : ""}`}>
              {n.title}
            </text>
            {badge && (
              <g>
                <rect x={n.x + n.w - (badge.length * 5.6 + 18)} y={n.y + 7} width={badge.length * 5.6 + 12} height={16} rx={8} className="arch-badge" style={{ fill: `${style.color}1a`, stroke: `${style.color}55` }} />
                <text x={n.x + n.w - 12 - (badge.length * 5.6 + 12) / 2} y={n.y + 18.5} textAnchor="middle" className="arch-badge-text" style={{ fill: style.color }}>
                  {badge}
                </text>
              </g>
            )}
            {(queue ? [n.detail] : n.lines ?? []).map((line, i) => (
              <text key={i} x={n.x + 14} y={n.y + (queue ? 34 : 38) + i * 15} className="arch-line">
                {line}
              </text>
            ))}
            {chips.map((c) => {
              const rule = n.id === "rules" ? rules.find((r) => c.label.startsWith(`${r.rule} `)) : undefined;
              return (
                <g key={c.label}>
                  <rect x={c.x} y={c.y} width={c.w} height={n.id === "rules" ? 18 : 17} rx={5} className="arch-chip"
                    style={rule ? { fill: SEVERITY_FILL[rule.severity], stroke: SEVERITY_INK[rule.severity] + "55" } : undefined} />
                  <text x={c.x + 6} y={c.y + 12.5} className="arch-chip-text" style={rule ? { fill: SEVERITY_INK[rule.severity] } : undefined}>
                    {c.label}
                  </text>
                </g>
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}
