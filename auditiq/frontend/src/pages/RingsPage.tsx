import { lazy, Suspense, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Ring, RingEdge, RingNode, Rings, WatchPair } from "../api/types";
import { Badge, Empty, ErrorBox, Kpi, Loading, Panel, RuleChips } from "../components/ui";
import { count, inr, riskColor, rupeesCompact } from "../lib/format";
import { useApi } from "../lib/useApi";
import { LINK_COLORS } from "../three/linkColors";

const RingNetwork = lazy(() => import("../three/RingNetwork").then((m) => ({ default: m.RingNetwork })));

const LINK_HELP: Record<string, string> = {
  "shared PAN": "two vendor records with the same PAN: one legal entity registered twice",
  "shared GSTIN": "two vendor records with the same GST registration",
  "another vendor's GSTIN": "an invoice of one vendor carries the registration of another",
  "repeated findings": "the approver approved more of the vendor's invoices with high or critical findings than approvers of the same role do",
  "above own limit": "among those findings, approvals above the approver's own limit",
  "approver hotspot": "the approver's approvals as a whole carry more high or critical findings than the role's rate allows",
  "concentrated approvals": "one approver approved a large share of the vendor's invoices",
  "unusual approvals": "a pair on the watch list: unusual, but below significance",
};

/** q and p values: three significant digits, or "< 0.0001". */
function prob(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return value < 1e-4 ? "< 0.0001" : value.toPrecision(2);
}

function LinkChips({ kinds }: { kinds: Record<string, number> }) {
  return (
    <span className="link-chips">
      {Object.entries(kinds).map(([k, n]) => (
        <span key={k} className="link-chip" title={LINK_HELP[k]}>
          <i style={{ background: LINK_COLORS[k] ?? "#94a3b8" }} />
          {k} {n > 1 && <b>×{n}</b>}
        </span>
      ))}
    </span>
  );
}

function rulesOf(rules: Record<string, number>): string[] {
  return Object.entries(rules)
    .sort((a, b) => b[1] - a[1])
    .map(([r]) => r);
}

function GroupCard({ group, prefix, active, onClick }: { group: Ring; prefix: string; active: boolean; onClick: () => void }) {
  return (
    <button className={`ring-card ${active ? "active" : ""}`} onClick={onClick} aria-pressed={active}>
      <span className="ring-card-head">
        <span className="ring-id">
          {prefix}
          {group.id}
        </span>
        <strong>{rupeesCompact(group.flagged_amount)}</strong>
        <span className="muted small">with findings</span>
        <span className="risk-dot" style={{ background: riskColor(group.max_risk) }} title={`highest risk ${group.max_risk.toFixed(0)}`} />
      </span>
      <span className="ring-card-body">
        {count(group.vendors.length)} vendor{group.vendors.length === 1 ? "" : "s"} · {count(group.approvers.length)} approver{group.approvers.length === 1 ? "" : "s"} ·{" "}
        {count(group.flagged_invoices)} invoice{group.flagged_invoices === 1 ? "" : "s"}
        {group.blacklisted > 0 && <Badge tone="violet">{group.blacklisted} blacklisted</Badge>}
      </span>
      <LinkChips kinds={group.link_kinds} />
    </button>
  );
}

