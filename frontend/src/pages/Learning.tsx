import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { LearningPayload, Proposal } from "../types";

function backtestLine(backtest: Record<string, unknown> | undefined) {
  const champ = (backtest?.champion || {}) as Record<string, unknown>;
  const chal = (backtest?.challenger || {}) as Record<string, unknown>;
  if (!Object.keys(champ).length && !Object.keys(chal).length) return "No backtest yet";
  return `Champion hit ${Number(champ.hit_rate || 0).toFixed(2)} / ${champ.pnl_cents ?? 0}¢ · Challenger hit ${Number(chal.hit_rate || 0).toFixed(2)} / ${chal.pnl_cents ?? 0}¢`;
}

export function Learning() {
  const [data, setData] = useState<LearningPayload | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(() => {
    api.learning().then(setData).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : "Learning failed to load");
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const act = (id: number, fn: (id: number) => Promise<unknown>) => {
    setBusy(id);
    setError("");
    fn(id)
      .then(() => load())
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Action failed"))
      .finally(() => setBusy(null));
  };

  if (!data) return <div className="empty">Loading learning loop…</div>;
  const inbox = data.proposals.filter((p) => p.status === "pending" || p.status === "shadow");
  const decided = data.proposals.filter((p) => p.status === "approved" || p.status === "rejected");

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Learning</h1>
          <p className="lede">
            Propose-only playbook changes. Hard caps (loss, per-match, per-day) are never proposed.
            Playbook v{data.playbook.current} — approve in the inbox to publish a new version.
          </p>
        </div>
      </div>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <div className="grid learning-grid">
        <div className="card">
          <h3>Proposals inbox</h3>
          <p className="meta">Approve / reject / try-in-shadow. Nothing applies until you approve.</p>
          {inbox.length === 0 && <div className="empty">No pending proposals.</div>}
          {inbox.map((row: Proposal) => (
            <div className="proposal" key={row.id}>
              <strong>{row.title}</strong>
              <div className="meta">{row.motivation}</div>
              <div className="meta">diff {JSON.stringify(row.diff)}</div>
              <div className="meta">{backtestLine(row.backtest)}</div>
              <div className="controls">
                <button className="primary" disabled={busy === row.id} onClick={() => act(row.id, api.approveProposal)}>
                  Approve
                </button>
                <button disabled={busy === row.id} onClick={() => act(row.id, api.rejectProposal)}>
                  Reject
                </button>
                {row.status !== "shadow" ? (
                  <button disabled={busy === row.id} onClick={() => act(row.id, api.shadowProposal)}>
                    Try in shadow
                  </button>
                ) : (
                  <span className="pill">shadow</span>
                )}
              </div>
            </div>
          ))}
          {decided.length > 0 && (
            <div className="meta" style={{ marginTop: 16 }}>
              Decided: {decided.map((p) => `${p.title} (${p.status})`).join(" · ")}
            </div>
          )}
        </div>
        <div className="card">
          <h3>Lessons</h3>
          <p className="meta">Hypotheses stay unused until mining validates them.</p>
          <table className="table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Conf</th>
                <th>Condition</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {data.lessons.map((lesson) => (
                <tr key={lesson.id}>
                  <td>
                    <span className={`chip ${lesson.status}`}>{lesson.status}</span>
                  </td>
                  <td>{Number(lesson.confidence).toFixed(2)}</td>
                  <td>{lesson.condition}</td>
                  <td>{lesson.suggested_action}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.lessons.length === 0 && <div className="empty">No lessons yet.</div>}
        </div>
        <div className="card">
          <h3>Calibration</h3>
          <p className="meta">Brier score of stated confidence vs outcomes.</p>
          <table className="table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>League</th>
                <th>n</th>
                <th>Brier</th>
                <th>Hit</th>
              </tr>
            </thead>
            <tbody>
              {data.calibration.map((row) => (
                <tr key={row.id}>
                  <td>{row.agent}</td>
                  <td>{row.league || "all"}</td>
                  <td>{row.n}</td>
                  <td>{row.brier}</td>
                  <td>{row.hit_rate ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.calibration.length === 0 && <div className="empty">No calibration rows yet.</div>}
        </div>
        <div className="card">
          <h3>Playbook versions</h3>
          <p className="meta">Hard-cap keys excluded: {data.hard_cap_keys.join(", ")}</p>
          <ul className="version-list">
            {data.playbook.versions.map((ver) => (
              <li key={ver.version}>
                v{ver.version}
                {ver.version === data.playbook.current ? " · current" : ""} — {ver.notes || "seed"}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
