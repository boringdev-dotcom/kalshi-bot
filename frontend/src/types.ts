export type Market = {
  ticker: string;
  game_id: string;
  strike: number | null;
  title: string | null;
  no_bid: number | null;
  no_ask: number | null;
  rem: number | null;
  last_verdict: string | null;
};

export type Game = {
  id: string;
  home_team: string;
  away_team: string;
  league: string | null;
  league_tier: number | null;
  kickoff_ts: number | null;
  status: string;
  home_goals: number;
  away_goals: number;
  minute: number;
  phase: string;
  red_cards: number;
  prematch: Record<string, unknown> | null;
  markets: Market[];
  verdicts?: Record<string, { verdict: string; reason: string }>;
  positions?: Position[];
};

export type Position = {
  market_ticker: string;
  game_id: string;
  side: string;
  count: number;
  avg_price: number | null;
  paper: number;
  stopped: number;
};

export type GameEvent = {
  id: number;
  game_id: string;
  event_type: string;
  minute: number;
  payload: Record<string, unknown>;
  created_at: number;
};

export type Verdict = {
  id: number;
  agent: string;
  market_ticker: string | null;
  verdict: string | null;
  size_hint: number | null;
  reason: string;
  created_at: number;
};

export type Order = {
  id: number;
  market_ticker: string;
  action: string;
  count: number;
  price: number | null;
  paper: number;
  status: string;
  reason: string | null;
  created_at: number;
};

export type Status = {
  paper: boolean;
  paused: boolean;
  kalshi_env: string;
  model: string;
  xai_configured: boolean;
  live_games: number;
  open_positions: number;
  playbook: Record<string, unknown>;
};

export type Portfolio = {
  paper: boolean;
  positions: Position[];
  orders_today: Order[];
  daily_pnl: Record<string, unknown>;
  caps: { per_match: number; per_day: number; used_today: number };
};

export type CostSummary = {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  by_game: Array<{
    game_id: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
  }>;
  rows: Array<{
    id: number;
    game_id: string | null;
    agent: string;
    model: string;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
    created_at: number;
  }>;
};
