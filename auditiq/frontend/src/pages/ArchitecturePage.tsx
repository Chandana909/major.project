// The Architecture tab: the whole platform as a 3D city (or a 2D map), a guided pitch tour that follows one invoice
// through every layer, and what makes it more than a demo. Clicking any component opens the page that shows it working.
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ArchitectureDiagram } from "../components/ArchitectureDiagram";
import { Kpi, Loading, Panel } from "../components/ui";
import { demoOf, EDGES, GROUPS, KIND_STYLE, NODES, PAGES } from "../lib/architecture";
import { count } from "../lib/format";
import { CODEBASE, HARD_PROBLEMS, INVOICE_PATH, liveBadges, TOUR, type LiveFacts } from "../lib/pitch";
import { useApi } from "../lib/useApi";
import { webglAvailable } from "../three/layout";

// three.js loads only when the 3D view is shown.
const ArchitectureScene = lazy(() => import("../three/ArchitectureScene").then((m) => ({ default: m.ArchitectureScene })));

type View = "3d" | "map";

export function ArchitecturePage() {
  const navigate = useNavigate();
  const overview = useApi(() => api.overview());
  const health = useApi(() => api.health());
  const stream = useApi(() => api.stream());
  const policy = useApi(() => api.policy());
  const gl = useMemo(() => webglAvailable(), []);
  const [view, setView] = useState<View>(gl ? "3d" : "map");
  const [step, setStep] = useState<number | null>(null);
  const [full, setFull] = useState(false);

  const facts: LiveFacts = useMemo(() => ({ overview: overview.data ?? undefined, health: health.data ?? undefined, stream: stream.data ?? undefined, policy: policy.data ?? undefined }),
    [overview.data, health.data, stream.data, policy.data]);
  const live = useMemo(() => liveBadges(facts), [facts]);
  const current = step === null ? null : TOUR[step];
  const tourNodes = current?.nodes.length ? current.nodes : current ? INVOICE_PATH : null;
  const path = current && !current.nodes.length ? INVOICE_PATH : null;
  const open = useCallback((id: string) => navigate(demoOf(id).to), [navigate]);

  useEffect(() => {
    const key = (ev: KeyboardEvent) => {
      const typing = ev.target instanceof HTMLElement && /input|textarea|select/i.test(ev.target.tagName);
      if (typing) return;
      if (ev.key === "Escape") {
        if (step !== null) setStep(null);
        else setFull(false);
      }
      if (step === null) return;
      if (ev.key === "ArrowRight") setStep((s) => Math.min(TOUR.length - 1, (s ?? 0) + 1));
      if (ev.key === "ArrowLeft") setStep((s) => Math.max(0, (s ?? 0) - 1));
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [step]);

  const kpis: [string, string, string][] = [
    ["Subsystems", String(GROUPS.length), "from ingestion to delivery"],
    ["Components", String(NODES.length), "each one in the code"],
    ["Connections", String(EDGES.length), "drawn from the imports"],
    ...CODEBASE.map((c) => [c.label, c.value, c.hint] as [string, string, string]),
  ];

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">Platform · Architecture</span>
          <h1>AuditIQ, end to end</h1>
          <p className="muted">
            Every subsystem and component of the platform and the data moving between them. Hover a component to see what feeds it and what it feeds; click it to open the
            page where it runs. Start the tour to follow one invoice from the ERP ledger to the reviewer's screen.
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setStep(0)}>
          Start the pitch tour
        </button>
      </header>

      <div className="kpis eight">
        {kpis.map(([label, value, hint]) => (
          <Kpi key={label} label={label} value={value} hint={hint} />
        ))}
      </div>

      <section className={`a3-stage ${full ? "full" : ""} ${view}`} aria-label="Architecture">
        <div className="a3-bar">
          <div className="segmented" role="tablist" aria-label="View">
            <button role="tab" aria-selected={view === "3d"} className={view === "3d" ? "active" : ""} onClick={() => setView("3d")} disabled={!gl}
              title={gl ? "The platform as a 3D city" : "This browser has no WebGL"}>
              3D city
            </button>
            <button role="tab" aria-selected={view === "map"} className={view === "map" ? "active" : ""} onClick={() => setView("map")}>
              2D map
            </button>
          </div>
          <div className="a3-legend">
            {Object.entries(KIND_STYLE).map(([k, v]) => (
              <span key={k}>
                <i style={{ background: v.color }} /> {v.label}
              </span>
            ))}
          </div>
          <div className="a3-actions">
            {step === null ? (
              <button type="button" className="a3-btn primary" onClick={() => setStep(0)}>
                ▶ Pitch tour
              </button>
            ) : (
              <button type="button" className="a3-btn" onClick={() => setStep(null)}>
                End tour
              </button>
            )}
            <button type="button" className="a3-btn" onClick={() => setFull(!full)} aria-pressed={full}>
              {full ? "Exit full screen" : "Full screen"}
            </button>
          </div>
        </div>

        <div className="a3-view">
          {view === "3d" && gl ? (
            <Suspense fallback={<Loading what="Building the 3D city" />}>
              <ArchitectureScene tour={tourNodes} path={path} live={live} onOpen={open} height="100%" />
            </Suspense>
          ) : (
            <ArchitectureDiagram live={live} onOpen={open} tour={tourNodes} embedded />
          )}
          {view === "3d" && step === null && (
            <div className="a3-hint">
              <span><i style={{ background: "#38bdf8" }} /> feeds in</span>
              <span><i style={{ background: "#fbbf24" }} /> feeds out</span>
              <span>Hover to trace · click to open its page · drag to turn · scroll to zoom · right-drag to pan</span>
            </div>
          )}
        </div>

        {current && step !== null && (
          <aside className="a3-tour" aria-live="polite" aria-label="Pitch tour">
            <div className="a3-tour-progress">
              {TOUR.map((t, i) => (
                <button key={t.id} type="button" className={i === step ? "on" : i < step ? "done" : ""} onClick={() => setStep(i)} aria-label={`Step ${i + 1}: ${t.title}`} />
              ))}
            </div>
            <h2>{current.title}</h2>
            <p>{current.story}</p>
            <div className="a3-tour-hard">
              <b>Why it is not simple</b>
              <span>{current.hard}</span>
            </div>
            {current.figures(facts).length > 0 && (
              <div className="a3-tour-figures">
                {current.figures(facts).map((f) => (
                  <span key={f}>{f}</span>
                ))}
              </div>
            )}
            <div className="a3-tour-nav">
              <button type="button" className="a3-btn" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>
                ← Back
              </button>
              <Link className="a3-btn" to={current.page}>
                Open {PAGES[current.page]} ↗
              </Link>
              {step < TOUR.length - 1 ? (
                <button type="button" className="a3-btn primary" onClick={() => setStep(step + 1)}>
                  Next →
                </button>
              ) : (
                <button type="button" className="a3-btn primary" onClick={() => setStep(null)}>
                  Finish
                </button>
              )}
            </div>
            <span className="a3-tour-keys">
              Step {step + 1} of {TOUR.length} · ← → to move · Esc to leave
            </span>
          </aside>
        )}
      </section>

      <Panel title="Why this is not a simple project" subtitle="Each is an engineering problem the platform solves, and each can be shown working on a page of this application.">
        <div className="a3-hard-grid">
          {HARD_PROBLEMS.map((h, i) => (
            <Link key={h.title} to={h.page} className="a3-hard">
              <span className="a3-hard-n">{String(i + 1).padStart(2, "0")}</span>
              <strong>{h.title}</strong>
              <p>{h.text}</p>
              <span className="a3-hard-link">See it on {PAGES[h.page]} →</span>
            </Link>
          ))}
        </div>
      </Panel>

      <Panel title="Subsystems and their components" subtitle={`${GROUPS.length} subsystems · ${NODES.length} components · ${count(EDGES.length)} connections. Click a component to open the page where it runs.`}>
        <div className="a3-groups">
          {GROUPS.map((g) => {
            const members = NODES.filter((n) => n.group === g.id);
            return (
              <div key={g.id} className="a3-group" style={{ ["--tone" as string]: g.tone }}>
                <div className="a3-group-head">
                  <strong>{g.title}</strong>
                  <span>{members.length} components</span>
                </div>
                <p className="muted small">{g.note}</p>
                <div className="a3-chips">
                  {members.map((n) => (
                    <button key={n.id} type="button" className="a3-chip" onClick={() => open(n.id)} title={`${n.detail} Opens ${demoOf(n.id).page}.`}
                      style={{ ["--kind" as string]: KIND_STYLE[n.kind].color }}>
                      {n.title}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
