// Panels of the Overview page that read more than one endpoint: the forensic signals, the coverage of the
// latest results, the escalation queue and the activity of the audit trail.
import { Link } from "react-router-dom";
import type { ActivityRow, Coverage, KeySummary, Overview, QueueItem, VendorPoint } from "../api/types";
import { count, percent, riskColor, rupeesCompact } from "../lib/format";
import { Badge, Kpi, Panel, RiskMeter, RuleChips, StackedBar } from "./ui";

const CONFIG_COLORS: Record<string, string> = { C1: "#0f766e", C2: "#64748b", C3: "#7c3aed", C4: "#a855f7", C5: "#c026d3" };

function findingsOf(o: Overview, test: (rule: string) => boolean): number {
  return o.findings_by_rule.filter((f) => test(f.rule)).reduce((t, f) => t + f.findings, 0);
}

/** The signals the earlier dashboard led with, counted from the findings of the latest results. */
export function ForensicSignals({ o, vendors }: { o: Overview; vendors: VendorPoint[] | null }) {
  const flaggedVendors = vendors?.filter((v) => v.findings > 0).length;
  const blacklisted = vendors?.filter((v) => v.blacklisted).length;
  return (
    <div className="kpis eight signals">
      <Kpi label="Critical alerts" value={count(o.risk_levels.CRITICAL ?? 0)} hint="weighted risk 70 or more" tone="bad" />
      <Kpi label="Duplicates" value={count(findingsOf(o, (r) => r.startsWith("2.2.")))} hint="potential double payments (2.2)" tone="bad" />
      <Kpi label="Three-way match" value={count(findingsOf(o, (r) => r.startsWith("2.1.")))} hint="PO, receipt and invoice disagree (2.1)" tone="warn" />
      <Kpi label="Tax identity" value={count(findingsOf(o, (r) => r.startsWith("3.")))} hint="GSTIN format, state or owner (3.1)" tone="warn" />
      <Kpi label="Splitting & timing" value={count(findingsOf(o, (r) => r.startsWith("4.1.") || r.startsWith("4.2.") || r.startsWith("4.3.")))} hint="split, structured, weekend, round (4.1 to 4.3)" tone="warn" />
      <Kpi label="Approval & vendor" value={count(findingsOf(o, (r) => r.startsWith("5.") || r.startsWith("4.4.")))} hint="above limit or blocked vendor (5.1, 4.4)" tone="bad" />
      <Kpi label="Vendors with findings" value={flaggedVendors === undefined ? "–" : count(flaggedVendors)} hint={`of ${count(o.vendors)} vendors${blacklisted ? ` · ${count(blacklisted)} blacklisted` : ""}`} share={flaggedVendors === undefined ? undefined : flaggedVendors / Math.max(1, o.vendors)} />
      <Kpi label="Findings that did not hold payment" value={o.coverage ? count(o.coverage.approved_with_findings) : "–"} hint="medium or low alone stay under 50" tone={o.coverage?.approved_with_findings ? "warn" : "good"} />
    </div>
  );
}

function KeyRow({ name, k, total }: { name: string; k: KeySummary; total?: number }) {
  return (
    <tr>
      <td className="strong">{name}</td>
      {total !== undefined && <td className="num">{count(total)}</td>}
      <td className="num good-text">{count(k.found)}</td>
      <td className={`num ${k.false_alarms ? "bad-text strong" : ""}`}>{count(k.false_alarms)}</td>
      <td className={`num ${k.missed ? "warn-text strong" : ""}`}>{count(k.missed)}</td>
      <td className={`num ${k.not_checked ? "warn-text strong" : ""}`}>{count(k.not_checked)}</td>
      <td className="num">{k.precision === null ? "–" : k.precision.toFixed(3)}</td>
      <td className="num">{k.recall === null ? "–" : k.recall.toFixed(3)}</td>
    </tr>
  );
}

