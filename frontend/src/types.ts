// Shared contract between the Courtside backend (FastAPI) and this UI.
// Every shape here is produced by courtside/api — see docs/API.md for endpoints.
// Prices are integer cents (1-99). Money is dollars. Probabilities are 0-1.

export type TradingMode = 'paper' | 'live'
export type DataSource = 'sim' | 'live'
export type RiskLevel = 'low' | 'medium' | 'high'

export interface Settings {
  trading_mode: TradingMode
  data_source: DataSource
  agent_enabled: boolean
  max_stake_per_trade: number
  max_open_positions: number
  max_daily_loss: number
  max_total_exposure: number
  /** Claude reviews each entry before the order goes out. */
  claude_review: boolean
  /** Simulated game clock multiplier (sim data source only). */
  sim_speed: number
}

export interface FeedStatus {
  ok: boolean
  detail: string
  updated_at: string | null
}

export interface Health {
  kalshi_keys: boolean
  kalshi_env: 'demo' | 'prod'
  anthropic: boolean
  odds_api: boolean
  feeds: { scores: FeedStatus; kalshi: FeedStatus; fanduel: FeedStatus }
}

export interface AgentStatus {
  /** idle = enabled but nothing to do; watching = tracking live games. */
  state: 'paused' | 'idle' | 'watching' | 'acting'
  last_tick: string | null
  /** One-line description of what it is looking at right now. */
  focus: string
  ticks: number
}

export interface Account {
  cash: number
  equity: number
  exposure: number
  pnl_today: number
  pnl_total: number
  wins: number
  losses: number
  open_positions: number
}

export interface AppState {
  settings: Settings
  health: Health
  agent: AgentStatus
  account: Account
}

export interface TeamSide {
  abbr: string
  name: string
  score: number
  /** Hex color without '#'. */
  color: string
  /** Points by period so far: [Q1, Q2, Q3, Q4, OT...]. The current period is a running count. */
  quarters: number[]
}

/** Which part of the game a market covers. */
export type Segment = 'game' | 'q1' | 'q2' | 'q3' | 'q4'
export type MarketKind = 'total' | 'spread'

export interface Projection {
  /** Expected final total. */
  mean: number
  /** One standard deviation of the final total, in points. */
  sd: number
  /** Probability the game goes to overtime. */
  p_ot: number
  /** Current scoring pace in points per 48 minutes. */
  pace: number
}

export interface FanDuelOdds {
  total_line: number | null
  /** American odds, e.g. -110. */
  over_price: number | null
  under_price: number | null
  /** Home spread, e.g. -4.5. */
  spread: number | null
  home_ml: number | null
  away_ml: number | null
  /** True when the line is an in-play line rather than the pregame close. */
  live: boolean
  /** Where the number came from: FanDuel via The Odds API, the simulator, or ESPN's pregame consensus fallback. */
  source: 'fanduel' | 'sim' | 'espn'
  updated_at: string
}

/**
 * One Kalshi market. Every market is a YES/NO contract:
 *   total  — YES = over the strike,  NO = under.
 *   spread — YES = `team` wins the segment by more than the strike, NO = they do not
 *            (the same thing as the other side "plus the points").
 * Field names keep the totals vocabulary: "over" always means YES and "under" always means NO.
 * Use `yes_label` / `no_label` for display rather than building text from those names.
 */
export interface LadderRung {
  ticker: string
  segment: Segment
  kind: MarketKind
  /** Spread markets only: the team the YES side backs (abbreviation). */
  team: string | null
  /** Short display names for each side, e.g. "Over 58.5" / "Under 58.5", or "HOU -3.5" / "IND +3.5". */
  yes_label: string
  no_label: string
  /** The line, e.g. 250.5 points, or 3.5 for a spread. */
  strike: number
  yes_bid: number | null
  yes_ask: number | null
  no_bid: number | null
  no_ask: number | null
  /** Model probability the NO side wins (for a total: finishes under the strike). */
  p_under: number
  /** Model probability minus the cost of buying NO (no_ask). Positive = cheap. */
  edge_under: number | null
  edge_over: number | null
  volume: number
}

