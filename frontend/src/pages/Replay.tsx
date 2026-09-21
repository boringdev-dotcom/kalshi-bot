import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { DecisionsTable } from "../components/DecisionsTable";
import type { Decision, Game, GameEvent, ReplayFixture, Status } from "../types";

export function Replay({ status, reload }: { status: Status | null; reload: () => void }) {
  const [fixtures, setFixtures] = useState<ReplayFixture[]>([]);
  const [runs, setRuns] = useState<Game[]>([]);
  const [selected, setSelected] = useState("");
  const [ticker, setTicker] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{
    game: Game;
    events: GameEvent[];
    decisions: Decision[];
    pnl: Record<string, unknown>;
    fired: string[];
  } | null>(null);

  const load = () => {
    api.fixtures().then((r) => {
      setFixtures(r.fixtures);
      setRuns(r.runs);
      if (!selected && r.fixtures[0]) setSelected(r.fixtures[0].id);
    }).catch(() => undefined);
  };

  useEffect(() => {
    load();
  }, [status?.paper]);

  const onRun = (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    api
      .replay({
        fixture_id: ticker ? undefined : selected || undefined,
        ticker: ticker || undefined,
      })
      .then((r) => {
        setResult(r);
        load();
        reload();
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Replay failed");
      })
      .finally(() => setBusy(false));
  };

  const pnl = result?.pnl || {};
  return (
    <>
      <div className="topbar">
        <div>
          <h1>Replay</h1>
          <p className="lede">
            Drive a past scoreline through the watcher and see paper would-place / would-skip / would-flatten. No live orders.
          </p>
        </div>
      </div>
      <form className="form replay-form" onSubmit={onRun}>
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {fixtures.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label}
            </option>
          ))}
        </select>
        <input
          placeholder="Or Phase 0 / Kalshi ticker"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
        />
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Replaying…" : "Run paper replay"}
        </button>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
      </form>
      {runs.length > 0 && (
        <p className="meta" style={{ marginTop: 12 }}>
          Past runs:{" "}
          {runs.map((g) => (
            <Link key={g.id} to={`/games/${g.id}`} style={{ marginRight: 12 }}>
              {g.home_team} vs {g.away_team}
            </Link>
          ))}
        </p>
      )}
      {result && (
        <div className="grid" style={{ marginTop: 18 }}>
          <div className="card">
            <h3>
              {result.game.home_team} {result.game.home_goals}–{result.game.away_goals} {result.game.away_team}
            </h3>
            <p className="meta">
              {result.fired.join(" → ")} · hypothetical P&amp;L {String(pnl.total_cents ?? 0)}¢
              {" "}(realized {String(pnl.realized_cents ?? 0)}¢)
            </p>
            <div className="timeline">
              {result.events.map((event) => (
                <div className="event" key={event.id}>
                  <strong>{event.event_type}</strong> · {event.minute}'
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <h3>Would-decisions</h3>
            <DecisionsTable decisions={result.decisions} />
          </div>
        </div>
      )}
    </>
  );
}
