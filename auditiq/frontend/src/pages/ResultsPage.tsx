import { api } from "../api/client";
import type { Interval } from "../api/types";
import { Badge, Empty, ErrorBox, Kpi, Loading, Panel } from "../components/ui";
import { count, ratio } from "../lib/format";
import { BENCH, meanOver, v } from "../lib/results";
import { useApi } from "../lib/useApi";
import { PolicyBars } from "../three/PolicyBars";

const SYSTEMS = ["C0-IF", "C0-SVM", "C1"];
const SYSTEM_NAME: Record<string, string> = { "C0-IF": "Isolation forest", "C0-SVM": "One-class SVM", C1: "Policy-driven controls" };
const CLASSES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "J1", "J2", "J3", "J4"];

function withInterval(x: Interval | undefined): string {
  if (!x || x.value === null) return "n/a";
  const ci = x.ci_low !== undefined && x.ci_low !== null && x.ci_high !== undefined && x.ci_high !== null ? ` [${ratio(x.ci_low)}, ${ratio(x.ci_high)}]` : "";
  return `${ratio(x.value)}${ci}`;
}

function heat(value: number | null): string {
  if (value === null) return "transparent";
  return `rgba(45, 212, 191, ${0.08 + value * 0.62})`;
}

function ScalabilityChart({ points }: { points: { workers: number; invoices_per_second: number }[] }) {
  const w = 420, h = 200, pad = 36;
  const maxX = Math.max(...points.map((p) => p.workers));
  const maxY = Math.max(...points.map((p) => p.invoices_per_second)) * 1.15;
  const x = (n: number) => pad + ((n - 1) / Math.max(maxX - 1, 1)) * (w - 2 * pad);
  const y = (n: number) => h - pad - (n / maxY) * (h - 2 * pad);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(p.workers)},${y(p.invoices_per_second)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="chart" role="img" aria-label="Throughput against worker processes">
      <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} className="axis" />
      <line x1={pad} y1={pad / 2} x2={pad} y2={h - pad} className="axis" />
      <path d={path} className="line" />
      {points.map((p) => (
        <g key={p.workers}>
          <circle cx={x(p.workers)} cy={y(p.invoices_per_second)} r={4.5} className="dot" />
          <text x={x(p.workers)} y={y(p.invoices_per_second) - 10} textAnchor="middle" className="label">
            {(p.invoices_per_second / 1000).toFixed(0)}k/s
          </text>
          <text x={x(p.workers)} y={h - pad + 16} textAnchor="middle" className="tick">
            {p.workers}
          </text>
        </g>
      ))}
      <text x={w / 2} y={h - 4} textAnchor="middle" className="tick">
        worker processes
      </text>
    </svg>
  );
}

