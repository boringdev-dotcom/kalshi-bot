import { Link } from "react-router-dom";
import type { Game } from "../types";

function kickoffLabel(ts: number | null): string {
  if (!ts) return "kickoff TBD";
  return new Date(ts * 1000).toLocaleString(undefined, {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function GameCard({ game, live }: { game: Game; live?: boolean }) {
  return (
    <Link className="card" to={`/games/${game.id}`}>
      <div className="meta">
        {game.league || "league"} · {live ? `${game.minute}' ${game.phase}` : kickoffLabel(game.kickoff_ts)}
      </div>
      <h3>
        {game.home_team} vs {game.away_team}
      </h3>
      {live && (
        <div className="score">
          {game.home_goals}–{game.away_goals}
        </div>
      )}
      <div className="markets">
        {(game.markets || []).map((market) => {
          const verdict = game.verdicts?.[market.ticker]?.verdict || market.last_verdict;
          return (
            <div className="market-row" key={market.ticker}>
              <span>{market.strike ?? "—"} tot</span>
              <span className="chip">rem {market.rem ?? "—"}</span>
              <span className="chip">No {market.no_ask ?? "—"}¢</span>
              <span className={`chip ${verdict || ""}`}>{verdict || "—"}</span>
            </div>
          );
        })}
      </div>
    </Link>
  );
}
