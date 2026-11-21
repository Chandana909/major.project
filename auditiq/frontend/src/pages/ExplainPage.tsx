import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Empty, ErrorBox, Kpi, Loading, Panel, RouteBadge } from "../components/ui";
import { Beeswarm, ImportanceBars, ProbabilityHistogram, ScoreValues } from "../components/xai";
import { count, inr, percent } from "../lib/format";
import { useApi } from "../lib/useApi";
import { rankColor } from "../lib/xai";

/** The risk screen: a learned model over every invoice, each prediction explained with exact SHAP values. */
export function ExplainPage() {
  const model = useApi(() => api.model());
  const [head, setHead] = useState("any");
  if (model.loading && !model.data) return <Loading what="Scoring the ledger with the risk screen" />;
  if (model.error) return <ErrorBox error={model.error} onRetry={model.reload} />;
  const m = model.data;
  if (!m) return null;
  if (!m.trained) {
    return (
      <div className="page">
        <h1>Explainable AI</h1>
        <Empty>
          No risk screen is trained yet. Run <code>python -m auditiq model train</code> and reload this page.
        </Empty>
      </div>
    );
  }
  const heads = m.heads ?? {};
  const importance = m.importance?.[head];
  const evaluation = m.evaluation;
  const training = m.training;
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">AI layer · Explainable AI</span>
          <h1>Risk screen and SHAP explanations</h1>
          <p className="muted">
            Gradient-boosted trees read every invoice in microseconds and score it: one head for "anomalous at all" and one per judgement rule that the controls cannot decide. Every score is taken apart into the contribution of each feature with exact SHAP values (TreeSHAP), which add up to the model's output. A score is a second opinion for a reviewer or for the language-model agents, not a finding: it changes no result, score or route.
          </p>
        </div>
      </header>

      <div className="kpis">
        <Kpi label="Trained on" value={training?.ledger ?? "–"} hint={`${count(training?.invoices)} invoices, policy v${training?.policy_version}; 150 trees of depth 3 per head`} />
        <Kpi label="Invoices scored" value={count(m.scored)} hint={m.limited ? `the first ${count(m.scored)} of ${count(m.invoices)}` : "every invoice of the ledger"} tone="accent" />
        <Kpi label="Likely anomalous" value={count(m.above_half?.any)} hint="probability at least 0.5 (any rule)" tone="warn" />
        <Kpi label="Judgement leads" value={count(m.above_half?.judgement)} hint="a judgement rule at 0.5 or more" tone="bad" />
        {evaluation && (
          <Kpi
            label="Held-out AUC (judgement heads)"
            value={(["2.1.4", "2.1.5", "2.2.2", "4.1.2"].reduce((t, h) => t + (evaluation.heads[h]?.auc_mean ?? 0), 0) / 4).toFixed(3)}
            hint={`mean over ${evaluation.ledgers.length} ledgers it was not trained on`}
            tone="good"
          />
        )}
      </div>

      <Panel
        title="What drives the screen"
        subtitle="Mean absolute SHAP value of each feature over a random sample of the ledger's invoices (how far it moves the head's output, in log-odds), and every sampled invoice as a dot: right of the line pushes toward an anomaly, the colour is the feature's value (blue low, red high)."
        actions={
          <div className="segmented" role="tablist" aria-label="Head">
            {Object.keys(heads).map((h) => (
              <button key={h} role="tab" aria-selected={head === h} className={head === h ? "active" : ""} onClick={() => setHead(h)} title={heads[h]}>
                {h === "any" ? "Any rule" : h}
              </button>
            ))}
          </div>
        }
      >
        {importance ? (
          <div className="grid-2">
            <div>
              <h3 className="small strong">{importance.title}</h3>
              <ImportanceBars head={importance} />
            </div>
            <div>
              <Beeswarm head={importance} />
              <p className="legend small">
                <span>
                  <i style={{ background: rankColor(0) }} /> low value
                </span>
                <span>
                  <i style={{ background: rankColor(1) }} /> high value
                </span>
                <span className="muted">{count(importance.rows)} invoices drawn at random</span>
              </p>
            </div>
          </div>
        ) : (
          <Empty>No invoices to explain.</Empty>
        )}
      </Panel>

      <div className="grid-2">
        <Panel title="A continuous risk index" subtitle="The screen's probability of an anomaly for every invoice, coloured by the route the audit gave it. The audit's own score (right) takes a handful of values, because most anomalous invoices carry one finding and sit on a floor.">
          {m.distribution && <ProbabilityHistogram bins={m.distribution.bins} byRoute={m.distribution.by_route} />}
        </Panel>
        <Panel title="The audit's score (equations 2 to 5)" subtitle="Latest results by their weighted risk score, rounded (log scale). The screen does not replace it; it ranks inside each of these values.">
          {m.paper_score && Object.keys(m.paper_score).length ? <ScoreValues values={m.paper_score} /> : <Empty>Nothing audited yet.</Empty>}
        </Panel>
      </div>

      <Panel
        title="Second opinion: invoices the audit passed that the screen would look at"
        subtitle="The latest result approved these invoices (or they are not audited), and a judgement head of the screen rates them highest. Each is a lead for a reviewer, or for the agents (C3 to C5), which take minutes per invoice and so cannot read the whole ledger. Open one to see why."
      >
        {m.second_opinion && m.second_opinion.length ? (
          <div className="table-wrap short">
            <table className="table sticky compact">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Vendor</th>
                  <th>Date</th>
                  <th className="num">Amount</th>
                  <th>Audit</th>
                  <th>Suggested rule</th>
                  <th className="num">Probability</th>
                </tr>
              </thead>
              <tbody>
                {m.second_opinion.slice(0, 40).map((s) => (
                  <tr key={s.invoice_id}>
                    <td>
                      <Link className="mono" to={`/invoice/${s.invoice_id}`}>
                        {s.invoice_id}
                      </Link>
                    </td>
                    <td>{s.vendor_name}</td>
                    <td className="mono">{s.date?.slice(0, 10)}</td>
                    <td className="num">₹{inr(s.amount)}</td>
                    <td>
                      <RouteBadge route={s.route} />
                    </td>
                    <td>
                      <Badge tone={s.probability >= 0.5 ? "bad" : "neutral"}>{s.suggested_rule}</Badge> <span className="small muted">{s.rule_title}</span>
                    </td>
                    <td className="num">{s.probability.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>The screen rates no approved invoice for a judgement rule.</Empty>
        )}
      </Panel>

      <Panel title="Model card" subtitle="How the screen was trained and measured. The measurement is python -m evaluation.screen_eval (results/risk_screen/screen.md).">
        <div className="grid-2">
          <dl className="facts">
            <div>
              <dt>Model</dt>
              <dd>scikit-learn GradientBoostingClassifier per head ({training?.params?.n_estimators} trees, depth {training?.params?.max_depth}, learning rate {training?.params?.learning_rate}), stored as plain arrays; prediction and SHAP read them with numpy</dd>
            </div>
            <div>
              <dt>Training data</dt>
              <dd>
                the answer key of <span className="mono">{training?.ledger}</span>, the development ledger; the store's own labels are never read
              </dd>
            </div>
            <div>
              <dt>Features</dt>
              <dd>{m.features?.length} measurements of the transaction, under the thresholds of the policy in force on the invoice's date</dd>
            </div>
            <div>
              <dt>Explanations</dt>
              <dd>exact TreeSHAP (Lundberg et al., 2018), checked against the Shapley formula itself; the parts add up to the output</dd>
            </div>
            <div>
              <dt>Limits</dt>
              <dd>every ledger it was measured on comes from the same generator as its training ledger; on real invoices it must be trained on labelled real cases</dd>
            </div>
          </dl>
          {evaluation ? (
            <div>
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Head</th>
                    <th className="num">AUC (held out)</th>
                    <th className="num">Isolation forest</th>
                    <th className="num">Recall at 2 %</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(evaluation.heads).map(([h, s]) => (
                    <tr key={h}>
                      <td title={s.title}>{h === "any" ? "any rule" : h}</td>
                      <td className="num">
                        {s.auc_mean.toFixed(4)} <span className="muted small">({s.auc_min.toFixed(3)}–{s.auc_max.toFixed(3)})</span>
                      </td>
                      <td className="num">{s.isolation_forest_auc_mean.toFixed(3)}</td>
                      <td className="num">{percent(s.recall_at_2pct_mean)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small muted">
                Of {count(evaluation.second_opinion_at_2pct.of)} judgement anomalies the controls alone approve on {evaluation.ledgers.length} held-out ledgers, {count(evaluation.second_opinion_at_2pct.found)} ({percent(evaluation.second_opinion_at_2pct.recall)}) are in the top 2 % of the invoices the controls approve.
                The suggested rule is right for {count(evaluation.classification.right)} of {count(evaluation.classification.of)} judgement anomalies scored at least 0.5.
              </p>
            </div>
          ) : (
            <Empty>Not measured yet: python -m evaluation.screen_eval</Empty>
          )}
        </div>
      </Panel>
    </div>
  );
}
