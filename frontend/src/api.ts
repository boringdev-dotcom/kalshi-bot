import type { CostSummary, Game, Portfolio, Status } from "./types";

// Vite injects Cloud Agent / Render VITE_API_URL even during `npm run dev`.
// Local development must stay on the same-origin proxy so watch/pause hit
// the local FastAPI instead of a deployed host.
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
  live: () => req<{ games: Game[] }>("/api/games/live"),
  game: (id: string) =>
    req<{
      game: Game;
      events: import("./types").GameEvent[];
      verdicts: import("./types").Verdict[];
      orders: import("./types").Order[];
      positions: import("./types").Position[];
      costs: unknown[];
      pnl: Record<string, unknown>;
    }>(`/api/games/${id}`),
  portfolio: () => req<Portfolio>("/api/portfolio"),
  costs: () => req<{ today: CostSummary; all: CostSummary }>("/api/costs"),
  pause: () => req("/api/control/pause", { method: "POST" }),
  resume: () => req("/api/control/resume", { method: "POST" }),
  paper: () => req("/api/control/paper", { method: "POST" }),
  liveMode: () => req("/api/control/live", { method: "POST" }),
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
