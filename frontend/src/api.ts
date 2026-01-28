import type { LeagueData, League, Orderbook, Trade, Candlestick, Market } from './types';

// API base URL - defaults to /api for same-origin, or use VITE_API_URL for cross-origin
const API_BASE = import.meta.env.VITE_API_URL || '/api';

// =============================================================================
// API Functions
// =============================================================================

export async function fetchLeagues(): Promise<League[]> {
  const response = await fetch(`${API_BASE}/leagues`);
  if (!response.ok) {
    throw new Error(`Failed to fetch leagues: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchMarkets(league?: string): Promise<LeagueData[]> {
  const url = league ? `${API_BASE}/markets?league=${league}` : `${API_BASE}/markets`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch markets: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchMarket(ticker: string): Promise<Market> {
  const response = await fetch(`${API_BASE}/markets/${ticker}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch market ${ticker}: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchOrderbook(ticker: string, depth?: number): Promise<Orderbook> {
  const url = depth 
    ? `${API_BASE}/markets/${ticker}/orderbook?depth=${depth}` 
    : `${API_BASE}/markets/${ticker}/orderbook`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch orderbook for ${ticker}: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchTrades(
  ticker: string, 
  limit: number = 100
): Promise<{ trades: Trade[]; cursor: string | null }> {
  const response = await fetch(`${API_BASE}/markets/${ticker}/trades?limit=${limit}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch trades for ${ticker}: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchCandlesticks(
  ticker: string,
  periodInterval: number = 1,
  startTs?: number,
  endTs?: number
): Promise<{ candlesticks: Candlestick[] }> {
  let url = `${API_BASE}/markets/${ticker}/candlesticks?period_interval=${periodInterval}`;
  if (startTs) url += `&start_ts=${startTs}`;
  if (endTs) url += `&end_ts=${endTs}`;
  
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch candlesticks for ${ticker}: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchLiveData(ticker: string): Promise<{
  ticker: string;
  market: Market;
  orderbook: Orderbook;
  trades: Trade[];
  timestamp: string;
}> {
  const response = await fetch(`${API_BASE}/live/${ticker}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch live data for ${ticker}: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchLiveDataMulti(tickers: string[]): Promise<{
  data: Record<string, { orderbook: Orderbook; trades: Trade[] } | { error: string }>;
  timestamp: string;
}> {
  const response = await fetch(`${API_BASE}/live-multi?tickers=${tickers.join(',')}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch live data: ${response.statusText}`);
  }
  return response.json();
}

// =============================================================================
// Odds API Functions (proxied through backend)
// =============================================================================

export interface OddsApiGame {
  id: string;
  sport_key: string;
  sport_title: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  bookmakers: Array<{
    key: string;
    title: string;
    markets: Array<{
      key: string;
      outcomes: Array<{
        name: string;
        price: number;
        point?: number;
      }>;
    }>;
  }>;
}

export async function fetchNBAOdds(): Promise<OddsApiGame[]> {
  const response = await fetch(`${API_BASE}/odds/nba`);
  if (!response.ok) {
    if (response.status === 503) {
      throw new Error('Odds API not configured on server');
    }
    throw new Error(`Failed to fetch NBA odds: ${response.statusText}`);
  }
  return response.json();
}

// =============================================================================
// Research API Functions
// =============================================================================

export interface ResearchGame {
  match_id: string;
  title: string;
  league: string;
  league_display: string;
  sport: string;
  market_count: number;
  close_time: string | null;
  markets: Array<{
    ticker: string;
    subtitle: string;
    market_type: string;
    yes_bid?: number;
    yes_ask?: number;
    volume?: number;
  }>;
}

export interface ResearchJobRequest {
  sport: string;
  match_id: string;
  prompt_version: string;
}

export interface ComboResearchJobRequest {
  sport: string;
  match_ids: string[];
  use_combined_analysis: boolean;
}

export interface ResearchJobResponse {
  job_id: string;
  status: string;
  created_at: string;
}

export interface ResearchJob {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  sport: string;
  match_id: string;
  prompt_version?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  result?: {
    title: string;
    research: string;
    analyses: Record<string, string>;
    reviews: Record<string, string>;
    final_recommendation: string;
    metadata: Record<string, any>;
  };
  error?: string;
}

export async function fetchResearchGames(): Promise<{ games: ResearchGame[]; count: number }> {
  const response = await fetch(`${API_BASE}/research/games`);
  if (!response.ok) {
    throw new Error(`Failed to fetch research games: ${response.statusText}`);
  }
  return response.json();
}

export async function startResearchJob(request: ResearchJobRequest): Promise<ResearchJobResponse> {
  const response = await fetch(`${API_BASE}/research/run`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to start research job: ${response.statusText}`);
  }
  return response.json();
}

export async function getResearchJob(jobId: string): Promise<ResearchJob> {
  const response = await fetch(`${API_BASE}/research/jobs/${jobId}`);
  if (!response.ok) {
    throw new Error(`Failed to get research job: ${response.statusText}`);
  }
  return response.json();
}

export async function listResearchJobs(limit: number = 20): Promise<{ jobs: ResearchJob[] }> {
  const response = await fetch(`${API_BASE}/research/jobs?limit=${limit}`);
  if (!response.ok) {
    throw new Error(`Failed to list research jobs: ${response.statusText}`);
  }
  return response.json();
}

export async function startComboResearchJob(request: ComboResearchJobRequest): Promise<ResearchJobResponse> {
  const response = await fetch(`${API_BASE}/research/combo`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to start combo research job: ${response.statusText}`);
  }
  return response.json();
}
