import { useEffect, useState, type FormEvent } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api, getToken, setToken } from "../api/client";
import { STORE_CHANGED, useApi } from "../lib/useApi";

const NAV = [
  { to: "/", label: "Overview", icon: "◈" },
  { to: "/review", label: "Review queue", icon: "⚑" },
  { to: "/invoice", label: "Invoices", icon: "▤" },
  { to: "/policy", label: "Policy", icon: "§" },
  { to: "/copilot", label: "Copilot", icon: "✦" },
  { to: "/pipeline", label: "Pipeline", icon: "⬡" },
  { to: "/results", label: "Results", icon: "▲" },
];

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

export function Layout() {
  const health = useApi(() => api.health());
  const reloadHealth = health.reload;
  useEffect(() => {
    window.addEventListener(STORE_CHANGED, reloadHealth);
    return () => window.removeEventListener(STORE_CHANGED, reloadHealth);
  }, [reloadHealth]);
  const auth = useApi(() => api.overview().then(() => true), []);
  const needsToken = (auth.error as { status?: number } | null)?.status === 401;
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={34} height={34} />
          <div>
            <strong>AuditIQ</strong>
            <span>Forensic audit &amp; compliance</span>
          </div>
        </div>
        <nav aria-label="Main">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              <span className="nav-icon" aria-hidden>
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="status">
          {health.data ? (
            <>
              <div>
                <span className="dot dot-good" /> API {health.data.version} · {health.data.backend}
              </div>
              <div className="muted">Ledger {health.data.ledger ?? "none"}</div>
              <div className="muted">Policy v{health.data.policy_version ?? "–"}</div>
              <div className="muted">{health.data.model ? `Model ${health.data.model}` : "No model configured"}</div>
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
      <main className="content">
        {needsToken ? (
          <TokenForm
            onSaved={() => {
              auth.reload();
              health.reload();
            }}
          />
        ) : (
          <Outlet />
        )}
      </main>
    </div>
  );
}
