// =============================================================================
// API Types
// =============================================================================

export interface League {
  league_id: string;
  display_name: string;
  sport: 'basketball' | 'soccer';
}

export interface Market {
  ticker: string;
  subtitle: string;
  market_type: string;
  yes_bid: number | null;
  yes_ask: number | null;
  no_bid: number | null;
  no_ask: number | null;
  last_price: number | null;
  volume: number;
}

export interface Event {
  event_id: string;
  title: string;
  league: string;
  close_time: string | null;
  markets: Market[];
}

export interface LeagueData {
  league_id: string;
  display_name: string;
  sport: string;
  events: Event[];
}

export interface OrderbookLevel {
  price: number;
  quantity: number;
}

// Orderbook can receive data in either array format [[price, qty], ...] or object format [{price, quantity}, ...]
export interface Orderbook {
  ticker: string;
  yes: (OrderbookLevel | [number, number])[];
  no: (OrderbookLevel | [number, number])[];
}

export interface Trade {
  trade_id: string | null;
  ticker: string;
  price: number | null;
  yes_price: number | null;
  no_price: number | null;
  count: number;
  taker_side: 'yes' | 'no' | null;
  created_time: string | null;
}

export interface Candlestick {
  timestamp: string | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number;
  yes_price: number | null;
}

export interface TickerData {
  ticker: string;
  yes_bid: number | null;
  yes_ask: number | null;
  no_bid: number | null;
  no_ask: number | null;
  last_price: number | null;
  volume: number | null;
}

// =============================================================================
// WebSocket Message Types
// =============================================================================

export type WSMessageType = 
  | 'orderbook'
  | 'trade'
  | 'trades'
  | 'ticker'
  | 'trades_history'
  | 'subscribed'
  | 'unsubscribed'
  | 'error'
  | 'ping'
  | 'pong';

export interface WSMessage {
  type: WSMessageType;
  ticker?: string;
  tickers?: string[];
  data?: unknown;
  message?: string;
}

export interface WSOrderbookMessage extends WSMessage {
  type: 'orderbook';
  ticker: string;
  data: {
    yes: [number, number][];
    no: [number, number][];
  };
}

export interface WSTradeMessage extends WSMessage {
  type: 'trade';
  ticker: string;
  data: Trade;
}

export interface WSTickerMessage extends WSMessage {
  type: 'ticker';
  ticker: string;
  data: TickerData;
}

// =============================================================================
// UI State Types
// =============================================================================

export interface SelectedMarket {
  ticker: string;
  subtitle: string;
  eventTitle: string;
  league: string;
  viewSide: 'yes' | 'no';  // Which side to display prices for (YES = over, NO = under)
}

export interface TradeWithMeta extends Trade {
  ticker: string;
  subtitle?: string;
}

export interface ChartDataPoint {
  time: number;
  value: number;
}

export interface TradeStats {
  mean: number;
  std: number;
  count: number;
  min: number;
  max: number;
}
