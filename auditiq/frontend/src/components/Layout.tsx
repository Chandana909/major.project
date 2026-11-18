import { useEffect, useRef, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, getToken, setToken } from "../api/client";
import { STORE_CHANGED, useApi } from "../lib/useApi";
import { Icon } from "./icons";

type NavItem = { to: string; label: string; icon: string; waiting?: boolean };

const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: "Command",
    items: [
      { to: "/", label: "Overview", icon: "overview" },
      { to: "/review", label: "Review queue", icon: "queue", waiting: true },
      { to: "/invoice", label: "Invoices", icon: "invoice" },
    ],
  },
  {
    group: "Ingestion",
    items: [{ to: "/kafka", label: "Kafka streams", icon: "kafka" }],
  },
  {
    group: "AI layer",
    items: [
      { to: "/ai", label: "Agents & pipeline", icon: "ai" },
      { to: "/ask", label: "Ask AI", icon: "copilot" },
    ],
  },
  {
    group: "Knowledge layer",
    items: [
      { to: "/knowledge", label: "Knowledge base", icon: "knowledge" },
      { to: "/graph", label: "Knowledge graph", icon: "graph" },
      { to: "/rag", label: "RAG retrieval", icon: "rag" },
      { to: "/policy", label: "Policy", icon: "policy" },
    ],
  },
  {
    group: "Intelligence",
    items: [
      { to: "/analytics", label: "Audit analytics", icon: "analytics" },
      { to: "/rings", label: "Vendor collusion", icon: "rings" },
      { to: "/assurance", label: "Assurance", icon: "assurance" },
    ],
  },
  {
    group: "Platform",
    items: [
      { to: "/architecture", label: "Architecture", icon: "architecture" },
      { to: "/pipeline", label: "Pipeline & configs", icon: "pipeline" },
      { to: "/results", label: "Results", icon: "results" },
    ],
  },
];

const TITLES: Record<string, string> = Object.fromEntries(NAV.flatMap((g) => g.items.map((i) => [i.to, `${g.group} / ${i.label}`])));

function TokenForm({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState(getToken() ?? "");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setToken(value.trim() || null);
    onSaved();
  };
  return (
    <form className="token-form" onSubmit={submit}>
      <p>This server requires an API token.</p>
      <input type="password" value={value} onChange={(e) => setValue(e.target.value)} placeholder="API token" aria-label="API token" />
      <button className="btn btn-primary" type="submit">
        Save token
      </button>
    </form>
  );
}

