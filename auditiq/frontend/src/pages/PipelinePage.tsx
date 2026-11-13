import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { ConfigName, StreamStatus } from "../api/types";
import { ArchitectureDiagram } from "../components/ArchitectureDiagram";
import { EDGES, KIND_STYLE, NODES } from "../lib/architecture";
import { short } from "../lib/chart";
import { Badge, ErrorBox, Kpi, Loading, Panel } from "../components/ui";
import { count } from "../lib/format";
import { useApi, type Loaded } from "../lib/useApi";
import { PipelineScene } from "../three/PipelineScene";

const ABOUT: Record<ConfigName, string> = {
  C1: "Controls only. The twelve deterministic controls, configured by the policy document, decide every rule that a comparison of fields can decide. No model is called.",
  C2: "One prompt over the whole policy, with no controls and no verification: the single-LLM setting that AuditBench evaluates.",
  C3: "Controls first, then three specialist agents, each limited to the rules that need reading. Count-based score.",
  C4: "C3 plus a challenger that removes agent findings the evidence does not support.",
  C5: "C4 plus evidence-grounded confidence: grounding, clause validity and agreement over three re-runs weight each finding.",
};

const TOPIC_ABOUT: Record<string, string> = {
  invoice: "invoices with their PO, goods receipt and approvals",
  vendor: "the vendor feed",
  email: "vendor e-mails (MIME)",
  compliance: "policy documents (PDF)",
};

const EDGE_KINDS: [string, string, string][] = [
  ["data", "#64748b", "data written or read"],
  ["control", "#0f766e", "control flow of one audit"],
  ["model", "#a21caf", "calls to a model"],
  ["dashed", "#94a3b8", "only in one configuration"],
];

