import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { CaseGraphPanel } from "../components/CaseGraphPanel";
import { PolicyGraphPanel } from "../components/PolicyGraphPanel";
import { ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/useApi";

type View = "policy" | "ledger";

export function GraphPage() {
  const policy = useApi(() => api.policy());
  const [view, setView] = useState<View>("policy");
  const p = policy.data;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Knowledge layer · Knowledge graph</span>
          <h1>Knowledge graph</h1>
          <p className="muted">
            Two graphs, both built by code with no model reading them. The policy graph holds what the rules say; the audit graph holds what the audit found: vendors, invoices, the
            rules they break, approvers and rings. Ask either a question that joins several facts and the part of the graph that answers lights up, with the facts and the numbers they rest
            on. The same facts go to the model in Ask AI.
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/rag">Trace retrieval</Link>
          <Link className="btn btn-primary" to="/ask">Ask AI</Link>
        </div>
      </header>
      <div className="tabs" role="tablist" aria-label="Which graph">
        <button role="tab" aria-selected={view === "policy"} className={`tab ${view === "policy" ? "active" : ""}`} onClick={() => setView("policy")}>
          Policy graph
        </button>
        <button role="tab" aria-selected={view === "ledger"} className={`tab ${view === "ledger" ? "active" : ""}`} onClick={() => setView("ledger")}>
          Audit findings graph
        </button>
      </div>
      {view === "policy" && (
        <>
          <ErrorBox error={policy.error} onRetry={policy.reload} />
          {!p && policy.loading && <Loading what="Reading the policy" />}
          {p && p.active && <PolicyGraphPanel versions={p.versions.map((v) => v.version)} />}
        </>
      )}
      {view === "ledger" && <CaseGraphPanel />}
    </div>
  );
}
