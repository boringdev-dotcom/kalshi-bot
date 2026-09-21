import { FormEvent, useState } from "react";
import { api } from "../api";
import { CapsBar } from "../components/CapsBar";
import { Controls } from "../components/Controls";
import { DecisionsTable } from "../components/DecisionsTable";
import type { Portfolio as PortfolioT, Pnl, Status } from "../types";

export function Portfolio({
  portfolio,
  status,
  reload,
}: {
  portfolio: PortfolioT | null;
  status: Status | null;
  reload: () => void;
}) {
  const limits = portfolio?.limits || status?.limits;
  const [match, setMatch] = useState(String(limits?.max_contracts_per_match ?? 150));
  const [day, setDay] = useState(String(limits?.max_contracts_per_day ?? 600));
  const [loss, setLoss] = useState(String(limits?.max_daily_loss_cents ?? 2500));
  const [msg, setMsg] = useState("");

  if (!portfolio) return <div className="empty">Loading portfolio…</div>;
  const pnl = (portfolio.pnl || portfolio.daily_pnl) as Pnl;

  const onSave = (event: FormEvent) => {
    event.preventDefault();
    setMsg("");
    api
      .limits({
        max_contracts_per_match: Number(match),
        max_contracts_per_day: Number(day),
        max_daily_loss_cents: Number(loss),
      })
      .then(() => {
        setMsg("Limits saved. Loss cap is enforced on paper P&L.");
        reload();
      })
      .catch((err: unknown) => {
        setMsg(err instanceof Error ? err.message : "Could not save limits");
      });
  };

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Portfolio</h1>
          <p className="lede">Paper fills, remaining caps, and the daily loss brake.</p>
        </div>
        <Controls status={status} onChange={reload} />
      </div>
      <CapsBar caps={portfolio.caps} pnl={pnl} />
      {portfolio.pause_reason && portfolio.pause_reason.includes("loss") ? (
        <p className="form-error" role="alert">
          Trading paused: {portfolio.pause_reason}. Raise the loss cap or resume after review.
        </p>
      ) : null}
      <div className="grid">
        <div className="card">
          <h3>Limits</h3>
          <form className="form limits-form" onSubmit={onSave}>
            <label>
              Max / match
              <input type="number" min={1} value={match} onChange={(e) => setMatch(e.target.value)} />
            </label>
            <label>
              Max / day
              <input type="number" min={1} value={day} onChange={(e) => setDay(e.target.value)} />
            </label>
            <label>
              Max daily loss (¢)
              <input type="number" min={0} value={loss} onChange={(e) => setLoss(e.target.value)} />
            </label>
            <button className="primary" type="submit">Save limits</button>
          </form>
          {msg ? <p className="meta">{msg}</p> : null}
        </div>
        <div className="card">
          <h3>Open (paper)</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Market</th>
                <th>Qty</th>
                <th>Avg</th>
                <th>Mode</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.positions.map((p) => (
                <tr key={p.market_ticker}>
                  <td>{p.market_ticker}</td>
                  <td>{p.count}</td>
                  <td>{p.avg_price}¢</td>
                  <td>{p.paper ? "paper" : "live"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>Today&apos;s paper orders</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Action</th>
                <th>Ticker</th>
                <th>Qty</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.orders_today.map((o) => (
                <tr key={o.id}>
                  <td>{o.action}</td>
                  <td>{o.market_ticker}</td>
                  <td>{o.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>Recent would-decisions</h3>
          <DecisionsTable decisions={portfolio.decisions || []} />
        </div>
      </div>
    </>
  );
}
