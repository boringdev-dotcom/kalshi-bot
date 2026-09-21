import { NavLink } from "react-router-dom";
import type { Status } from "../types";

const links = [
  { to: "/", label: "Upcoming" },
  { to: "/live", label: "Live" },
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
        <div className="pills" style={{ marginBottom: 18 }}>
          <span className={`pill ${status?.paper ? "ok" : "warn"}`}>{status?.paper ? "paper" : "live orders"}</span>
          <span className={`pill ${status?.paused ? "warn" : "live"}`}>{status?.paused ? "paused" : "armed"}</span>
          <span className={`pill ${connected ? "ok" : ""}`}>{connected ? "stream on" : "stream off"}</span>
          <span className="pill">{status?.kalshi_env || "env"}</span>
        </div>
        {children}
      </section>
    </div>
  );
}
