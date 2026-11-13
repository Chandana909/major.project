import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, waitForJob } from "../api/client";
import type { AiLayer, ConfigName, InvoiceDetail, Job, TrailEntry } from "../api/types";
import { Badge, Empty, ErrorBox, JobProgress, Kpi, Loading, Panel, RiskMeter, RouteBadge } from "../components/ui";
import { short } from "../lib/chart";
import { count } from "../lib/format";
import { notifyStoreChanged, useApi } from "../lib/useApi";

type Node = { id: string; label: string; kind: "code" | "llm" | "person"; x: number; y: number; sub: string };

const NODES: Node[] = [
  { id: "extraction", label: "Evidence extraction", kind: "code", x: 20, y: 150, sub: "PO · GRN · approvals · history" },
  { id: "controls", label: "12 controls", kind: "code", x: 200, y: 150, sub: "thresholds from the registry" },
  { id: "math_approvals", label: "Math & Approvals", kind: "llm", x: 390, y: 40, sub: "judges 2.1.4 · 2.1.5" },
  { id: "tax_identity", label: "Tax & Identity", kind: "llm", x: 390, y: 120, sub: "judges 2.2.2" },
  { id: "vendor_intelligence", label: "Vendor Intelligence", kind: "llm", x: 390, y: 200, sub: "judges 4.1.2" },
  { id: "single_auditor", label: "Single-prompt auditor", kind: "llm", x: 390, y: 280, sub: "C2 baseline" },
  { id: "challenger", label: "Challenger", kind: "llm", x: 590, y: 150, sub: "drops findings without evidence" },
  { id: "confidence", label: "Confidence", kind: "llm", x: 770, y: 150, sub: "g · p · a over 3 re-runs" },
  { id: "scoring", label: "Risk score & route", kind: "code", x: 950, y: 150, sub: "R0 · Rc · τ = 50" },
  { id: "review", label: "Human review", kind: "person", x: 950, y: 270, sub: "approve · reject · override" },
];
const EDGES: [string, string][] = [
  ["extraction", "controls"], ["controls", "math_approvals"], ["controls", "tax_identity"], ["controls", "vendor_intelligence"],
  ["extraction", "single_auditor"], ["math_approvals", "challenger"], ["tax_identity", "challenger"], ["vendor_intelligence", "challenger"],
  ["single_auditor", "challenger"], ["challenger", "confidence"], ["confidence", "scoring"], ["controls", "scoring"], ["scoring", "review"],
];
const KIND_COLOR = { code: "#0f766e", llm: "#7c3aed", person: "#d97706" };
const W = 140, H = 58;

function nodeOf(entry: { stage: string; actor: string | null }): string {
  if (entry.stage === "agent") return entry.actor ?? "single_auditor";
  if (entry.stage === "rerun") return "confidence";
  return entry.stage;
}

