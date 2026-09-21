import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import type { Game, GameEvent, Order, Position, Verdict } from "../types";

export function GameDetail({ tick }: { tick: number }) {
  const { id } = useParams();
  const [data, setData] = useState<{
    game: Game;
    events: GameEvent[];
    verdicts: Verdict[];
    orders: Order[];
    positions: Position[];
    pnl: Record<string, unknown>;
  } | null>(null);

  useEffect(() => {
    if (!id) return;
    api.game(id).then(setData).catch(() => setData(null));
  }, [id, tick]);

  if (!data) return <div className="empty">Loading game…</div>;
  const { game } = data;
  return (
    <>
      <div className="topbar">
        <div>
          <h1>
            {game.home_team} {game.home_goals}–{game.away_goals} {game.away_team}
          </h1>
          <p className="lede">
            {game.league} · {game.minute}' {game.phase} · P&L open {String(data.pnl.open_contracts)} ct
          </p>
        </div>
      </div>
      <div className="grid">
        <div className="card">
          <h3>Markets</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Strike</th>
                <th>Rem</th>
                <th>No ask</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {game.markets.map((m) => (
                <tr key={m.ticker}>
                  <td>{m.strike}</td>
                  <td>{m.rem}</td>
                  <td>{m.no_ask}¢</td>
                  <td>{m.last_verdict || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>Timeline</h3>
          <div className="timeline">
            {data.events.length === 0 && <div className="empty">No material events yet.</div>}
            {data.events.map((event) => (
              <div className="event" key={event.id}>
                <strong>{event.event_type}</strong> · {event.minute}'
                <div className="meta">{JSON.stringify(event.payload)}</div>
                {data.verdicts
                  .filter((v) => v.created_at >= event.created_at - 2)
                  .slice(0, 4)
                  .map((v) => (
                    <div key={v.id}>
                      {v.agent}: {v.verdict || "note"} — {v.reason}
                    </div>
                  ))}
              </div>
            ))}
          </div>
        </div>
        <div className="card">
          <h3>Orders</h3>
          <table className="table">
            <thead>
              <tr>
                <th>Action</th>
                <th>Ticker</th>
                <th>Size</th>
                <th>Px</th>
              </tr>
            </thead>
            <tbody>
              {data.orders.map((o) => (
                <tr key={o.id}>
                  <td>{o.action}</td>
                  <td>{o.market_ticker}</td>
                  <td>{o.count}</td>
                  <td>{o.price}¢ {o.paper ? "paper" : "live"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>Pre-match</h3>
          <pre style={{ whiteSpace: "pre-wrap", color: "var(--muted)", fontSize: 13 }}>
            {JSON.stringify(game.prematch, null, 2) || "Not pulled yet"}
          </pre>
        </div>
      </div>
    </>
  );
}
