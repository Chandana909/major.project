// The audited ledger as a knowledge graph on the Knowledge graph page: the graph in 3D, asking it, and every relation as a table.
import { lazy, Suspense, useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { CaseAnswer, CaseNode } from "../api/types";
import { count, rupeesCompact } from "../lib/format";
import { useApi } from "../lib/useApi";
import { CASE_EDGE_COLORS, CASE_NODE_LABELS } from "../three/caseLayout";
import { Badge, Empty, ErrorBox, Kpi, Loading, Panel } from "./ui";

const CaseGraph3D = lazy(() => import("../three/CaseGraph3D").then((m) => ({ default: m.CaseGraph3D })));

const EXAMPLES = [
  "Which vendors are in collusion rings and who approves their invoices?",
  "Which approvers approved the most invoices above their own limit?",
  "Which vendors share the same PAN?",
  "Tell me about blacklisted vendors",
  "Which vendors have number mismatches between invoice and PO?",
];

const FACT_TONE: Record<string, "bad" | "warn" | "accent" | "violet" | "neutral" | "good"> = {
  ring: "violet", rings: "violet", identity: "violet", approver: "warn", approvers: "warn", vendor: "accent", vendors: "bad",
  invoice: "neutral", rule: "bad", overview: "good",
};

function title(n: CaseNode | undefined, id: string): string {
  return n ? n.label : id;
}

function summary(n: CaseNode): string {
  switch (n.kind) {
    case "vendor":
      return `${n.category ?? ""} · ${count(n.flagged ?? 0)} of ${count(n.invoices ?? 0)} invoices with findings · ${rupeesCompact(n.amount ?? 0)}${n.blacklisted ? " · blacklisted" : ""}`;
    case "approver":
      return `${n.role ?? ""} · ${count(n.flagged ?? 0)} approvals with findings · ${count(n.over_limit ?? 0)} above the limit`;
    case "rule":
      return `${n.severity} · ${count(n.invoices ?? 0)} invoices break it`;
    case "invoice":
      return `${rupeesCompact(n.amount ?? 0)} · score ${(n.risk ?? 0).toFixed(0)} (${n.level}) · ${n.route}`;
    default:
      return `${n.vendors ?? 0} vendors, ${n.approvers ?? 0} approvers · ${rupeesCompact(n.amount ?? 0)} with findings`;
  }
}

export function CaseGraphPanel() {
  const [focus, setFocus] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const graph = useApi(() => api.caseGraph(focus ?? undefined), [focus]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<CaseAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const g = graph.data;
  const byId = useMemo(() => new Map((g?.nodes ?? []).map((n) => [n.id, n])), [g]);
  const highlight = useMemo(() => (answer ? new Set(answer.nodes) : null), [answer]);
  const picked = selected ? byId.get(selected) : undefined;
  const relations = selected && g ? g.edges.filter((e) => e.source === selected || e.target === selected) : [];

  const open = (id: string | null) => {
    setFocus(id);
    setSelected(null);
    setAnswer(null);
  };
  const ask = async (q: string) => {
    const text = q.trim();
    if (!text) return;
    setQuestion(text);
    setAsking(true);
    setError(null);
    setSelected(null);
    try {
      const found = await api.askCaseGraph(text);
      setAnswer(found);
      // What the question names may not be in the picture: show the first node it names.
      if (found.nodes.length && !found.nodes.some((id) => byId.has(id))) setFocus(found.nodes[0]);
    } catch (err) {
      setError(err as Error);
    } finally {
      setAsking(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(question);
  };
  const find = (e: FormEvent) => {
    e.preventDefault();
    if (typed.trim()) open(typed.trim());
  };

  return (
    <Panel
      title="Audit knowledge graph"
      subtitle="What the audit found, as a graph: which vendor billed which invoice, which rule it breaks, who approved it, which vendors share an identity and which rings they form. Built by code from the audit results; no model reads it. Ask it about vendors, invoices, approvers or kinds of fraud and the facts come with the numbers they rest on. Ask AI gets the same facts."
    >
      <ErrorBox error={graph.error} onRetry={graph.reload} />
      {!g && graph.loading && <Loading what="Building the graph from the audit" />}
      {g && (
        <>
          <div className="kpis small">
            <Kpi label="Vendors" value={g.counts.vendors ?? 0} hint="billing the ledger" />
            <Kpi label="Invoices with findings" value={g.counts.invoices_with_findings ?? 0} hint={`${count(g.counts.findings ?? 0)} findings`} />
            <Kpi label="Approvers" value={g.counts.approvers ?? 0} hint="who approved the payments" />
            <Kpi label="Rings" value={g.counts.rings ?? 0} hint={`policy v${g.policy_version}`} />
          </div>
          <form className="search graph-ask" onSubmit={submit}>
            <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask the ledger, e.g. which vendors share a PAN?" aria-label="Question for the ledger graph" />
            <button className="btn btn-primary" type="submit" disabled={asking || !question.trim()}>
              Ask the graph
            </button>
            {answer && (
              <button className="btn btn-ghost" type="button" onClick={() => setAnswer(null)}>
                Clear
              </button>
            )}
          </form>
          <div className="examples">
            {EXAMPLES.map((x) => (
              <button key={x} type="button" className="chip" onClick={() => void ask(x)}>
                {x}
              </button>
            ))}
          </div>
          <form className="search graph-ask" onSubmit={find}>
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Open a vendor, invoice, approver, ring or rule: INV53478, Frado Deep, g:3, 5.1.1" aria-label="Open a node of the ledger graph" />
            <button className="btn" type="submit" disabled={!typed.trim()}>
              Open
            </button>
            {focus && (
              <button className="btn btn-ghost" type="button" onClick={() => open(null)}>
                Back to the rings
              </button>
            )}
          </form>
          <ErrorBox error={error} />
          <p className="muted small">
            {focus ? `Neighbourhood of ${g.focus_kind ?? "the node"} ${focus}` : "The rings of the ledger with the vendors and approvers in them"}: {g.nodes.length} nodes, {g.edges.length} relations
            {g.truncated ? " (the largest part is drawn)" : ""}.
          </p>
          <div className="grid-2 wide-left flush graph-grid">
            <Suspense fallback={<Loading what="Laying out the graph" />}>
              <CaseGraph3D nodes={g.nodes} edges={g.edges} highlight={highlight} selected={selected} onSelect={setSelected} />
            </Suspense>
            <div className="stack">
              {answer ? (
                <div>
                  <h3 className="sub">What the graph answers</h3>
                  {answer.facts.length ? (
                    <ol className="graph-facts">
                      {answer.facts.map((f, i) => (
                        <li key={i}>
                          <span className="fact-label">C{i + 1}</span>
                          <div>
                            <Badge tone={FACT_TONE[f.kind] ?? "neutral"}>{f.kind}</Badge> {f.text}
                          </div>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <Empty>The graph found nothing the question names. Try an invoice number, a vendor, an approver, a rule number, or words such as collusion, mismatch, blacklisted.</Empty>
                  )}
                </div>
              ) : picked ? (
                <div>
                  <h3 className="sub">{title(picked, picked.id)}</h3>
                  <p className="muted small">{summary(picked)}</p>
                  <button className="btn" type="button" onClick={() => open(picked.id)}>
                    Open its neighbourhood
                  </button>
                  <ul className="relations">
                    {relations.map((e, i) => (
                      <li key={i}>
                        <i style={{ background: CASE_EDGE_COLORS[e.kind] ?? "#94a3b8" }} />
                        {e.source === selected ? (
                          <span>
                            <b>{e.kind}</b> {title(byId.get(e.target), e.target)}
                          </span>
                        ) : (
                          <span>
                            {title(byId.get(e.source), e.source)} <b>{e.kind}</b> this
                          </span>
                        )}
                        {e.count ? <span className="muted"> · ×{e.count}</span> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="muted small">Click a node to see its relations, ask the graph a question to light the part that answers, or open a vendor, an invoice, an approver, a ring or a rule.</p>
              )}
            </div>
          </div>
          <div className="legend">
            {CASE_NODE_LABELS.map(([k, label]) => (
              <span key={k}>{label}</span>
            ))}
            {Object.entries(CASE_EDGE_COLORS).map(([k, color]) => (
              <span key={k}>
                <i style={{ background: color }} /> {k}
              </span>
            ))}
          </div>
          <details>
            <summary>Every relation drawn as a table ({g.edges.length})</summary>
            <table className="table compact" aria-label="Relations of the ledger graph">
              <thead>
                <tr>
                  <th>From</th>
                  <th>Relation</th>
                  <th>To</th>
                </tr>
              </thead>
              <tbody>
                {g.edges.map((e, i) => (
                  <tr key={i}>
                    <td>{title(byId.get(e.source), e.source)}</td>
                    <td>{e.kind}{e.count ? ` ×${e.count}` : ""}</td>
                    <td>{title(byId.get(e.target), e.target)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </Panel>
  );
}
