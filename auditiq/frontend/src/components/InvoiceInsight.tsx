// The invoice page's explanations: the risk screen's SHAP waterfall, the counterfactuals of each control finding,
// and the story of the invoice. Each loads on its own, so the page shows the audit at once.
import { useState } from "react";
import { api } from "../api/client";
import type { Counterfactual, CounterfactualOption, EmailVerdict, Explanation } from "../api/types";
import { useApi } from "../lib/useApi";
import { Badge, Empty, ErrorBox, Loading, Panel, SeverityBadge } from "./ui";
import { ShapWaterfall, StoryTimeline } from "./xai";

const RISK_TONE = { high: "bad", medium: "warn", low: "accent", none: "neutral" } as const;

/** The triage risk of a vendor e-mail. */
export function RiskBadge({ risk }: { risk: EmailVerdict["risk"] }) {
  return <Badge tone={RISK_TONE[risk]}>{risk === "none" ? "no risk" : `${risk} risk`}</Badge>;
}

// Both explanation panels read the same answer: one request per invoice, kept for half a minute.
const asked = new Map<string, { at: number; answer: Promise<Explanation> }>();
function explainOnce(id: string): Promise<Explanation> {
  const kept = asked.get(id);
  if (kept && Date.now() - kept.at < 30000) return kept.answer;
  const answer = api.explain(id);
  asked.set(id, { at: Date.now(), answer });
  answer.catch(() => asked.delete(id));
  return answer;
}

export function ScreenPanel({ id }: { id: string }) {
  const explained = useApi(() => explainOnce(id), [id]);
  const [head, setHead] = useState<string | null>(null);
  const e = explained.data;
  const heads = e?.screen?.heads;
  const chosen = head ?? "any";
  return (
    <Panel
      title="Why the risk screen scores this invoice"
      subtitle="SHAP values: how much each feature moves the screen's output from the average invoice (base) to this one, in log-odds; red pushes toward an anomaly, blue away. They add up to the output exactly. A score is a second opinion, not a finding."
    >
      {explained.loading && !e && <Loading what="Explaining" />}
      <ErrorBox error={explained.error} onRetry={explained.reload} />
      {e && !heads && <Empty>No risk screen is trained (python -m auditiq model train).</Empty>}
      {heads && (
        <>
          <div className="head-chips" role="tablist" aria-label="Head of the screen">
            {Object.entries(heads).map(([name, h]) => (
              <button key={name} role="tab" aria-selected={chosen === name} className={`head-chip ${chosen === name ? "active" : ""} ${h.probability >= 0.5 ? "hot" : ""}`} onClick={() => setHead(name)} title={h.title}>
                <span>{name === "any" ? "any rule" : name}</span>
                <strong>{h.probability.toFixed(3)}</strong>
              </button>
            ))}
          </div>
          <p className="small">
            <strong>{heads[chosen].title}</strong>: probability {heads[chosen].probability.toFixed(3)} against {heads[chosen].base_probability.toFixed(3)} for the average invoice.
            {e.screen && heads[e.screen.suggested_rule].probability >= 0.5 && (
              <>
                {" "}
                Of the judgement rules the screen points to <Badge tone="bad">{e.screen.suggested_rule}</Badge> ({heads[e.screen.suggested_rule].title.toLowerCase()}).
              </>
            )}
          </p>
          <ShapWaterfall head={heads[chosen]} />
        </>
      )}
    </Panel>
  );
}

function Option({ option, kind }: { option: CounterfactualOption; kind: "record" | "policy" }) {
  return (
    <li className="cf-option">
      <Badge tone={kind === "policy" ? "violet" : "accent"}>{kind === "policy" ? "policy" : "records"}</Badge>
      <div>
        <div className="small">{option.change}</div>
        <div className="muted small">
          verified by running the controls again
          {option.raises.length > 0 && <span className="warn-text">; would raise {option.raises.join(", ")} instead</span>}
          {option.also_clears != null && <>; the same change would also clear {option.also_clears.toLocaleString("en-IN")} other invoice(s) of this rule</>}
        </div>
        {option.caution && <div className="small warn-text">{option.caution}</div>}
      </div>
    </li>
  );
}

function CounterfactualCard({ cf }: { cf: Counterfactual }) {
  return (
    <article className="finding">
      <header>
        <strong>Rule {cf.clause}</strong> <span className="muted">{cf.title}</span> <SeverityBadge severity={cf.severity} />
      </header>
      <p className="small">
        <strong>Margin:</strong> {cf.margin.text}.
      </p>
      <ul className="cf-options">
        {cf.record.map((o, i) => (
          <Option key={`r${i}`} option={o} kind="record" />
        ))}
        {cf.policy.map((o, i) => (
          <Option key={`p${i}`} option={o} kind="policy" />
        ))}
      </ul>
      {cf.no_parameter && <p className="muted small">The rule has no threshold: only the records can clear it.</p>}
    </article>
  );
}

export function CounterfactualPanel({ id }: { id: string }) {
  const explained = useApi(() => explainOnce(id), [id]);
  const e = explained.data;
  return (
    <Panel
      title="What would clear each finding"
      subtitle="Counterfactual explanations: how far the invoice is past each rule, and the smallest change of its records or of the policy that would clear the finding, found by running the controls themselves. An explanation, not advice to change a record."
    >
      {explained.loading && !e && <Loading what="Working out the counterfactuals" />}
      <ErrorBox error={explained.error} onRetry={explained.reload} />
      {e && (e.counterfactuals.length ? e.counterfactuals.map((cf) => <CounterfactualCard key={cf.clause} cf={cf} />) : <Empty>No control finding under the policy in force (v{e.policy_version}).</Empty>)}
    </Panel>
  );
}

export function StoryPanel({ id }: { id: string }) {
  const story = useApi(() => api.story(id), [id]);
  const s = story.data;
  return (
    <Panel title="The story of this invoice" subtitle="Everything that happened to it, in order: records, approvals, e-mails, audits and decisions.">
      {story.loading && !s && <Loading what="Telling the story" />}
      <ErrorBox error={story.error} onRetry={story.reload} />
      {s && (
        <>
          <StoryTimeline steps={s.steps} />
          <p className="small strong">Now: {s.state}</p>
        </>
      )}
    </Panel>
  );
}
