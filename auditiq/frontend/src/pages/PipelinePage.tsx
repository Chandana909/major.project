import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ConfigName, StreamStatus } from "../api/types";
import { EDGES, GROUPS, NODES } from "../lib/architecture";
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
  const p = pipeline.data;
  const o = overview.data;
  const h = health.data;
  const s = stream.data;

  const stages = p?.stages ?? [];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Engineering · Pipeline</span>
          <h1>The pipeline</h1>
          <p className="muted">
            The audit graph each invoice runs through, the stages each configuration (C1 to C5) runs, and the Kafka topics documents arrive through.
          </p>
        </div>
      </header>

      <div className="kpis eight">
        <Kpi label="Components" value={count(NODES.length)} hint={`${count(EDGES.length)} connections · ${GROUPS.length} subsystems`} />
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

      <Panel title="The whole platform" subtitle="Every subsystem, component and connection, in 3D and as a map, with a guided tour for presenting it.">
        <p className="muted">
          The architecture has its own page: <Link to="/architecture">Architecture</Link>. Hover a component there to see what feeds it and what it feeds, and click it to open
          the page where it runs.
        </p>
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
