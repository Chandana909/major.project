// The Kafka layer as a live topology: sources, the producer, the broker's topics and partitions, the consumer
// groups and where they write. Messages are drawn moving along the edges while there is something to move.
import type { StreamTopic } from "../api/types";
import { short } from "../lib/chart";

const TOPICS = ["vendor", "invoice", "email", "compliance"] as const;
const SINK: Record<string, string> = {
  vendor: "vendor_master",
  invoice: "invoices → audit (C1)",
  email: "emails · mentions",
  compliance: "policy registry",
};
const SOURCE_OF: Record<string, number> = { vendor: 0, invoice: 0, email: 1, compliance: 2 };

function Flow({ id, d, active, color, delay = 0 }: { id: string; d: string; active: boolean; color: string; delay?: number }) {
  return (
    <g className={`kt-edge ${active ? "on" : ""}`}>
      <path id={id} d={d} style={{ stroke: color }} />
      {active &&
        [0, 0.33, 0.66].map((offset) => (
          <circle key={offset} r={3.4} className="kt-dot" style={{ fill: color }}>
            <animateMotion dur="1.8s" repeatCount="indefinite" begin={`${delay + offset * 1.8}s`}>
              <mpath href={`#${id}`} />
            </animateMotion>
          </circle>
        ))}
    </g>
  );
}

export function KafkaTopology({ topics, bootstrap, prefix, publishing, consuming }: {
  topics: StreamTopic[];
  bootstrap?: string;
  prefix?: string;
  publishing: boolean;
  consuming: boolean;
}) {
  const by = new Map(topics.map((t) => [t.kind, t]));
  const W = 1180, laneY = (i: number) => 92 + i * 78;
  const sources = [
    { label: "Ledger", sub: "vendors · invoices + PO, GRN, approvals", color: "#0f766e" },
    { label: "Vendor mailbox", sub: ".mbox · MIME e-mails", color: "#7c3aed" },
    { label: "Policy PDFs", sub: "SOP versions", color: "#b45309" },
  ];
  return (
    <svg className="kafka-topology" viewBox={`0 0 ${W} 420`} role="img" aria-label="Kafka topology: sources, producer, topics and partitions, consumer groups and the store">
      <defs>
        <marker id="kt-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8" />
        </marker>
      </defs>

      {/* sources */}
      <text x={24} y={34} className="kt-col">SOURCES</text>
      {sources.map((src, i) => (
        <g key={src.label}>
          <rect x={24} y={86 + i * 104} width={176} height={62} rx={10} className="kt-box" style={{ stroke: src.color }} />
          <rect x={24} y={86 + i * 104} width={5} height={62} rx={2} style={{ fill: src.color }} />
          <text x={40} y={110 + i * 104} className="kt-title">{src.label}</text>
          <text x={40} y={128 + i * 104} className="kt-sub">{src.sub}</text>
        </g>
      ))}

      {/* producer */}
      <text x={262} y={34} className="kt-col">PRODUCER</text>
      <rect x={262} y={150} width={150} height={116} rx={12} className="kt-box producer" />
      <text x={278} y={176} className="kt-title">Publisher</text>
      <text x={278} y={196} className="kt-sub">idempotent</text>
      <text x={278} y={212} className="kt-sub">acks = all · lz4</text>
      <text x={278} y={228} className="kt-sub">keyed by vendor</text>
      <text x={278} y={250} className="kt-sub mono">{publishing ? "sending…" : "idle"}</text>
      {sources.map((_, i) => (
        <Flow key={i} id={`kt-src-${i}`} d={`M200,${117 + i * 104} C232,${117 + i * 104} 236,208 262,208`} active={publishing} color="#94a3b8" delay={i * 0.2} />
      ))}

      {/* broker */}
      <text x={452} y={34} className="kt-col">BROKER · {bootstrap ?? "not configured"}</text>
      <rect x={452} y={56} width={404} height={346} rx={14} className="kt-broker" />
      <text x={470} y={78} className="kt-sub">Kafka 4.3.2 · KRaft · topics {prefix ?? "auditiq"}.*</text>
      {TOPICS.map((kind, i) => {
        const t = by.get(kind);
        const parts = t?.partitions ?? 0;
        const share = t && t.messages ? t.processed / t.messages : 0;
        const y = laneY(i);
        const laneW = 236;
        return (
          <g key={kind}>
            <Flow id={`kt-in-${kind}`} d={`M412,208 C440,208 444,${y + 26} 470,${y + 26}`} active={publishing && SOURCE_OF[kind] !== undefined} color="#f97316" delay={i * 0.15} />
            <text x={470} y={y + 4} className="kt-title mono">{t?.topic ?? `${prefix ?? "auditiq"}.${kind}`}</text>
            {Array.from({ length: Math.max(parts, 1) }, (_, p) => {
              const w = (laneW - (parts - 1) * 4) / Math.max(parts, 1);
              const x = 470 + p * (w + 4);
              return (
                <g key={p}>
                  <rect x={x} y={y + 14} width={w} height={22} rx={4} className="kt-partition" />
                  <rect x={x} y={y + 14} width={w * share} height={22} rx={4} className="kt-partition-done" />
                  <text x={x + 6} y={y + 29} className="kt-p">p{p}</text>
                </g>
              );
            })}
            <text x={716} y={y + 22} className="kt-num">{short(t?.messages ?? 0)}</text>
            <text x={716} y={y + 36} className="kt-sub">messages</text>
            <text x={786} y={y + 22} className={`kt-num ${t?.lag ? "lag" : ""}`}>{short(t?.lag ?? 0)}</text>
            <text x={786} y={y + 36} className="kt-sub">lag</text>
          </g>
        );
      })}

      {/* consumers and sinks */}
      <text x={896} y={34} className="kt-col">CONSUMER GROUPS → STORE</text>
      {TOPICS.map((kind, i) => {
        const t = by.get(kind);
        const y = laneY(i);
        return (
          <g key={kind}>
            <Flow id={`kt-out-${kind}`} d={`M856,${y + 26} L896,${y + 26}`} active={consuming || Boolean(t?.lag)} color="#0f766e" delay={i * 0.1} />
            <rect x={896} y={y + 4} width={260} height={46} rx={10} className="kt-box consumer" />
            <text x={910} y={y + 22} className="kt-title">{prefix ?? "auditiq"}-{kind}-workers</text>
            <text x={910} y={y + 39} className="kt-sub">
              {short(t?.processed ?? 0)} processed → {SINK[kind]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
