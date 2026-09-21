import type { CostSummary } from "../types";

export function Costs({ today, all }: { today: CostSummary | null; all: CostSummary | null }) {
  if (!today || !all) return <div className="empty">Loading Grok spend…</div>;
  return (
    <>
      <div className="topbar">
        <div>
          <h1>Costs</h1>
          <p className="lede">xAI Grok calls, tokens, and estimated USD. Agents run only on material events.</p>
        </div>
      </div>
      <div className="grid">
        <div className="card">
          <h3>Today ${today.cost_usd.toFixed(4)}</h3>
          <p className="meta">
            {today.calls} calls · {today.input_tokens} in · {today.output_tokens} out
          </p>
        </div>
        <div className="card">
          <h3>All-time ${all.cost_usd.toFixed(4)}</h3>
          <p className="meta">
            {all.calls} calls · {all.input_tokens} in · {all.output_tokens} out
          </p>
        </div>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h3>Per game</h3>
        <table className="table">
          <thead>
            <tr>
              <th>Game</th>
              <th>Calls</th>
              <th>Tokens</th>
              <th>USD</th>
            </tr>
          </thead>
          <tbody>
            {all.by_game.map((row) => (
              <tr key={row.game_id}>
                <td>{row.game_id}</td>
                <td>{row.calls}</td>
                <td>{row.input_tokens + row.output_tokens}</td>
                <td>${row.cost_usd.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <table className="table" style={{ marginTop: 20 }}>
          <thead>
            <tr>
              <th>When</th>
              <th>Agent</th>
              <th>Model</th>
              <th>USD</th>
            </tr>
          </thead>
          <tbody>
            {all.rows.map((row) => (
              <tr key={row.id}>
                <td>{new Date(row.created_at * 1000).toLocaleString()}</td>
                <td>{row.agent}</td>
                <td>{row.model}</td>
                <td>${row.cost_usd.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
