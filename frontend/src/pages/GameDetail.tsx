import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import { CapsBar } from "../components/CapsBar";
import { DecisionsTable } from "../components/DecisionsTable";
import type { Caps, Decision, Game, GameEvent, Order, Position, Pnl, Verdict } from "../types";

export function GameDetail({ tick }: { tick: number }) {
  const { id } = useParams();
  const [data, setData] = useState<{
    game: Game;
    events: GameEvent[];
    verdicts: Verdict[];
    decisions: Decision[];
    orders: Order[];
    positions: Position[];
    pnl: Pnl;
    caps: Caps;
  } | null>(null);

  useEffect(() => {
    if (!id) return;
    api.game(id).then((row) => setData(row as typeof data)).catch(() => setData(null));
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
            {game.league} · {game.minute}' {game.phase} · paper would-decisions
          </p>
        </div>
      </div>
      <CapsBar caps={data.caps} pnl={data.pnl} />
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
          <h3>Would-decisions</h3>
          <DecisionsTable decisions={data.decisions || []} />
        </div>
        <div className="card">
          <h3>Timeline</h3>
          <div className="timeline">
            {data.events.length === 0 && <div className="empty">No material events yet.</div>}
            {data.events.map((event) => (
              <div className="event" key={event.id}>
                <strong>{event.event_type}</strong> · {event.minute}'
                <div className="meta">
                  {(data.decisions || [])
                    .filter((d) => d.event_id === event.id)
                    .map((d) => (
                      <div key={d.id}>
                        {d.agent}: {d.action} {d.market_ticker || ""} — {d.reason}
                      </div>
                    ))}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="card">
          <h3>Paper orders</h3>
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
                  <td>{o.price}¢ paper</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
