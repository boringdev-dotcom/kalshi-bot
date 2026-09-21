import { Controls } from "../components/Controls";
import type { Portfolio as PortfolioT, Status } from "../types";

export function Portfolio({
  portfolio,
  status,
  reload,
}: {
  portfolio: PortfolioT | null;
  status: Status | null;
  reload: () => void;
}) {
  if (!portfolio) return <div className="empty">Loading portfolio…</div>;
  return (
    <>
      <div className="topbar">
        <div>
          <h1>Portfolio</h1>
          <p className="lede">
            Open positions, daily notional, playbook caps {portfolio.caps.used_today}/{portfolio.caps.per_day} today.
          </p>
        </div>
        <Controls status={status} onChange={reload} />
      </div>
      <div className="grid">
        <div className="card">
          <h3>Open</h3>
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
          <h3>Today</h3>
          <p className="meta">Buy-No notional {String(portfolio.daily_pnl.buy_no_notional_cents)}¢</p>
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
      </div>
    </>
  );
}
