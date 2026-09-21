import { CapsBar } from "../components/CapsBar";
import { Controls } from "../components/Controls";
import { DecisionsTable } from "../components/DecisionsTable";
import { GameCard } from "../components/GameCard";
import type { Game, Status } from "../types";

export function Live({
  games,
  status,
  reload,
}: {
  games: Game[];
  status: Status | null;
  reload: () => void;
}) {
  const decisions = games.flatMap((g) => g.decisions || []);
  return (
    <>
      <div className="topbar">
        <div>
          <h1>Live</h1>
          <p className="lede">Score, rem, No price, paper would-decisions, remaining caps.</p>
        </div>
        <Controls status={status} onChange={reload} />
      </div>
      <CapsBar caps={status?.caps || games[0]?.caps} pnl={status?.pnl} />
      {games.length === 0 ? (
        <div className="empty">No live matches. Pollers start at kickoff, or run a Replay.</div>
      ) : (
        <div className="grid">
          {games.map((game) => (
            <GameCard key={game.id} game={game} live />
          ))}
        </div>
      )}
      {decisions.length > 0 && (
        <div className="card" style={{ marginTop: 18 }}>
          <h3>Would-decisions</h3>
          <DecisionsTable decisions={decisions} />
        </div>
      )}
    </>
  );
}
