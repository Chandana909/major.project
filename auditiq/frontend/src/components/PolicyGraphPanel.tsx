// The policy knowledge graph on the Policy page: the graph in 3D, asking it, and every relation as a table.
import { lazy, Suspense, useMemo, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { GraphAnswer, GraphNode } from "../api/types";
import { useApi } from "../lib/useApi";
import { EDGE_COLORS, NODE_COLORS, NODE_LABELS } from "../three/graphColors";
import { Badge, Empty, ErrorBox, Kpi, Loading, Panel } from "./ui";

const PolicyGraph3D = lazy(() => import("../three/PolicyGraph3D").then((m) => ({ default: m.PolicyGraph3D })));

const EXAMPLES = [
  "Who has to approve an invoice of ₹30 lakh?",
  "What changed between version 2.5 and 2.6?",
  "Is ₹4,99,000 suspicious and who approves it?",
  "Which rules does the Vendor Intelligence agent judge?",
  "List the critical rules",
];

const FACT_TONE: Record<string, "bad" | "warn" | "accent" | "violet" | "neutral" | "good"> = {
  routing: "warn", band: "bad", round: "neutral", limit: "warn", change: "violet", set: "accent", checker: "accent",
  rule: "neutral", parameter: "good",
};

function name(n: GraphNode | undefined, id: string): string {
  if (!n) return id;
  if (n.kind === "clause") return `Rule ${n.label} (${n.title})`;
  if (n.kind === "parameter") return `${n.label} of ${n.clause}`;
  return n.label;
}

export function PolicyGraphPanel({ versions }: { versions: string[] }) {
  const [version, setVersion] = useState<string | undefined>(undefined);
  const graph = useApi(() => api.policyGraph(version), [version]);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<GraphAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const g = graph.data;
  const byId = useMemo(() => new Map((g?.nodes ?? []).map((n) => [n.id, n])), [g]);
  const highlight = useMemo(() => (answer ? new Set(answer.nodes) : null), [answer]);

  const ask = async (q: string) => {
    const text = q.trim();
    if (!text) return;
    setQuestion(text);
    setAsking(true);
    setError(null);
    setSelected(null);
    try {
      setAnswer(await api.askGraph(text, g?.version));
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
  const relations = selected && g ? g.edges.filter((e) => e.source === selected || e.target === selected) : [];

  return (
    <Panel
      title="Policy knowledge graph"
      subtitle="The policy as a graph, built by code from the clause registry, the documents and the code that checks each rule: no model reads it. Ask a question that needs several facts (an amount and who may approve it, what changed between versions, what checks a rule) and the graph answers with the facts and the passages they come from."
      actions={
        versions.length > 1 ? (
          <select aria-label="Graph version" value={g?.version ?? ""} onChange={(e) => {
            setVersion(e.target.value);
            setAnswer(null);
            setSelected(null);
          }}>
            {versions.map((v) => (
              <option key={v} value={v}>
                v{v}
              </option>
            ))}
          </select>
        ) : undefined
      }
    >
      <ErrorBox error={graph.error} onRetry={graph.reload} />
      {!g && graph.loading && <Loading what="Building the graph" />}
      {g && (
        <>
          <div className="kpis small">
            <Kpi label="Rules" value={g.counts.clause ?? 0} hint={`${g.counts.section ?? 0} sections`} />
            <Kpi label="Parameters" value={g.counts.parameter ?? 0} hint={`${g.counts.role ?? 0} roles with limits`} />
            <Kpi label="Checked by" value={g.counts.checker ?? 0} hint="control functions and agents" />
            <Kpi label="Relations" value={g.edges.length} hint={`${g.edges.filter((e) => e.kind === "changes").length} changes in other versions`} />
          </div>
          <form className="search graph-ask" onSubmit={submit}>
            <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask the graph, e.g. who may approve ₹7,50,000?" aria-label="Question for the graph" />
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
          <ErrorBox error={error} />
          <div className="grid-2 wide-left flush graph-grid">
            <Suspense fallback={<Loading what="Laying out the graph" />}>
              <PolicyGraph3D nodes={g.nodes} edges={g.edges} highlight={highlight} selected={selected} onSelect={setSelected} />
            </Suspense>
            <div className="stack">
              {answer ? (
                <div>
                  <h3 className="sub">What the graph answers</h3>
                  {answer.facts.length ? (
                    <ol className="graph-facts">
                      {answer.facts.map((f, i) => (
                        <li key={i}>
                          <span className="fact-label">F{i + 1}</span>
                          <div>
                            <Badge tone={FACT_TONE[f.kind] ?? "neutral"}>{f.kind}</Badge> {f.text}
                            {f.source && <span className="cite">{f.source}</span>}
                          </div>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <Empty>The graph found nothing the question names. Try a rule number, an amount, a role, a version or an agent.</Empty>
                  )}
                  {answer.passages.length > 0 && (
                    <details>
                      <summary>The passages these facts cite ({answer.passages.length})</summary>
                      {answer.passages.map((h) => (
                        <article key={h.chunk_id} className="hit">
                          <strong>{h.source}</strong>
                          <p>{h.text}</p>
                        </article>
                      ))}
                    </details>
                  )}
                </div>
              ) : selected ? (
                <div>
                  <h3 className="sub">{name(byId.get(selected), selected)}</h3>
                  <ul className="relations">
                    {relations.map((e, i) => (
                      <li key={i}>
                        <i style={{ background: EDGE_COLORS[e.kind] ?? "#94a3b8" }} />
                        {e.source === selected ? (
                          <span>
                            <b>{e.kind}</b> {name(byId.get(e.target), e.target)}
                          </span>
                        ) : (
                          <span>
                            {name(byId.get(e.source), e.source)} <b>{e.kind}</b> this
                          </span>
                        )}
                        {e.label && <span className="muted"> · {e.label}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="muted small">Click a node to see its relations, or ask the graph a question to light the part of it that answers.</p>
              )}
            </div>
          </div>
          <div className="legend">
            {NODE_LABELS.map(([k, label]) => (
              <span key={k}>
                <i style={{ background: NODE_COLORS[k] }} /> {label}
              </span>
            ))}
          </div>
          <details>
            <summary>Every relation of v{g.version} as a table ({g.edges.length})</summary>
            <table className="table compact" aria-label="Relations of the policy graph">
              <thead>
                <tr>
                  <th>From</th>
                  <th>Relation</th>
                  <th>To</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                {g.edges.map((e, i) => (
                  <tr key={i}>
                    <td>{name(byId.get(e.source), e.source)}</td>
                    <td>{e.kind}</td>
                    <td>{name(byId.get(e.target), e.target)}</td>
                    <td className="muted">{e.label || "–"}</td>
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