export interface GameRisk {
  level: RiskLevel
  /** Short human flags, e.g. "2-pt game, 1:40 left — foul/OT risk". */
  flags: string[]
}

/** One quarter's running state. Cheap enough to ride along on every game update. */
export interface QuarterSummary {
  segment: Segment // 'q1'..'q4'
  label: string // "Q1"
  status: 'upcoming' | 'live' | 'final'
  home_points: number
  away_points: number
  /** Seconds left in this quarter (720 before it starts, 0 once over). */
  seconds_remaining: number
  /** Model view of where the quarter finishes. null once it is final. */
  projection: { total_mean: number; total_sd: number; margin_mean: number; margin_sd: number } | null
}

/** A quarter's tradable markets. Only sent with GameDetail (too heavy for every tick). */
export interface QuarterMarkets {
  segment: Segment
  totals: LadderRung[]
  spreads: LadderRung[]
}

/** One thing happening on the floor, in a sentence. `lean` is which way it pushes points scored. */
export interface PatternNote {
  key: string
  text: string
  lean: 'up' | 'down' | null
  team: string | null
  weight: number
}

export interface TeamFloor {
  abbr: string
  side: 'home' | 'away'
  /** Team fouls in the current period. */
  fouls: number
  /** True when this team's next foul sends the other team to the free-throw line. */
  penalty: boolean
  /** Player ids on the floor (see GameDetail.players). */
  on_court: string[]
  starters_on: number
  /** Points in the last 5 minutes of game time. */
  last5: number
}

/** What is happening on the floor. From ESPN play-by-play, or made up in practice games. */
export interface GamePatterns {
  source: 'espn' | 'practice'
  updated_at: string
  period: number
  teams: TeamFloor[]
  notes: PatternNote[]
  out: { team: string; names: string[] }[]
  final?: boolean
}

export interface PlayerLine {
  id: string
  name: string
  short: string
  team: string
  starter: boolean
  on_court: boolean
  minutes: number
  points: number
  fgm: number
  fga: number
  tpm: number
  tpa: number
  ftm: number
  fta: number
  fouls: number
  plus_minus: number
}

export interface Game {
  id: string
  event_ticker: string | null
  label: string // "MEM @ CLE"
  home: TeamSide
  away: TeamSide
  state: 'pre' | 'live' | 'final'
  period: number // 1-4, 5+ = OT
  clock: string // "7:42"
  /** Regulation seconds remaining (0 in OT / final). */
  seconds_remaining: number
  total: number
  margin: number
  start_time: string
  pregame_total: number | null
  projection: Projection | null
  fanduel: FanDuelOdds | null
  /** Full-game total ladder. */
  ladder: LadderRung[]
  /** Where the model has the full-game margin (home minus away) ending. null once final. */
  margin_projection?: { margin_mean: number; margin_sd: number } | null
  /** Always four entries, Q1-Q4. */
  quarters: QuarterSummary[]
  risk: GameRisk
  simulated: boolean
  /** What is happening on the floor. null until the first read. */
  patterns?: GamePatterns | null
}

export interface TimelinePoint {
  /** Game seconds elapsed (0-2880 regulation). */
  t: number
  total: number
  projected: number
  /** Projection band (mean ± 1 sd). */
  lo: number
  hi: number
  line: number | null
}

/** One moment in a quarter. `t` is seconds into the quarter (0-720); margins are home minus away. */
export interface QuarterPoint {
  t: number
  total: number
  projected: number
  lo: number
  hi: number
  /** Kalshi's 50/50 quarter total. */
  line: number | null
  margin: number
  m_projected: number
  m_lo: number
  m_hi: number
  /** Kalshi's 50/50 quarter margin. */
  m_line: number | null
}