/** Which configurations produced the latest results, what they did not check and, on a benchmark ledger, how they compare with its answer key. */
export function CoveragePanel({ coverage, audited }: { coverage: Coverage; audited: number }) {
  const key = coverage.answer_key;
  const unchecked = audited - coverage.judgement_run;
  const notices: string[] = [];
  if (unchecked > 0 && coverage.judgement_clauses.length)
    notices.push(
      `${count(unchecked)} of ${count(audited)} invoices were audited without the language-model agents, so the judgement rules ${coverage.judgement_clauses.join(", ")} were not checked on them; an approval there means the controls found nothing, not that the invoice is clean.`,
    );
  if (coverage.approved_with_findings > 0)
    notices.push(`${count(coverage.approved_with_findings)} invoices have a finding but were approved: one medium (10) or low (5) finding alone cannot reach the threshold of 50.`);
  if (key?.false_alarms)
    notices.push(`${count(key.false_alarms)} invoices were flagged that the answer key marks as clean or as a legitimate look-alike (${count(key.hard_negatives_flagged)} look-alikes); see the configurations below.`);
  return (
    <Panel title="Audit coverage and quality" subtitle="What produced the numbers on this page. The latest result of each invoice comes from the configuration it was last audited with.">
      <div className="grid-2 flush">
        <div className="stack">
          <StackedBar
            label="Configuration of the latest results"
            parts={Object.entries(coverage.configurations).map(([c, n]) => ({ key: c, label: c, value: n, color: CONFIG_COLORS[c] ?? "#94a3b8" }))}
          />
          <div className="checks">
            <div>
              <span className="kpi-label">Deterministic controls</span>
              <strong>{count(coverage.controls_run)}</strong>
              <span className="muted small">of {count(audited)} invoices · {percent(coverage.controls_run / Math.max(1, audited), 1)}</span>
              <span className="check-bar"><i style={{ width: `${(coverage.controls_run / Math.max(1, audited)) * 100}%` }} /></span>
            </div>
            <div>
              <span className="kpi-label">Judgement rules (agents)</span>
              <strong>{count(coverage.judgement_run)}</strong>
              <span className="muted small">of {count(audited)} invoices · {percent(coverage.judgement_run / Math.max(1, audited), 1)}</span>
              <span className="check-bar warn"><i style={{ width: `${(coverage.judgement_run / Math.max(1, audited)) * 100}%` }} /></span>
            </div>
          </div>
          {notices.length > 0 && (
            <ul className="notices">
              {notices.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </div>
        <div>
          {key && key.found + key.false_alarms + key.missed + key.not_checked + key.passed === 0 ? (
            <p className="muted">
              The answer key of this benchmark describes policy v{key.policy_version}, and all {count(key.other_policy)} latest results were produced under another version, so
              none can be scored against it: a changed threshold makes an invoice anomalous or clean whatever the labels say.
            </p>
          ) : key ? (
            <>
              <span className="kpi-label">Against the benchmark's answer key (policy v{key.policy_version})</span>
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Results</th>
                    <th className="num">Invoices</th>
                    <th className="num">Found</th>
                    <th className="num">False alarms</th>
                    <th className="num">Missed</th>
                    <th className="num">Not checked</th>
                    <th className="num">Precision</th>
                    <th className="num">Recall</th>
                  </tr>
                </thead>
                <tbody>
                  <KeyRow name="All" k={key} total={audited} />
                  {Object.entries(key.by_configuration).map(([c, k]) => (
                    <KeyRow key={c} name={c} k={k} total={coverage.configurations[c]} />
                  ))}
                </tbody>
              </table>
              <p className="muted small">
                An anomaly is found when its invoice has any finding. "Not checked": its rule is a judgement rule and the configuration ran no agents.
                {key.other_policy > 0 && ` ${count(key.other_policy)} results under another policy version than v${key.policy_version} are left out.`} The answer key is part of the
                generated benchmark; a real ledger has none, and then this table is absent.
              </p>
            </>
          ) : (
            <p className="muted">This ledger has no answer key, so there is nothing to score the results against.</p>
          )}
        </div>
      </div>
    </Panel>
  );
}

/** The riskiest invoices waiting for a reviewer. */
export function EscalationPreview({ items, total, titles }: { items: QueueItem[]; total: number; titles: Record<string, string | null> }) {
  return (
    <Panel title="Escalation queue" subtitle={`${count(total)} invoices wait for a reviewer; the riskiest first.`} actions={<Link className="btn btn-ghost" to="/review">Open the queue</Link>}>
      <table className="table compact">
        <thead>
          <tr>
            <th>Invoice</th>
            <th>Vendor</th>
            <th className="num">Amount</th>
            <th>Risk</th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.result_id}>
              <td>
                <Link className="mono" to={`/invoice/${i.invoice_id}`}>
                  {i.invoice_id}
                </Link>
                <RuleChips rules={i.rules} titles={titles} />
              </td>
              <td>{i.vendor_name}</td>
              <td className="num">{rupeesCompact(i.amount)}</td>
              <td>
                <RiskMeter score={i.rc} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

const STAGE_TONE: Record<string, "neutral" | "accent" | "violet" | "warn" | "good"> = {
  extraction: "neutral", controls: "accent", agent: "violet", challenger: "violet", confidence: "violet", scoring: "good", review: "warn",
};

/** The newest steps written to the audit trail. */
export function ActivityLog({ rows }: { rows: ActivityRow[] }) {
  return (
    <Panel title="Activity" subtitle="The newest steps of the audit trail: what ran, who or what did it, and what it concluded.">
      <ol className="activity">
        {rows.map((r) => (
          <li key={r.entry_id}>
            <Badge tone={STAGE_TONE[r.stage] ?? "neutral"}>{r.stage}</Badge>
            <div>
              <span>
                <Link className="mono" to={`/invoice/${r.invoice_id}`}>
                  {r.invoice_id}
                </Link>{" "}
                <span className="muted">by {r.actor}</span>
              </span>
              <span className="muted small">{r.detail ?? ""}</span>
            </div>
            <time className="muted small">{r.created_at?.slice(0, 16) ?? ""}</time>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

/** The vendors with the highest risk and most findings. */
export function TopRiskVendors({ vendors }: { vendors: VendorPoint[] }) {
  const top = [...vendors].sort((a, b) => b.max_risk - a.max_risk || b.findings - a.findings || b.amount - a.amount).slice(0, 8);
  return (
    <Panel title="High-risk vendors" subtitle="By the highest weighted risk among their invoices, then by findings.">
      <table className="table compact">
        <thead>
          <tr>
            <th>Vendor</th>
            <th className="num">Invoices</th>
            <th className="num">Findings</th>
            <th className="num">Waiting</th>
            <th className="num">Risk</th>
          </tr>
        </thead>
        <tbody>
          {top.map((v) => (
            <tr key={v.vendor_id}>
              <td>
                <Link to={`/invoice?q=${encodeURIComponent(v.vendor_name)}`}>{v.vendor_name}</Link>
                <div className="muted small">
                  {v.category}
                  {v.blacklisted ? " · blacklisted" : ""}
                </div>
              </td>
              <td className="num">{count(v.invoices)}</td>
              <td className="num">{count(v.findings)}</td>
              <td className="num">{count(v.waiting)}</td>
              <td className="num">
                <span className="sev">
                  <i style={{ background: riskColor(v.max_risk) }} />
                  {v.max_risk.toFixed(0)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}