/** The four topics documents arrive through, and how far the workers have got in each. */
function Ingestion({ status }: { status: Loaded<StreamStatus> }) {
  const s = status.data;
  return (
    <Panel
      title="Kafka ingestion"
      subtitle="Documents arrive through four partitioned topics. Each topic has its own group of stateless workers that write to the database; the partitions are the scaling lever."
      actions={
        <button className="btn btn-ghost" onClick={status.reload} disabled={status.loading}>
          Refresh
        </button>
      }
    >
      <ErrorBox error={status.error} onRetry={status.reload} />
      {!s && status.loading && <Loading what="Asking the broker" />}
      {s && !s.configured && (
        <p className="muted">
          No broker is configured, so ledgers are loaded in batches. To stream them, start one with <code>python scripts/kafka_local.py start</code>, then run{" "}
          <code>python -m auditiq stream work</code>.
        </p>
      )}
      {s?.error && <div className="error">The broker at {s.bootstrap} does not answer: {s.error}</div>}
      {s && s.topics.length > 0 && (
        <div className="kpis">
          {s.topics.map((t) => (
            <Kpi
              key={t.topic}
              label={t.topic}
              value={count(t.processed)}
              tone={t.lag ? "warn" : "good"}
              hint={
                <>
                  of {count(t.messages)} {TOPIC_ABOUT[t.kind]} · {t.partitions} partitions · lag {count(t.lag)}
                  {Object.keys(t.outcomes).length > 0 && (
                    <>
                      <br />
                      {Object.entries(t.outcomes)
                        .map(([k, n]) => `${count(n)} ${k}`)
                        .join(" · ")}
                    </>
                  )}
                </>
              }
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

export function PipelinePage() {
  const pipeline = useApi(() => api.pipeline());
  const overview = useApi(() => api.overview());
  const health = useApi(() => api.health());
  const stream = useApi(() => api.stream());
  const policy = useApi(() => api.policy());
  const [config, setConfig] = useState<ConfigName>("C5");
  const [highlight, setHighlight] = useState<ConfigName | "all">("all");
  const [selected, setSelected] = useState<string | null>(null);
  const p = pipeline.data;
  const o = overview.data;
  const h = health.data;
  const s = stream.data;

  const live = useMemo(() => {
    const out: Record<string, string> = {};
    if (h) {
      out.api = `v${h.version} · ${h.backend}`;
      out.chat = h.model ? "configured" : "not configured";
      if (h.ledger) out.erp = h.ledger;
      if (h.policy_version) out.registry = `v${h.policy_version} active`;
    }
    if (o) {
      out.ledger = `${short(o.invoices)} invoices`;
      out.audit = `${short(o.audited)} results`;
      out.views = `${count(o.states.PENDING_REVIEW ?? 0)} waiting`;
      out.review = `${count(o.states.PENDING_REVIEW ?? 0)} waiting · ${count(o.reviewed)} done`;
      out.route = `${count(o.routes.escalate ?? 0)} escalated`;
      out.score = `${short(o.audited)} scored`;
      const controls = o.findings_by_rule.filter((f) => f.source === "control").reduce((t, f) => t + f.findings, 0);
      out.controls = `${count(controls)} findings`;
      out.pack = `${count(o.runs.length)} runs`;
      if (o.coverage) {
        out.single = `${count(o.coverage.configurations.C2 ?? 0)} invoices`;
        out.labels = o.coverage.answer_key ? "present" : "none";
        if (o.coverage.judgement_run) out.confidence = `${count(o.coverage.configurations.C5 ?? 0)} invoices`;
      }
    }
    if (s) {
      const down = !s.configured ? "no broker" : s.error ? "broker down" : null;
      for (const t of s.topics) out[`t-${t.kind}`] = `${short(t.messages)} msgs · lag ${short(t.lag)}`;
      if (down) for (const k of ["vendor", "invoice", "email", "compliance"]) out[`t-${k}`] = down;
      out.workers = down ?? `${short(s.topics.reduce((t, x) => t + x.processed, 0))} processed`;
    }
    if (policy.data) out.policyT = `${policy.data.versions.length} versions`;
    return out;
  }, [h, o, s, policy.data]);

  const active = highlight === "all" || !p ? null : new Set(p.configurations[highlight]);
  const node = NODES.find((n) => n.id === selected);
  const stages = p?.stages ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Engineering · Pipeline</span>
          <h1>The pipeline</h1>
          <p className="muted">
            The whole platform in one diagram: where ledgers, e-mails and policies come in, the audit graph each invoice runs through, what is stored where, which parts call a
            model and how people reach it. Hover a component to trace its connections; click it for what it does and where it lives in the code.
          </p>
        </div>
      </header>

      <div className="kpis eight">
        <Kpi label="Components" value={count(NODES.length)} hint={`${count(EDGES.length)} connections · 10 subsystems`} />
        <Kpi label="Graph stages" value={count(stages.length)} hint={`${count(stages.filter((x) => x.kind === "llm").length)} call a model`} tone="accent" />
        <Kpi label="Rules in the policy" value={count(policy.data?.rules.length ?? 0)} hint={`${count(policy.data?.rules.filter((r) => r.kind === "judgement").length ?? 0)} need judgement`} />
        <Kpi label="Invoices in the store" value={o ? short(o.invoices) : "–"} hint={h ? `${h.backend} · ledger ${h.ledger ?? "none"}` : undefined} />
        <Kpi label="Audit results" value={o ? short(o.audited) : "–"} hint={o ? `${count(o.findings)} findings` : undefined} tone="good" />
        <Kpi label="Kafka topics" value={s ? count(s.topics.length) : "–"}
          hint={s ? (!s.configured ? "no broker configured" : s.error ? `broker at ${s.bootstrap} not answering` : `${short(s.topics.reduce((t, x) => t + x.lag, 0))} messages of lag`) : undefined}
          tone={s?.configured && !s.error ? "good" : "warn"} />
        <Kpi label="Chat model" value={h?.model ? "configured" : "none"} hint={h?.model ?? "C1 runs without one"} tone={h?.model ? "accent" : "warn"} />
        <Kpi label="API" value={h ? `v${h.version}` : "–"} hint="27 endpoints · roles · jobs" />
      </div>

      <Panel
        title="System architecture"
        subtitle="Clusters are subsystems; arrows follow the data. Choose a configuration to dim the stages it does not run."
        actions={
          <div className="segmented" role="tablist" aria-label="Highlight a configuration">
            {(["all", ...(p ? (Object.keys(p.configurations) as ConfigName[]) : [])] as (ConfigName | "all")[]).map((c) => (
              <button key={c} role="tab" aria-selected={highlight === c} className={highlight === c ? "active" : ""} onClick={() => setHighlight(c)}>
                {c === "all" ? "All" : c}
              </button>
            ))}
          </div>
        }
      >
        <div className="arch-wrap">
          <ArchitectureDiagram live={live} active={active} rules={policy.data?.rules ?? []} selected={selected} onSelect={setSelected} />
        </div>
        <div className="arch-legend">
          {Object.entries(KIND_STYLE).map(([k, v]) => (
            <span key={k}>
              <i style={{ background: v.color }} /> {v.label}
            </span>
          ))}
          {EDGE_KINDS.map(([k, c, label]) => (
            <span key={k}>
              <b className={`edge-swatch ${k}`} style={{ borderColor: c }} /> {label}
            </span>
          ))}
        </div>
        {node ? (
          <div className="arch-detail" role="region" aria-label={`About ${node.title}`}>
            <div>
              <span className="arch-kind" style={{ background: KIND_STYLE[node.kind].color }}>
                {KIND_STYLE[node.kind].label}
              </span>
              <h3>{node.title}</h3>
              <p>{node.detail}</p>
              {live[node.id] && <p className="muted small">Now: {live[node.id]}</p>}
            </div>
            <div>
              {node.files && (
                <>
                  <span className="kpi-label">In the code</span>
                  <ul className="files">
                    {node.files.map((f) => (
                      <li key={f}>
                        <code>{f}</code>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <span className="kpi-label">Connections</span>
              <ul className="files">
                {EDGES.filter((e) => e.from === node.id || e.to === node.id).map((e, i) => (
                  <li key={i}>
                    {e.from === node.id ? "→ " : "← "}
                    {NODES.find((n) => n.id === (e.from === node.id ? e.to : e.from))?.title ?? (e.from === node.id ? e.to : e.from)}
                    {e.label && <span className="muted"> · {e.label}</span>}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : (
          <p className="muted small">Click a component for its description, its files and its connections.</p>
        )}
      </Panel>

      <ErrorBox error={pipeline.error} onRetry={pipeline.reload} />
      {!p && pipeline.loading && <Loading />}
      {p && (
        <>
          <Panel title="Configurations compared" subtitle="Which stages each configuration runs. C1 is the measured system; C2 is the single-prompt baseline of AuditBench.">
            <div className="scroll-x">
              <table className="table compact matrix">
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th>Kind</th>
                    {(Object.keys(p.configurations) as ConfigName[]).map((c) => (
                      <th key={c} className="num">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {p.stages.map((st) => (
                    <tr key={st.id}>
                      <td className="strong">
                        {st.label}
                        {st.feature && <span className="feature-tag">the extra feature</span>}
                      </td>
                      <td>
                        <Badge tone={st.kind === "llm" ? "violet" : st.kind === "person" ? "warn" : "accent"}>{st.kind === "llm" ? "model" : st.kind}</Badge>
                      </td>
                      {(Object.keys(p.configurations) as ConfigName[]).map((c) => (
                        <td key={c} className="num">
                          {p.configurations[c].includes(st.id) ? <span className="tick" aria-label="runs">●</span> : <span className="muted" aria-label="does not run">–</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <div className="tabs" role="tablist" aria-label="Configuration">
            {(Object.keys(p.configurations) as ConfigName[]).map((c) => (
              <button key={c} role="tab" aria-selected={config === c} className={config === c ? "active" : ""} onClick={() => setConfig(c)}>
                {c}
              </button>
            ))}
          </div>
          <Panel title={`Configuration ${config} in 3D`} subtitle={ABOUT[config]}>
            <PipelineScene stages={p.stages} active={p.configurations[config]} />
            <ol className="stage-list">
              {p.configurations[config].map((id) => {
                const st = p.stages.find((x) => x.id === id);
                if (!st) return null;
                return (
                  <li key={id}>
                    <Badge tone={st.kind === "llm" ? "violet" : st.kind === "person" ? "warn" : "accent"}>{st.kind === "llm" ? "model" : st.kind}</Badge> {st.label}
                    {st.feature && <span className="feature-tag">the extra feature</span>}
                  </li>
                );
              })}
            </ol>
          </Panel>
        </>
      )}
      <Ingestion status={stream} />
    </div>
  );
}
