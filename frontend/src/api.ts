import type { LeagueData, League, Orderbook, Trade, Candlestick, Market } from './types';

const API_BASE = '/api';

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
