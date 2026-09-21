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
  decisions?: Decision[];
  caps?: Caps;
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

export type Decision = {
  id: number;
  game_id: string;
  event_id: number | null;
  agent: string;
  market_ticker: string | null;
  action: string;
  size: number;
  price: number | null;
  rem: number | null;
  reason: string;
  paper: number;
  created_at: number;
  outcome?: string | null;
  process_grade?: string | null;
  realized_pnl_cents?: number | null;
  counterfactual_pnl_cents?: number | null;
  confidence?: number | null;
  playbook_version?: number | null;
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

export type Limits = {
  max_contracts_per_match: number;
  max_contracts_per_day: number;
  max_daily_loss_cents: number;
};

export type Caps = {
  per_match: number;
  per_day: number;
  used_match: number;
  used_today: number;
  remaining_match: number;
  remaining_day: number;
  max_daily_loss_cents: number;
};

export type Pnl = {
  realized_cents: number;
  unrealized_cents: number;
  total_cents: number;
  cap_cents?: number;
  breached?: boolean;
};

export type Status = {
  paper: boolean;
  paused: boolean;
  pause_reason?: string | null;
  paper_only?: boolean;
  kalshi_env: string;
  model: string;
  xai_configured: boolean;
  live_games: number;
  open_positions: number;
  playbook: Record<string, unknown>;
  limits?: Limits;
  caps?: Caps;
  pnl?: Pnl;
};

export type Portfolio = {
  paper: boolean;
  paused?: boolean;
  pause_reason?: string | null;
  positions: Position[];
  orders_today: Order[];
  decisions?: Decision[];
  daily_pnl: Pnl | Record<string, unknown>;
  caps: Caps;
  limits?: Limits;
  pnl?: Pnl;
};

export type ReplayFixture = {
  id: string;
  label: string;
  source: string;
  path?: string;
  ticker?: string;
  home_team?: string;
  away_team?: string;
  league?: string;
  date?: string;
};

export type Lesson = {
  id: number;
  condition: string;
  observation: string;
  suggested_action: string;
  status: string;
  confidence: number;
  support_count: number;
  evidence_game: string | null;
  league: string | null;
};

export type Calibration = {
  id: number;
  agent: string;
  league: string | null;
  n: number;
  brier: number;
  hit_rate: number | null;
};

export type Proposal = {
  id: number;
  status: string;
  title: string;
  motivation: string | null;
  lesson_id: number | null;
  diff: Record<string, unknown>;
  backtest: Record<string, unknown>;
  created_at: number;
  decided_at: number | null;
};

export type Reflection = {
  id: number;
  game_id: string;
  notes: string | null;
  raw?: {
    notes?: string;
    decisions?: Array<{ id?: number; verdict?: string; would_do_differently?: string }>;
    lessons?: unknown[];
    source?: string;
  } | null;
};

export type LearningPayload = {
  lessons: Lesson[];
  calibration: Calibration[];
  proposals: Proposal[];
  playbook: {
    current: number;
    versions: Array<{ version: number; notes: string | null; body?: Record<string, unknown> }>;
    rules: Record<string, unknown>;
  };
  hard_cap_keys: string[];
  propose_only: boolean;
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
