import type { CostSummary, Decision, Game, LearningPayload, Portfolio, ReplayFixture, Status } from "./types";

const API = import.meta.env.DEV ? "" : import.meta.env.VITE_API_URL || "";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const detail = (await res.text()).trim();
    throw new Error(detail || `${res.status} ${path}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  status: () => req<Status>("/api/status"),
  upcoming: () => req<{ games: Game[] }>("/api/games/upcoming"),
  live: () => req<{ games: Game[]; caps?: Status["caps"]; pnl?: Status["pnl"] }>("/api/games/live"),
  game: (id: string) =>
    req<{
      game: Game;
      events: import("./types").GameEvent[];
      verdicts: import("./types").Verdict[];
      decisions: Decision[];
      orders: import("./types").Order[];
      positions: import("./types").Position[];
      costs: unknown[];
      pnl: Record<string, unknown>;
      caps: import("./types").Caps;
      paper: boolean;
      reflection?: import("./types").Reflection | null;
      brief?: { id: number; text: string; token_estimate: number; phase: string } | null;
    }>(`/api/games/${id}`),
  portfolio: () => req<Portfolio>("/api/portfolio"),
  costs: () => req<{ today: CostSummary; all: CostSummary }>("/api/costs"),
  pause: () => req("/api/control/pause", { method: "POST" }),
  resume: () => req("/api/control/resume", { method: "POST" }),
  paper: () => req("/api/control/paper", { method: "POST" }),
  liveMode: () => req("/api/control/live", { method: "POST" }),
  limits: (body: {
    max_contracts_per_match?: number;
    max_contracts_per_day?: number;
    max_daily_loss_cents?: number;
  }) => req("/api/control/limits", { method: "POST", body: JSON.stringify(body) }),
  fixtures: () => req<{ fixtures: ReplayFixture[]; runs: Game[] }>("/api/replay/fixtures"),
  replay: (body: { fixture_id?: string; ticker?: string; date?: string }) =>
    req<{
      game: Game;
      events: import("./types").GameEvent[];
      decisions: Decision[];
      orders: import("./types").Order[];
      pnl: Record<string, unknown>;
      fired: string[];
    }>("/api/replay", { method: "POST", body: JSON.stringify(body) }),
  learning: () => req<LearningPayload>("/api/learning"),
  approveProposal: (id: number) => req(`/api/learning/proposals/${id}/approve`, { method: "POST" }),
  rejectProposal: (id: number) => req(`/api/learning/proposals/${id}/reject`, { method: "POST" }),
  shadowProposal: (id: number) => req(`/api/learning/proposals/${id}/shadow`, { method: "POST" }),
  watch: (body: {
    home_team: string;
    away_team: string;
    league?: string;
    kickoff_ts?: number;
    tickers?: string[];
  }) => req("/api/games/watch", { method: "POST", body: JSON.stringify(body) }),
};

export function wsUrl(): string {
  if (!import.meta.env.DEV && import.meta.env.VITE_API_URL) {
    const base = String(import.meta.env.VITE_API_URL).replace(/^http/, "ws");
    return `${base}/ws/events`;
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws/events`;
}