/** Go to an invoice by its number, or search the invoices for anything else; "/" puts the cursor here. */
function GlobalSearch() {
  const [value, setValue] = useState("");
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (e.key === "/" && !(target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = value.trim();
    if (!q) return;
    navigate(/^INV\d+$/i.test(q) ? `/invoice/${q.toUpperCase()}` : `/invoice?q=${encodeURIComponent(q)}`);
    setValue("");
    input.current?.blur();
  };
  return (
    <form className="global-search" onSubmit={submit} role="search">
      <Icon name="search" size={16} />
      <input ref={input} value={value} onChange={(e) => setValue(e.target.value)} placeholder="Invoice number or vendor" aria-label="Go to an invoice" />
      <kbd>/</kbd>
    </form>
  );
}

export function Layout() {
  const health = useApi(() => api.health());
  const overview = useApi(() => api.overview());
  const reloadHealth = health.reload;
  const reloadOverview = overview.reload;
  useEffect(() => {
    const reload = () => {
      reloadHealth();
      reloadOverview();
    };
    window.addEventListener(STORE_CHANGED, reload);
    return () => window.removeEventListener(STORE_CHANGED, reload);
  }, [reloadHealth, reloadOverview]);
  const auth = useApi(() => api.me(), []);
  const system = useApi(() => api.system());
  const reloadSystem = system.reload;
  useEffect(() => {
    // The system bar follows what starts and stops; a tab nobody is looking at does not ask.
    const timer = window.setInterval(() => !document.hidden && reloadSystem(), 20000);
    return () => window.clearInterval(timer);
  }, [reloadSystem]);
  const sys = system.data;
  const needsToken = (auth.error as { status?: number } | null)?.status === 401;
  const me = auth.data;
  const h = health.data;
  const waiting = overview.data?.states.PENDING_REVIEW;
  const { pathname } = useLocation();
  const section = TITLES[pathname] ?? TITLES[`/${pathname.split("/")[1]}`] ?? "AuditIQ";

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-dot" aria-hidden />
          <div>
            <strong>AuditIQ</strong>
            <span>Forensic audit &amp; compliance</span>
          </div>
        </div>
        <nav aria-label="Main">
          {NAV.map((g) => (
            <div className="nav-group" key={g.group}>
              <span className="nav-heading">{g.group}</span>
              {g.items.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
                  <span className="nav-icon">
                    <Icon name={item.icon} />
                  </span>
                  <span className="nav-label">{item.label}</span>
                  {item.waiting && waiting ? (
                    <span className="nav-count" aria-label={`${waiting} waiting`}>
                      {waiting.toLocaleString("en-IN")}
                    </span>
                  ) : null}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="status">
          <span className="status-title">System</span>
          {h ? (
            <>
              <div>
                <span className="dot dot-good" /> API {h.version} · {h.backend}
              </div>
              <dl className="status-grid">
                <dt>Ledger</dt>
                <dd>{h.ledger ?? "none"}</dd>
                <dt>Policy</dt>
                <dd>v{h.policy_version ?? "–"}</dd>
                <dt>Model</dt>
                <dd>{h.model ?? "not configured"}</dd>
                <dt>Access</dt>
                <dd>{h.auth ? "token required" : "open"}</dd>
              </dl>
            </>
          ) : health.error ? (
            <div>
              <span className="dot dot-bad" /> API unreachable
            </div>
          ) : (
            <div className="muted">Connecting…</div>
          )}
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="topbar-title" title={section}>
            <span className="crumb-root">Workspace</span>
            <span className="crumb-sep">/</span>
            <span className="mono">{h?.ledger ?? "no ledger"}</span>
            {overview.data && <span className="muted small">{overview.data.invoices.toLocaleString("en-IN")} invoices</span>}
          </div>
          <GlobalSearch />
          <div className="topbar-meta">
            {sys ? (
              <>
                <span className="pill" title={sys.kafka.connected ? `broker ${sys.kafka.bootstrap}, topics ${sys.kafka.prefix}.*` : sys.kafka.error ?? "no broker configured"}>
                  <span className={`dot ${sys.kafka.connected ? "dot-good" : "dot-idle"}`} />
                  Kafka {sys.kafka.connected ? "live" : "off"}
                </span>
                <span className="pill" title={sys.model.configured ? `${sys.model.name} at ${sys.model.endpoint} (${sys.model.status})` : "no model configured"}>
                  <span className={`dot ${sys.model.reachable ? "dot-good" : "dot-bad"}`} />
                  Model {sys.model.reachable ? "online" : "offline"}
                </span>
                <span className="pill" title={sys.embeddings.model ?? "no embedding model"}>
                  <span className={`dot ${sys.embeddings.embedded && sys.embeddings.embedded === sys.embeddings.passages ? "dot-good" : "dot-idle"}`} />
                  Vectors {sys.embeddings.embedded}/{sys.embeddings.passages}
                </span>
                <span className="pill">Policy v{sys.policy_version ?? "–"}</span>
                <span className="pill mono">{sys.store.backend}</span>
              </>
            ) : (
              h && (
                <>
                  <span className="pill">Policy v{h.policy_version ?? "–"}</span>
                  <span className="pill mono">{h.backend}</span>
                </>
              )
            )}
            {me && me.via !== "open" && (
              <span className="pill user" aria-label="Signed in">
                {me.via === "account" ? `${me.name} · ${me.role}` : `shared token · ${me.role}`}
              </span>
            )}
          </div>
        </header>
        <main className="content">
          {needsToken ? (
            <TokenForm
              onSaved={() => {
                auth.reload();
                health.reload();
                overview.reload();
              }}
            />
          ) : (
            <Outlet />
          )}
        </main>
      </div>
    </div>
  );
}