function GroupDetail({ group, nodes, edges }: { group: Ring; nodes: RingNode[]; edges: RingEdge[] }) {
  const vendors = nodes.filter((n) => n.ring === group.id && n.kind === "vendor");
  const approvers = nodes.filter((n) => n.ring === group.id && n.kind === "approver");
  const names = new Map(nodes.map((n) => [n.id, n.label ?? n.id]));
  const links = edges.filter((e) => e.ring === group.id);
  return (
    <div className="stack">
      <div className="kpis small">
        <Kpi label="Money with findings" value={rupeesCompact(group.flagged_amount)} tone="bad" />
        <Kpi label="Invoices with findings" value={count(group.flagged_invoices)} />
        <Kpi label="Vendors' total spend" value={rupeesCompact(group.amount)} />
        <Kpi label="Waiting for review" value={count(group.waiting)} tone="warn" />
      </div>
      <div className="grid-2 flush">
        <div>
          <h3 className="sub">Vendors</h3>
          <table className="table compact">
            <thead>
              <tr>
                <th>Vendor</th>
                <th className="num">Invoices</th>
                <th className="num">Spend</th>
                <th className="num">Findings</th>
                <th className="num">Top approver</th>
                <th className="num">Risk</th>
              </tr>
            </thead>
            <tbody>
              {vendors.map((v) => (
                <tr key={v.id}>
                  <td>
                    <Link to={`/invoice?q=${encodeURIComponent(v.label ?? v.vendor_id ?? "")}`}>{v.label}</Link>
                    <div className="muted small">
                      {v.vendor_id} · {v.category}
                      {v.blacklisted && " · blacklisted"}
                    </div>
                  </td>
                  <td className="num">{count(v.invoices ?? 0)}</td>
                  <td className="num">{rupeesCompact(v.amount ?? 0)}</td>
                  <td className="num">{count(v.flagged ?? 0)}</td>
                  <td className="num">{v.top_approver_share == null ? "–" : `${(v.top_approver_share * 100).toFixed(0)}%`}</td>
                  <td className="num">
                    <span className="sev">
                      <i style={{ background: riskColor(v.max_risk ?? 0) }} />
                      {(v.max_risk ?? 0).toFixed(0)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h3 className="sub">Approvers</h3>
          {approvers.length ? (
            <table className="table compact">
              <thead>
                <tr>
                  <th>Approver</th>
                  <th>Role</th>
                  <th className="num">Own limit</th>
                </tr>
              </thead>
              <tbody>
                {approvers.map((a) => (
                  <tr key={a.id}>
                    <td className="strong">{a.label}</td>
                    <td>{a.role ?? "–"}</td>
                    <td className="num">{a.limit == null ? "–" : `₹${inr(a.limit)}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>The vendors are bound by identity alone.</Empty>
          )}
          <h3 className="sub">Rules broken on the links</h3>
          <RuleChips rules={rulesOf(group.rules)} />
          <p className="muted small">
            {Object.entries(group.rules)
              .map(([r, n]) => `${r} ×${n}`)
              .join(" · ") || "none: identity links only"}
          </p>
        </div>
      </div>
      <h3 className="sub">Links</h3>
      <table className="table compact">
        <thead>
          <tr>
            <th>From</th>
            <th>To</th>
            <th>Why</th>
            <th className="num">Invoices</th>
            <th className="num">Amount</th>
            <th>Rules</th>
          </tr>
        </thead>
        <tbody>
          {links.map((e) => (
            <tr key={`${e.source}-${e.target}`}>
              <td>{names.get(e.source)}</td>
              <td>{names.get(e.target)}</td>
              <td>
                <LinkChips kinds={Object.fromEntries(e.kinds.map((k) => [k, 1]))} />
              </td>
              <td className="num">{count(e.invoices)}</td>
              <td className="num">{e.amount ? rupeesCompact(e.amount) : "–"}</td>
              <td>
                <RuleChips rules={rulesOf(e.rules)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The 3D network of a set of groups, their list, and the group chosen. */
function Network({ title, subtitle, prefix, groups, nodes, edges, listTitle }: {
  title: string;
  subtitle: string;
  prefix: string;
  groups: Ring[];
  nodes: RingNode[];
  edges: RingEdge[];
  listTitle: string;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const group = groups.find((g) => g.id === selected) ?? null;
  const kinds = useMemo(() => [...new Set(edges.flatMap((e) => e.kinds))], [edges]);
  return (
    <>
      <div className="grid-2 wide-left">
        <Panel title={title} subtitle={subtitle}>
          <Suspense fallback={<Loading what="Laying out the network" />}>
            <RingNetwork nodes={nodes} edges={edges} selected={selected} onSelect={setSelected} />
          </Suspense>
          <div className="legend">
            {kinds.map((k) => (
              <span key={k} title={LINK_HELP[k]}>
                <i style={{ background: LINK_COLORS[k] ?? "#94a3b8" }} /> {k}
              </span>
            ))}
          </div>
        </Panel>
        <Panel title={listTitle} subtitle="Most money with findings on the links first." className="ring-list-panel">
          <div className="ring-list">
            {groups.map((g) => (
              <GroupCard key={g.id} group={g} prefix={prefix} active={g.id === selected} onClick={() => setSelected(g.id === selected ? null : g.id)} />
            ))}
          </div>
        </Panel>
      </div>
      {group && (
        <Panel
          title={`${prefix === "R" ? "Ring" : "Lead"} ${prefix}${group.id}`}
          subtitle={`${group.vendor_names.join(", ")}${group.approvers.length ? ` · approved by ${group.approvers.join(", ")}` : ""}`}
          actions={
            <button className="btn btn-ghost" onClick={() => setSelected(null)}>
              Show all
            </button>
          }
        >
          <GroupDetail group={group} nodes={nodes} edges={edges} />
        </Panel>
      )}
    </>
  );
}

function WatchList({ watch, fdr }: { watch: WatchPair[]; fdr: number }) {
  return (
    <div className="table-wrap">
      <table className="table sticky compact">
        <thead>
          <tr>
            <th>Approver</th>
            <th>Vendor</th>
            <th className="num">With findings</th>
            <th className="num">Expected</th>
            <th className="num">p</th>
            <th className="num">q (FDR)</th>
            <th>Rules</th>
            <th className="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {watch.map((w) => (
            <tr key={`${w.approver}-${w.vendor_id}`} className={w.significant ? "highlight" : ""}>
              <td>
                <span className="strong">{w.approver}</span>
                <div className="muted small">{w.role ?? "role unknown"}</div>
              </td>
              <td>
                <Link to={`/invoice?q=${encodeURIComponent(w.vendor_name ?? w.vendor_id)}`}>{w.vendor_name ?? w.vendor_id}</Link>
              </td>
              <td className="num strong">
                {count(w.flagged)} of {count(w.invoices)}
              </td>
              <td className="num">{w.expected.toFixed(2)}</td>
              <td className="num">{prob(w.p)}</td>
              <td className={`num ${w.q <= fdr ? "bad-text strong" : ""}`}>{prob(w.q)}</td>
              <td>
                <RuleChips rules={rulesOf(w.rules)} />
              </td>
              <td className="num">{rupeesCompact(w.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Tests({ d }: { d: Rings }) {
  const t = d.tests;
  return (
    <div className="grid-2 flush">
      <div>
        <h3 className="sub">Rate of each role</h3>
        <table className="table compact">
          <thead>
            <tr>
              <th>Role</th>
              <th className="num">Invoices approved</th>
              <th className="num">With high or critical findings</th>
              <th className="num">Rate</th>
            </tr>
          </thead>
          <tbody>
            {t.role_rates.map((r) => (
              <tr key={r.role ?? "none"}>
                <td className="strong">{r.role ?? "unknown"}</td>
                <td className="num">{count(r.invoices)}</td>
                <td className="num">{count(r.flagged)}</td>
                <td className="num">{(r.rate * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="facts">
        <div>
          <dt>Approver-vendor pairs tested</dt>
          <dd>
            {count(t.pairs_tested)} with two invoices or more; {count(t.pairs_with_findings)} have two findings or more; {count(t.pairs_significant)} pass
          </dd>
        </div>
        <div>
          <dt>Approvers tested</dt>
          <dd>
            {count(t.approvers_tested)}; {count(t.hotspots)} hotspot{t.hotspots === 1 ? "" : "s"} (lowest q {prob(t.min_q_approver)})
          </dd>
        </div>
        <div>
          <dt>Lowest q-value of a pair</dt>
          <dd>
            {prob(t.min_q_pair)} · a link needs {t.fdr} or less
          </dd>
        </div>
        <div>
          <dt>Procedure</dt>
          <dd>one-sided binomial test against the role's rate; Benjamini-Hochberg over each family of tests</dd>
        </div>
      </dl>
    </div>
  );
}

export function RingsPage() {
  const data = useApi(() => api.rings(40));
  const d = data.data;
  const members = d ? new Set(d.nodes.filter((n) => n.kind === "vendor").map((n) => n.id)).size : 0;
  const approvers = d ? new Set(d.nodes.filter((n) => n.kind === "approver").map((n) => n.id)).size : 0;
  const atStake = d ? d.rings.reduce((t, r) => t + r.flagged_amount, 0) : 0;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Intelligence · Vendor collusion</span>
          <h1>Vendor collusion rings</h1>
          <p className="muted">
            Vendors and approvers tied together by shared identities and by approvals that carry more serious findings than chance allows. Every approval link is tested
            against the rate of the approver's role and must survive a false-discovery-rate correction. A ring is a lead for an investigation, not a finding; the audit packs of
            its invoices say what is wrong.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/analytics">
            Analytics
          </Link>
        </div>
      </header>

      <ErrorBox error={data.error} onRetry={data.reload} />
      {!d && data.loading && <Loading what="Testing every approver and vendor" />}

      {d && (
        <>
          <div className="kpis eight">
            <Kpi label="Rings" value={count(d.total_rings)} hint={d.total_rings ? `${count(members)} vendors · ${count(approvers)} approvers` : `none passes at FDR ${d.tests.fdr}`} tone={d.total_rings ? "bad" : "good"} />
            <Kpi label="Pairs tested" value={count(d.tests.pairs_tested)} hint={`${count(d.tests.pairs_with_findings)} with two findings or more`} />
            <Kpi label="Approvers tested" value={count(d.tests.approvers_tested)} hint={`${count(d.tests.hotspots)} hotspots`} tone={d.tests.hotspots ? "bad" : "default"} />
            <Kpi label="Most unusual pair" value={prob(d.tests.min_q_pair)} hint={`q-value; ${d.tests.fdr} needed`} tone="accent" />
            <Kpi label="Money on ring links" value={rupeesCompact(atStake)} hint={d.total_rings ? "invoices with findings" : "no ring"} />
            <Kpi label="Shared PAN" value={count(d.identity.shared_pan)} hint="pairs of vendor records" tone={d.identity.shared_pan ? "bad" : "good"} />
            <Kpi label="Shared GSTIN" value={count(d.identity.shared_gstin)} hint={`${count(d.identity.another_vendors_gstin)} invoices with another vendor's`} tone={d.identity.shared_gstin ? "bad" : "good"} />
            <Kpi label="GSTIN mismatches" value={count(d.identity.gstin_mismatches)} hint="invoice GSTIN is not the vendor's" tone={d.identity.gstin_mismatches ? "warn" : "good"} />
          </div>

          {d.rings.length > 0 ? (
            <Network
              title="Collusion network"
              subtitle="Spheres are vendors, coloured by their highest risk and sized by spend; white diamonds are approvers. Lines are links, coloured by kind. Click a member to open its ring; click the floor to see them all."
              prefix="R"
              groups={d.rings}
              nodes={d.nodes}
              edges={d.edges}
              listTitle={`Rings (${count(d.total_rings)})`}
            />
          ) : (
            <>
              <div className="banner subtle" role="note">
                <span>
                  <strong>No ring passes the tests.</strong> {count(d.tests.pairs_tested)} approver-vendor pairs and {count(d.tests.approvers_tested)} approvers were tested against
                  the rate of their role, and no vendor shares a PAN or GSTIN with another. The lowest q-value of a pair is {prob(d.tests.min_q_pair)}; a link needs {d.tests.fdr} or
                  less. Below are the {count(d.watch.length)} most unusual pairs as leads: where to look first, none of them significant.
                </span>
              </div>
              {d.leads.groups.length > 0 && (
                <Network
                  title="Leads below significance"
                  subtitle="The most unusual approver-vendor pairs, grouped where they share an approver or a vendor. Spheres are vendors, diamonds approvers."
                  prefix="L"
                  groups={d.leads.groups}
                  nodes={d.leads.nodes}
                  edges={d.leads.edges}
                  listTitle={`Leads (${count(d.leads.groups.length)})`}
                />
              )}
            </>
          )}

          <Panel title="Watch list" subtitle={`The ${count(d.watch.length)} approver-vendor pairs whose findings are least likely by chance, with what the approver's role makes likely. A highlighted row passes at FDR ${d.tests.fdr}.`}>
            {d.watch.length ? <WatchList watch={d.watch} fdr={d.tests.fdr} /> : <Empty>No approver approved two invoices with findings of one vendor.</Empty>}
          </Panel>

          <Panel title="The tests" subtitle="An approver is compared with others of the same role: a policy that gives a role a lower limit makes its approvals break the rules more often, which says nothing about collusion.">
            <Tests d={d} />
          </Panel>

          <div className="grid-2">
            <Panel title="Single-vendor groups" subtitle={`A vendor and the approvers linked to it, without a second vendor. ${count(d.total_pairs)} in the ledger.`}>
              {d.pairs.length ? (
                <table className="table compact">
                  <thead>
                    <tr>
                      <th>Vendor</th>
                      <th>Approvers</th>
                      <th>Why</th>
                      <th className="num">Invoices</th>
                      <th className="num">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.pairs.slice(0, 15).map((p) => (
                      <tr key={p.vendor_id}>
                        <td>
                          <Link to={`/invoice?q=${encodeURIComponent(p.vendor_name ?? p.vendor_id)}`}>{p.vendor_name}</Link>
                        </td>
                        <td>{p.approvers.map((a, i) => `${a}${p.roles[i] ? ` (${p.roles[i]})` : ""}`).join(", ")}</td>
                        <td>
                          <LinkChips kinds={p.link_kinds} />
                        </td>
                        <td className="num">{count(p.flagged_invoices)}</td>
                        <td className="num">{rupeesCompact(p.flagged_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <Empty>None: no link passes the tests around a single vendor either.</Empty>
              )}
            </Panel>
            <Panel title="How rings are found" subtitle="Every link is computed from the ledger and the latest audit results; nothing is inferred by a model.">
              <ul className="method">
                {d.method.links.map((k) => (
                  <li key={k}>
                    <span className="link-chip">
                      <i style={{ background: LINK_COLORS[k] ?? "#94a3b8" }} />
                      {k}
                    </span>
                    {LINK_HELP[k]}
                    {k === "concentrated approvals" && ` (at least ${Math.round(d.method.concentration_share * 100)}% of at least ${d.method.concentration_min} invoices)`}
                    {k === "above own limit" && d.method.limit_clause && ` (rule ${d.method.limit_clause})`}
                  </li>
                ))}
              </ul>
              <p className="muted small">
                Approval links must pass a one-sided binomial test against the rate of the approver's role, corrected by Benjamini-Hochberg at a false discovery rate of{" "}
                {d.method.fdr} over all pairs with at least {d.method.repeated} invoices, and over all approvers. A ring is a connected group with at least two vendors. The identity
                checks cover all {count(d.identity.vendors)} vendor records.
              </p>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
