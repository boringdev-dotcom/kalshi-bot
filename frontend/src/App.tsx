import { useCallback, useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { api } from "./api";
import { Layout } from "./components/Layout";
import { Costs } from "./pages/Costs";
import { GameDetail } from "./pages/GameDetail";
import { Live } from "./pages/Live";
import { Portfolio } from "./pages/Portfolio";
import { Replay } from "./pages/Replay";
import { Upcoming } from "./pages/Upcoming";
import type { CostSummary, Game, Portfolio as PortfolioT, Status } from "./types";
import { useLiveTick } from "./useEvents";

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [upcoming, setUpcoming] = useState<Game[]>([]);
  const [live, setLive] = useState<Game[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioT | null>(null);
  const [today, setToday] = useState<CostSummary | null>(null);
  const [allCosts, setAllCosts] = useState<CostSummary | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => {
    api.status().then(setStatus).catch(() => setStatus(null));
    api.upcoming().then((r) => setUpcoming(r.games)).catch(() => setUpcoming([]));
    api.live().then((r) => setLive(r.games)).catch(() => setLive([]));
    api.portfolio().then(setPortfolio).catch(() => setPortfolio(null));
    api.costs().then((r) => {
      setToday(r.today);
      setAllCosts(r.all);
    }).catch(() => undefined);
    setTick((n) => n + 1);
  }, []);

  const connected = useLiveTick(reload);

  useEffect(() => {
    reload();
    const id = window.setInterval(reload, 15000);
    return () => window.clearInterval(id);
  }, [reload]);

  return (
    <Layout status={status} connected={connected}>
      <Routes>
        <Route path="/" element={<Upcoming games={upcoming} status={status} reload={reload} />} />
        <Route path="/live" element={<Live games={live} status={status} reload={reload} />} />
        <Route path="/replay" element={<Replay status={status} reload={reload} />} />
        <Route path="/games/:id" element={<GameDetail tick={tick} />} />
        <Route path="/portfolio" element={<Portfolio portfolio={portfolio} status={status} reload={reload} />} />
        <Route path="/costs" element={<Costs today={today} all={allCosts} />} />
      </Routes>
    </Layout>
  );
}
