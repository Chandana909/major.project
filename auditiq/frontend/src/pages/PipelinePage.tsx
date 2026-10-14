import { useState } from "react";
import { api } from "../api/client";
import type { ConfigName } from "../api/types";
import { Badge, ErrorBox, Loading, Panel } from "../components/ui";
import { useApi } from "../lib/useApi";
import { PipelineScene } from "../three/PipelineScene";

const ABOUT: Record<ConfigName, string> = {
  C1: "Controls only. The twelve deterministic controls, configured by the policy document, decide every rule that a comparison of fields can decide. No model is called.",
  C2: "One prompt over the whole policy, with no controls and no verification: the single-LLM setting that AuditBench evaluates.",
  C3: "Controls first, then three specialist agents, each limited to the rules that need reading. Count-based score.",
  C4: "C3 plus a challenger that removes agent findings the evidence does not support.",
  C5: "C4 plus evidence-grounded confidence: grounding, clause validity and agreement over three re-runs weight each finding.",
};

export function PipelinePage() {
  const pipeline = useApi(() => api.pipeline());
  const [config, setConfig] = useState<ConfigName>("C5");
  const p = pipeline.data;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>The pipeline</h1>
          <p className="muted">Five configurations built from the same stages. Teal stages are code, violet stages call a language model, amber is a person.</p>
        </div>
      </header>
      <ErrorBox error={pipeline.error} onRetry={pipeline.reload} />
      {!p && pipeline.loading && <Loading />}
      {p && (
        <>
          <div className="tabs" role="tablist" aria-label="Configuration">
            {(Object.keys(p.configurations) as ConfigName[]).map((c) => (
              <button key={c} role="tab" aria-selected={config === c} className={config === c ? "active" : ""} onClick={() => setConfig(c)}>
                {c}
              </button>
            ))}
          </div>
          <Panel title={`Configuration ${config}`} subtitle={ABOUT[config]}>
            <PipelineScene stages={p.stages} active={p.configurations[config]} />
            <ol className="stage-list">
              {p.configurations[config].map((id) => {
                const s = p.stages.find((x) => x.id === id);
                if (!s) return null;
                return (
                  <li key={id}>
                    <Badge tone={s.kind === "llm" ? "violet" : s.kind === "person" ? "warn" : "accent"}>{s.kind === "llm" ? "model" : s.kind}</Badge> {s.label}
                    {s.feature && <span className="feature-tag">the extra feature</span>}
                  </li>
                );
              })}
            </ol>
          </Panel>
        </>
      )}
    </div>
  );
}