export function ResultsPage() {
  const results = useApi(() => api.results());
  const r = results.data;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Results</h1>
          <p className="muted">
            Every number on this page was produced by a script of the repository and is read from <code>results/</code>. Runs with a local model on small samples are marked as such: they show that the stages work, not how well a model audits.
          </p>
        </div>
      </header>
      <ErrorBox error={results.error} onRetry={results.reload} />
      {!r && results.loading && <Loading what="Reading the results" />}
      {r && (
        <>
          <div className="kpis">
            <Kpi label="Controls: F1 on the benchmark" value={ratio(meanOver(r, "C1", "detection_f1"))} hint={`isolation forest ${ratio(meanOver(r, "C0-IF", "detection_f1"))} · SVM ${ratio(meanOver(r, "C0-SVM", "detection_f1"))}`} tone="accent" />
            <Kpi label="Controls: precision" value={ratio(meanOver(r, "C1", "detection_precision"))} hint="mean of three ledgers of 5,000 invoices" tone="good" />
            {r.policy_change && (
              <Kpi
                label="Policy-driven: wrong decisions"
                value={count(r.policy_change.variants.reduce((a, x) => a + (x.driven.invoices - x.driven.exact), 0))}
                hint={`in ${count(r.policy_change.variants.length * r.policy_change.invoices)} invoice audits`}
                tone="good"
              />
            )}
            {r.policy_change && (
              <Kpi
                label="Frozen thresholds: worst case"
                value={`${(Math.max(...r.policy_change.variants.map((x) => 1 - x.frozen.exact / x.frozen.invoices)) * 100).toFixed(1)}%`}
                hint="of invoices decided against the policy in force"
                tone="bad"
              />
            )}
            {r.scalability && <Kpi label="Throughput, 8 processes" value={`${count(r.scalability.by_workers[r.scalability.by_workers.length - 1].invoices_per_second)}/s`} hint="control stage, one laptop" />}
          </div>

          <Panel title="Detection on the benchmark ledgers" subtitle="Whole ledgers of 5,000 invoices, 8.4% anomalous. 95% bootstrap intervals. The classical detectors use thresholds chosen on other folds.">
            <div className="scroll-x">
              <table className="table">
                <thead>
                  <tr>
                    <th>Ledger</th>
                    <th>System</th>
                    <th>Recall</th>
                    <th>Precision</th>
                    <th>F1</th>
                    <th>FPR, ordinary</th>
                    <th>FPR, hard negatives</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(r.benchmark).flatMap(([ledger, data]) =>
                    SYSTEMS.map((s) => (
                      <tr key={`${ledger}-${s}`} className={s === "C1" ? "highlight" : ""}>
                        <td>{s === "C0-IF" ? ledger : ""}</td>
                        <td>{SYSTEM_NAME[s]}</td>
                        <td>{withInterval(data.metrics[s]?.detection_recall)}</td>
                        <td>{withInterval(data.metrics[s]?.detection_precision)}</td>
                        <td>{withInterval(data.metrics[s]?.detection_f1)}</td>
                        <td>{withInterval(data.metrics[s]?.fpr_ordinary)}</td>
                        <td>{withInterval(data.metrics[s]?.fpr_hard_negative)}</td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Share of each anomaly class detected" subtitle="Mean over the three benchmark ledgers. R1–R10 are decidable from field values; J1–J4 need reading or judgement and are the task of the agents.">
            <div className="scroll-x">
              <table className="table heat">
                <thead>
                  <tr>
                    <th>System</th>
                    {CLASSES.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {SYSTEMS.map((s) => (
                    <tr key={s}>
                      <td>{SYSTEM_NAME[s]}</td>
                      {CLASSES.map((c) => {
                        const vals = BENCH.map((d) => v(r.benchmark[d]?.per_class[s]?.[c])).filter((x): x is number => x !== null);
                        const mean = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
                        return (
                          <td key={c} style={{ background: heat(mean) }}>
                            {mean === null ? "–" : mean.toFixed(2)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {r.policy_change && (
            <Panel title="Policy change: policy-driven controls against frozen thresholds" subtitle={`${count(r.policy_change.invoices)} invoices of five ledgers under each of 14 policy documents. The policy-driven controls read the thresholds from each PDF; a frozen system keeps those of version 2.5.`}>
              <PolicyBars bars={r.policy_change.variants.map((x) => ({ label: x.name, value: 1 - x.frozen.exact / x.frozen.invoices, count: x.frozen.invoices - x.frozen.exact }))} />
              <div className="scroll-x">
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Policy</th>
                      <th className="num">Values read</th>
                      <th className="num">Decisions moved</th>
                      <th className="num">Policy-driven adherence</th>
                      <th className="num">Frozen adherence</th>
                      <th className="num">Missed escalations</th>
                      <th className="num">Needless escalations</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.policy_change.variants.map((x) => (
                      <tr key={x.version}>
                        <td>{x.name}</td>
                        <td className="num">
                          {x.parameters_read_correctly}/{x.parameters}
                        </td>
                        <td className="num">{count(x.affected)}</td>
                        <td className="num">{ratio(x.driven.exact / x.driven.invoices)}</td>
                        <td className="num">{ratio(x.frozen.exact / x.frozen.invoices)}</td>
                        <td className="num">{count(x.frozen.missed_escalations)}</td>
                        <td className="num">{count(x.frozen.needless_escalations)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          <div className="grid-2">
            {r.scalability && (
              <Panel title="Scalability of the control stage" subtitle={`300,000 invoice audits; ${r.scalability.logical_cpus} logical CPUs; median of three runs.`}>
                <ScalabilityChart points={r.scalability.by_workers} />
                <table className="table compact">
                  <thead>
                    <tr>
                      <th className="num">Ledger size</th>
                      <th className="num">Seconds</th>
                      <th className="num">µs per invoice</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.scalability.by_size.map((s) => (
                      <tr key={s.invoices}>
                        <td className="num">{count(s.invoices)}</td>
                        <td className="num">{s.seconds.toFixed(3)}</td>
                        <td className="num">{s.microseconds_per_invoice}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            )}
            {r.policy_reading && (
              <Panel title="Policies in their own wording" subtitle={`${r.policy_reading.model}, six documents in two styles. The model proposes; code verifies; a person confirms.`}>
                <div className="kpis small">
                  <Kpi label="Right and verified" value={r.policy_reading.total.right_verified} tone="good" />
                  <Kpi label="Right, held back" value={r.policy_reading.total.right_held_back} tone="accent" />
                  <Kpi label="Wrong, caught" value={r.policy_reading.total.wrong_caught} tone="warn" />
                  <Kpi label="Wrong, passed" value={r.policy_reading.total.wrong_passed} tone="bad" />
                </div>
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th className="num">Right, verified</th>
                      <th className="num">Wrong, passed</th>
                      <th className="num">Rules located</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.policy_reading.documents.map((d) => (
                      <tr key={d.file}>
                        <td className="mono small">{d.file}</td>
                        <td className="num">
                          {String(d.counts.right_verified)}/{String(d.counts.values)}
                        </td>
                        <td className="num">{String(d.counts.wrong_passed)}</td>
                        <td className="num">
                          {String(d.counts.located)}/{String(d.counts.rules)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted small">Out of {r.policy_reading.total.values} values, {r.policy_reading.total.values - r.policy_reading.total.wrong_caught - r.policy_reading.total.wrong_passed - r.policy_reading.total.missing} were proposed correctly.</p>
              </Panel>
            )}
          </div>

          <Panel title="Real-model pilots and sample" subtitle="Small samples with a local 7B model on a laptop CPU: pilots on the development ledger, and 34 invoices of benchmark ledger 101 that no prompt was tried on. They show that every stage works and what an invoice costs; they are too small to compare the configurations.">
            {Object.keys(r.pilots).length ? (
              <div className="scroll-x">
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Model</th>
                      <th className="num">Invoices</th>
                      <th className="num">Flagged</th>
                      <th className="num">Model calls</th>
                      <th className="num">Prompt tokens</th>
                      <th className="num">Failed stages</th>
                      <th>Routes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(r.pilots).map(([name, p]) => {
                      const s = p.summary as Record<string, number | Record<string, number>>;
                      return (
                        <tr key={name}>
                          <td>
                            {name} <Badge>{p.dataset?.startsWith("bench") ? "benchmark sample" : "pilot"}</Badge>
                          </td>
                          <td>{p.model ?? "none"}</td>
                          <td className="num">{String(s.invoices)}</td>
                          <td className="num">{String(s.invoices_flagged)}</td>
                          <td className="num">{String(s.llm_calls)}</td>
                          <td className="num">{count(s.prompt_tokens as number)}</td>
                          <td className="num">{String(s.failed_stages)}</td>
                          <td className="small">{Object.entries((s.routes as Record<string, number>) ?? {}).map(([k, n]) => `${k} ${n}`).join(" · ")}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>No pilot has been run.</Empty>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
