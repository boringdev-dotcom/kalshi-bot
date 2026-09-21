import { NavLink } from "react-router-dom";
import type { Status } from "../types";

const links = [
  { to: "/", label: "Upcoming" },
  { to: "/live", label: "Live" },
  { to: "/replay", label: "Replay" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/costs", label: "Costs" },
];

export function Layout({
  children,
  status,
  connected,
}: {
  children: React.ReactNode;
  status: Status | null;
  connected: boolean;
}) {
  const paper = status?.paper !== false;
  return (
    <div className="app">
      <aside className="rail">
        <div className="wordmark">
          Under
          <span>No</span>
        </div>
        <nav className="nav">
          {links.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
              {link.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <section className="main">
        <div className={`paper-banner ${paper ? "" : "live-warn"}`}>
          {paper
            ? "PAPER ONLY — no live orders. Every Pundit/Kalshi call is would-place / would-skip / would-flatten."
            : "LIVE ORDERS ON — real Kalshi fills. Switch back to paper unless you intend to send size."}
        </div>
        <div className="pills" style={{ marginBottom: 18 }}>
          <span className={`pill ${paper ? "ok" : "warn"}`}>{paper ? "paper only" : "live orders"}</span>
          <span className={`pill ${status?.paused ? "warn" : "live"}`}>
            {status?.paused ? `paused${status.pause_reason ? ` · ${status.pause_reason}` : ""}` : "armed"}
          </span>
          <span className={`pill ${connected ? "ok" : ""}`}>{connected ? "stream on" : "stream off"}</span>
          <span className="pill">{status?.kalshi_env || "env"}</span>
        </div>
        {children}
      </section>
    </div>
  );
}