function AgentGraph({ stats, active, done }: { stats: Map<string, { steps: number; calls: number; tokens: number; latency: number | null }>; active: string | null; done: Set<string> }) {
  const at = new Map(NODES.map((n) => [n.id, n]));
  return (
    <svg className="agent-graph" viewBox="0 0 1110 350" role="img" aria-label="The audit graph: extraction, controls, the agents, the challenger, confidence, the score and human review">
      <defs>
        <marker id="ag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8" />
        </marker>
      </defs>
      {EDGES.map(([a, b]) => {
        const s = at.get(a)!, t = at.get(b)!;
        const x1 = s.x + W, y1 = s.y + H / 2, x2 = t.x, y2 = t.y + H / 2;
        const vertical = t.x === s.x;
        const d = vertical ? `M${s.x + W / 2},${s.y + H} L${t.x + W / 2},${t.y}` : `M${x1},${y1} C${x1 + 30},${y1} ${x2 - 30},${y2} ${x2},${y2}`;
        const hot = active === b && done.has(a);
        return <path key={`${a}-${b}`} d={d} className={`ag-edge ${hot ? "hot" : ""} ${done.has(a) && done.has(b) ? "done" : ""}`} markerEnd="url(#ag-arrow)" />;
      })}
      {NODES.map((n) => {
        const st = stats.get(n.id);
        const state = active === n.id ? "active" : done.has(n.id) ? "done" : "";
        return (
          <g key={n.id} className={`ag-node ${state}`}>
            <rect x={n.x} y={n.y} width={W} height={H} rx={10} style={{ stroke: KIND_COLOR[n.kind] }} />
            <rect x={n.x} y={n.y} width={4} height={H} rx={2} style={{ fill: KIND_COLOR[n.kind] }} />
            <text x={n.x + 12} y={n.y + 18} className="ag-title">{n.label}</text>
            <text x={n.x + 12} y={n.y + 33} className="ag-sub">{n.sub}</text>
            <text x={n.x + 12} y={n.y + 48} className="ag-stat">
              {st ? `${short(st.steps)} steps${st.calls ? ` · ${short(st.tokens)} tok · ${((st.latency ?? 0) / 1000).toFixed(0)} s` : ""}` : "not run"}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function AiLayerPage() {
  const ai = useApi(() => api.ai());
  const system = useApi(() => api.system());
  const [invoiceId, setInvoiceId] = useState<string | null>(null);
  const [detail, setDetail] = useState<InvoiceDetail | null>(null);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [runId, setRunId] = useState("");
  const [runConfig, setRunConfig] = useState<ConfigName>("C1");
  const a: AiLayer | null = ai.data;
  const online = Boolean(system.data?.model.reachable);

  const stats = useMemo(() => {
    const m = new Map<string, { steps: number; calls: number; tokens: number; latency: number | null }>();
    for (const s of a?.stages ?? []) {
      const id = nodeOf(s);
      const cur = m.get(id) ?? { steps: 0, calls: 0, tokens: 0, latency: null };
      cur.steps += s.steps;
      cur.calls += s.model_calls;
      cur.tokens += s.prompt_tokens + s.completion_tokens;
      cur.latency = s.mean_latency_ms ?? cur.latency;
      m.set(id, cur);
    }
    return m;
  }, [a]);

  useEffect(() => {
    if (!invoiceId) return;
    let live = true;
    setDetail(null);
    setStep(0);
    api.invoice(invoiceId).then((d) => {
      if (!live) return;
      setDetail(d);
      setPlaying(true);
    }).catch((err) => live && setError(err as Error));
    return () => {
      live = false;
    };
  }, [invoiceId]);

  const trail: TrailEntry[] = detail?.result?.trail ?? [];
  useEffect(() => {
    if (!playing || step >= trail.length) {
      if (step >= trail.length) setPlaying(false);
      return;
    }
    const t = window.setTimeout(() => setStep((s) => s + 1), 900);
    return () => window.clearTimeout(t);
  }, [playing, step, trail.length]);

  const shown = trail.slice(0, step);
  const done = new Set(shown.map(nodeOf));
  const active = step > 0 && step <= trail.length ? nodeOf(trail[step - 1]) : null;
  const pack = detail?.result?.pack;
  const totals = (a?.stages ?? []).reduce((t, s) => ({ calls: t.calls + s.model_calls, tokens: t.tokens + s.prompt_tokens + s.completion_tokens }), { calls: 0, tokens: 0 });

  const runLive = async () => {
    const id = runId.trim().toUpperCase();
    if (!id) return;
    setError(null);
    try {
      await waitForJob(await api.audit(id, runConfig), setJob as (j: Job<unknown>) => void, 1500);
      notifyStoreChanged();
      ai.reload();
      setInvoiceId(null);
      window.setTimeout(() => setInvoiceId(id), 0);
    } catch (err) {
      setError(err as Error);
    } finally {
      setJob(null);
    }
  };

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">AI layer · Agents & pipeline</span>
          <h1>Agents & pipeline</h1>
          <p className="muted">
            The audit graph (LangGraph): code extracts the evidence and runs the twelve controls; three specialist agents read the four judgement rules, each within its remit; a
            challenger removes findings the evidence does not support; three re-runs at temperature 0.7 measure agreement; code scores and routes. Replay a stored run step by step,
            or audit an invoice now.
          </p>
        </div>
        <div className="page-actions">
          <span className={`status-chip ${online ? "good" : "bad"}`}>
            <span className={`dot ${online ? "dot-good" : "dot-bad"}`} />
            {online ? `Model online · ${system.data?.model.name}` : `Model offline${system.data?.model.endpoint ? ` · ${system.data.model.endpoint}` : ""}`}
          </span>
        </div>
      </header>

      <ErrorBox error={ai.error ?? error} onRetry={ai.reload} />
      {!a && ai.loading && <Loading what="Reading the agents" />}

      {a && (
        <>
          <div className="kpis eight">
            <Kpi label="Agents" value={a.agents.length} hint="specialists, one remit each" tone="accent" />
            <Kpi label="Judgement rules" value={a.agents.reduce((t, x) => t + x.judges.length, 0)} hint={`of policy v${a.policy_version}`} />
            <Kpi label="Configurations" value={Object.keys(a.configurations).length} hint="C1 to C5" />
            <Kpi label="Model calls stored" value={short(totals.calls)} hint="in the latest results" />
            <Kpi label="Tokens stored" value={short(totals.tokens)} hint="prompt + completion" />
            <Kpi label="Invoices with agent runs" value={count(a.traced.length)} hint="to replay" tone="good" />
            <Kpi label="Model" value={a.model ?? "–"} hint={online ? "answering" : "not answering"} tone={online ? "good" : "warn"} />
            <Kpi label="Re-runs" value={a.configurations.C5?.reruns ?? 3} hint={`at temperature ${a.configurations.C5?.rerun_temperature ?? 0.7}`} />
          </div>

          <Panel title="The audit graph" subtitle="Each node with what the stored runs cost: steps, tokens and mean latency of a model call. During a replay the node working lights up and the path behind it fills in.">
            <div className="topology-wrap">
              <AgentGraph stats={stats} active={active} done={done} />
            </div>
            <div className="legend">
              <span><i style={{ background: KIND_COLOR.code }} /> code</span>
              <span><i style={{ background: KIND_COLOR.llm }} /> language model</span>
              <span><i style={{ background: KIND_COLOR.person }} /> a person</span>
            </div>
          </Panel>

          <div className="grid-2 wide-left">
            <Panel
              title={invoiceId ? `Replay: ${invoiceId}` : "Replay a run"}
              subtitle="Every step of the invoice's latest audit, in order, from its audit trail: who did it, what it concluded, its tokens and time."
              actions={
                detail && (
                  <div className="panel-actions">
                    <button className="btn btn-ghost" onClick={() => { setStep(0); setPlaying(true); }}>Replay</button>
                    <button className="btn btn-ghost" onClick={() => setStep(trail.length)}>Show all</button>
                  </div>
                )
              }
            >
              {!invoiceId ? (
                <Empty>Choose an invoice from the list, or audit one now.</Empty>
              ) : !detail ? (
                <Loading what="Reading the audit trail" />
              ) : (
                <>
                  <ol className="replay">
                    {trail.map((t, i) => (
                      <li key={t.seq} className={i < step ? (i === step - 1 ? "current" : "done") : "todo"}>
                        <span className="num">{t.seq}</span>
                        <div>
                          <strong>{t.stage === "agent" || t.stage === "rerun" ? `${t.stage}: ${t.actor}` : t.stage}</strong>
                          <span className="muted small"> {t.detail}</span>
                        </div>
                        <span className="small mono">{t.latency_ms ? `${(t.latency_ms / 1000).toFixed(1)} s · ${count((t.prompt_tokens ?? 0) + (t.completion_tokens ?? 0))} tok` : "code"}</span>
                      </li>
                    ))}
                  </ol>
                  {pack && step >= trail.length && (
                    <div className="replay-outcome">
                      <RouteBadge route={detail.result?.route} />
                      <RiskMeter score={detail.result?.rc ?? 0} />
                      <span className="small">
                        {pack.flags.length} finding{pack.flags.length === 1 ? "" : "s"} kept · {pack.removed_by_challenger.length} removed by the challenger
                      </span>
                      <Link className="btn btn-ghost" to={`/invoice/${invoiceId}`}>Open the audit pack</Link>
                    </div>
                  )}
                </>
              )}
            </Panel>
            <div className="stack">
              <Panel title="Audit an invoice now" subtitle="Runs the graph on one invoice under the configuration chosen; C1 needs no model.">
                <div className="form-grid">
                  <label>
                    Invoice
                    <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="INV40045" aria-label="Invoice to audit" />
                  </label>
                  <label>
                    Configuration
                    <select value={runConfig} onChange={(e) => setRunConfig(e.target.value as ConfigName)} aria-label="Configuration to run">
                      {(Object.keys(a.configurations) as ConfigName[]).map((c) => (
                        <option key={c} value={c} disabled={c !== "C1" && !online}>
                          {c}{c !== "C1" && !online ? " (needs the model)" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <button className="btn btn-primary" onClick={runLive} disabled={Boolean(job) || !runId.trim()}>
                  Audit and replay
                </button>
                <JobProgress job={job} />
              </Panel>
              <Panel title={`Runs to replay (${count(a.traced.length)})`} subtitle="Invoices whose latest result came from the agents, most model calls first.">
                <div className="table-wrap short">
                  <table className="table sticky compact">
                    <thead>
                      <tr>
                        <th>Invoice</th>
                        <th>Config</th>
                        <th className="num">Calls</th>
                        <th className="num">Findings</th>
                      </tr>
                    </thead>
                    <tbody>
                      {a.traced.map((t) => (
                        <tr key={t.invoice_id} className={t.invoice_id === invoiceId ? "highlight" : ""}>
                          <td>
                            <button className="linkish mono" onClick={() => setInvoiceId(t.invoice_id)}>
                              {t.invoice_id}
                            </button>
                          </td>
                          <td>
                            <span className="config">{t.configuration}</span>
                          </td>
                          <td className="num">{t.llm_calls}</td>
                          <td className="num">{t.flag_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </div>
          </div>

          <div className="grid-2">
            <Panel title="The agents" subtitle="Each agent reads only its sections of the policy; a finding that cites a rule outside its remit is discarded by code.">
              <div className="agent-cards">
                {a.agents.map((x) => (
                  <article key={x.name} className="agent-card">
                    <header>
                      <strong>{x.title}</strong>
                      <span className="mono small muted">{x.name}</span>
                    </header>
                    <div className="small">
                      Sections <b>{x.sections.join(", ")}</b> · judges {x.judges.map((j) => <Badge key={j} tone="violet">{j}</Badge>)}
                    </div>
                    <div className="small muted">
                      sees: {x.records.join(", ")}
                      {x.history_rules.length ? ` · vendor history by ${x.history_rules.join(", ")}` : ""}
                    </div>
                  </article>
                ))}
              </div>
            </Panel>
            <Panel title="Configurations" subtitle="Which stages each configuration runs (measured results on the Results page).">
              <table className="table compact matrix">
                <thead>
                  <tr>
                    <th>Config</th>
                    <th>Controls</th>
                    <th>Agents</th>
                    <th>Challenger</th>
                    <th>Confidence</th>
                    <th className="num">T</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(a.configurations).map(([name, c]) => (
                    <tr key={name}>
                      <td className="strong">{name}</td>
                      <td>{c.controls ? <span className="tick">●</span> : "–"}</td>
                      <td>{c.agents === "none" ? "–" : c.agents}</td>
                      <td>{c.challenger ? <span className="tick">●</span> : "–"}</td>
                      <td>{c.confidence ? `${c.reruns} re-runs` : "–"}</td>
                      <td className="num">{c.temperature}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
