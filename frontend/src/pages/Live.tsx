import { GameCard } from "../components/GameCard";
import { Controls } from "../components/Controls";
import type { Game, Status } from "../types";

export function Live({ games, status, reload }: { games: Game[]; status: Status | null; reload: () => void }) {
  return (
    <>
      <div className="topbar">
        <div>
          <h1>Live</h1>
          <p className="lede">Score, minute, rem per market, No price, latest Pundit verdict, held size.</p>
        </div>
        <Controls status={status} onChange={reload} />
      </div>
      {games.length === 0 ? (
        <div className="empty">No live matches. Pollers start at kickoff.</div>
      ) : (
        <div className="grid">
          {games.map((game) => (
            <GameCard key={game.id} game={game} live />
          ))}
        </div>
      )}
    </>
  );
}
