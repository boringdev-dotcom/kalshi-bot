import { FormEvent, useState } from "react";
import { api } from "../api";
import { Controls } from "../components/Controls";
import { GameCard } from "../components/GameCard";
import type { Game, Status } from "../types";

export function Upcoming({
  games,
  status,
  reload,
}: {
  games: Game[];
  status: Status | null;
  reload: () => void;
}) {
  const [home, setHome] = useState("");
  const [away, setAway] = useState("");
  const [league, setLeague] = useState("");
  const [ticker, setTicker] = useState("");

  const onAdd = (event: FormEvent) => {
    event.preventDefault();
    api
      .watch({
        home_team: home,
        away_team: away,
        league: league || undefined,
        tickers: ticker ? [ticker] : [],
        kickoff_ts: Math.floor(Date.now() / 1000) + 3600,
      })
      .then(() => {
        setHome("");
        setAway("");
        setLeague("");
        setTicker("");
        reload();
      });
  };

  return (
    <>
      <div className="topbar">
        <div>
          <h1>Upcoming</h1>
          <p className="lede">Kalshi soccer totals kicking off in the next six hours, matched to FotMob/ESPN.</p>
        </div>
        <Controls status={status} onChange={reload} />
      </div>
      {games.length === 0 ? <div className="empty">No upcoming boards yet. Add one below or wait for discovery.</div> : (
        <div className="grid">
          {games.filter((g) => g.status !== "live").map((game) => (
            <GameCard key={game.id} game={game} />
          ))}
        </div>
      )}
      <form className="form" onSubmit={onAdd}>
        <input placeholder="Home team" value={home} onChange={(e) => setHome(e.target.value)} required />
        <input placeholder="Away team" value={away} onChange={(e) => setAway(e.target.value)} required />
        <input placeholder="League" value={league} onChange={(e) => setLeague(e.target.value)} />
        <input placeholder="Kalshi ticker (optional)" value={ticker} onChange={(e) => setTicker(e.target.value)} />
        <button className="ghost" type="submit">Watch game</button>
      </form>
    </>
  );
}