export interface GameDetail {
  game: Game
  /** Full-game spreads (overtime counts). Empty when Kalshi has no market. */
  game_spreads?: LadderRung[]
  /** Quarter totals and spreads, Q1-Q4. Lists are empty when Kalshi has no market. */
  quarter_markets: QuarterMarkets[]
  timeline: TimelinePoint[]
  /** Per-quarter history, keyed 'q1'..'q4'. A quarter appears once it has started. */
  quarter_timelines?: Partial<Record<Segment, QuarterPoint[]>>
  /** Every player's line so far. Empty before tip-off. */
  players?: PlayerLine[]
  decisions: Decision[]
  positions: Position[]
}

/** 'over' = the YES side of the market, 'under' = the NO side. See LadderRung. */
export type Side = 'under' | 'over'

export interface Position {
  id: number
  game_id: string
  game_label: string
  ticker: string
  segment: Segment
  kind: MarketKind
  team: string | null
  /** What was bought, ready to show: "Under 251.5", "Q2 Over 58.5", "Q1 HOU -3.5". */
  label: string
  strike: number
  side: Side
  contracts: number
  entry_price: number
  mark_price: number
  cost: number
  value: number
  pnl: number
  max_profit: number
  /** Model probability this position wins right now. */
  p_win: number
  /** p_win at entry, for comparison. */
  p_win_entry: number
  opened_at: string
  opened_by: 'agent' | 'user'
  mode: TradingMode
  simulated: boolean
  strategy_id: string | null
  exit_profile: string | null
  /** Your bet only: the agent may sell it if it goes badly wrong. */
  watch: boolean
  /** Claude's latest read on a watched bet. */
  watch_note: WatchNote | null
  risk: GameRisk
}

export type ExitReason =
  | 'settled_win'
  | 'settled_loss'
  | 'risk_exit'
  | 'stop_loss'
  | 'take_profit'
  | 'manual'

export interface Trade {
  id: number
  game_id: string
  game_label: string
  ticker: string
  segment: Segment
  kind: MarketKind
  team: string | null
  /** Same wording as Position.label. */
  label: string
  strike: number
  side: Side
  contracts: number
  entry_price: number
  exit_price: number
  cost: number
  pnl: number
  opened_at: string
  closed_at: string
  opened_by: 'agent' | 'user'
  mode: TradingMode
  simulated: boolean
  strategy_id: string | null
  exit_reason: ExitReason
  /** What holding to settlement would have paid. null until the game is final. */
  counterfactual_pnl: number | null
  /** For early exits once the game is final: did selling beat holding? */
  exit_verdict: 'saved' | 'shaken_out' | null
  /** The number the market settled on: the total, or for a spread the backed team's margin. */
  final_total: number | null
}

export type DecisionKind = 'enter' | 'skip' | 'hold' | 'exit' | 'note'

export interface Decision {
  id: number
  ts: string
  game_id: string | null
  game_label: string | null
  kind: DecisionKind
  ticker: string | null
  headline: string
  reasoning: string
  confidence: number
  /** Key numbers behind the call, shown as chips. */
  data: Record<string, number | string>
  source: 'rules' | 'model' | 'claude'
  memory_ids: number[]
}

export interface ParamSpec {
  key: string
  label: string
  help: string
  group: 'entry' | 'sizing' | 'exit'
  value: number
  min: number
  max: number
  step: number
  unit: string // "pts" | "¢" | "$" | "min" | "%" | ""
}

export interface Strategy {
  id: string
  name: string
  description: string
  enabled: boolean
  params: ParamSpec[]
  stats: { trades: number; win_rate: number; pnl: number }
}

export type MemoryKind = 'guidance' | 'lesson' | 'episode'

export interface Memory {
  id: number
  kind: MemoryKind
  text: string
  tags: string[]
  /** 0-1: how much weight the agent gives it. */
  importance: number
  /** 0-1: how well outcomes have supported it. */
  confidence: number
  /** Trades that confirmed (+) and contradicted (−) this memory. */
  support: number
  against: number
  pinned: boolean
  source: 'user' | 'agent'
  simulated: boolean
  trade_id: number | null
  created_at: string
  last_used_at: string | null
  uses: number
}

export interface Arm {
  key: string
  label: string
  dims: { buffer: string; time: string; margin: string }
  n: number
  wins: number
  sim_n: number
  /** Mean P&L per dollar risked. */
  mean_return: number
  /** Posterior win probability (model prior blended with outcomes). */
  p_win: number
  prior: number
  /** Break-even win rate at the typical entry price for this arm. */
  breakeven: number
}

export interface ExitArm {
  key: string
  label: string
  description: string
  n: number
  mean_return: number
  saved: number
  shaken_out: number
  /** Share of entries currently being assigned this profile. */
  share: number
}

/**
 * One line of the agent's shadow book for quarter markets: what happened to everyone who
 * could have bought this kind of contract at this kind of price. The agent records prices
 * shortly after a quarter starts ('open') and again with about six minutes left ('mid'),
 * then scores them when the quarter ends. It places no orders of its own here.
 */
export interface QuarterCell {
  segment: Segment
  kind: MarketKind
  checkpoint: 'open' | 'mid'
  /** 'over' = YES side, 'under' = NO side. */
  side: Side
  /** Price band of the side bought, e.g. "80-97". Ordered cheap to expensive. */
  bucket: string
  n: number
  /** Average ask paid, cents. */
  price: number
  /** How often that side won. */
  win_rate: number
  /** What the model thought the win rate was. */
  model: number
  /** Average profit per dollar risked, after fees. */
  ret: number
}

export interface QuarterLearning {
  /** Markets recorded so far, and how many of those have settled. */
  observations: number
  settled: number
  games: number
  cells: QuarterCell[]
  /** The user's own quarter trades, by quarter and market type. */
  your_trades: { segment: Segment; kind: MarketKind; n: number; wins: number; pnl: number }[]
}

/** How trades went, grouped by a pattern that was showing when they were placed. key 'all' is every trade. */
export interface PatternRecord {
  key: string
  label: string
  trades: number
  wins: number
  pnl: number
  /** How many of them were the user's own trades. */
  yours: number
}

export interface LearningState {
  patterns?: PatternRecord[]
  /** Quarter totals and spreads: watched and scored, not traded by the agent. */
  quarters: QuarterLearning
  arms: Arm[]
  exit_arms: ExitArm[]
  calibration: { bucket: string; predicted: number; actual: number; n: number }[]
  equity_curve: { ts: string; equity: number; simulated: boolean }[]
  totals: {
    trades: number
    win_rate: number
    avg_win: number
    avg_loss: number
    expectancy: number
    exits_saved: number
    exits_shaken: number
    sim_episodes: number
  }
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  text: string
  ts: string
  /** Tools the agent used while answering, for display. */
  tools: { name: string; summary: string }[]
}

/** POST /api/chat streams these as server-sent events (`data: <json>\n\n`). */
export type ChatEvent =
  | { type: 'text'; delta: string }
  | { type: 'tool'; name: string; summary: string }
  | { type: 'done'; message: ChatMessage }
  | { type: 'error'; message: string }

/** Messages pushed over the /ws WebSocket. */
export type WsEvent =
  | { type: 'state'; data: AppState }
  | { type: 'games'; data: Game[] }
  | { type: 'positions'; data: Position[] }
  | { type: 'account'; data: Account }
  | { type: 'decision'; data: Decision }
  | { type: 'trade'; data: Trade }
  | { type: 'memory'; data: Memory }
  | { type: 'toast'; data: { level: 'info' | 'success' | 'warn' | 'error'; title: string; body: string } }

export interface OrderRequest {
  ticker: string
  side: Side
  contracts: number
  /** Limit price in cents for the side being bought. */
  price: number
  /** Let the agent sell it if it goes badly wrong. */
  watch?: boolean
}

export interface TrainResult {
  episodes: number
  trades: number
  win_rate: number
  pnl: number
  lessons: number
}

export interface WatchNote {
  action: 'sell' | 'hold'
  reason: string
  concern: 'low' | 'medium' | 'high'
  /** Claude's own chance this bet wins, 0-1. */
  win_chance: number
  at: string
}
