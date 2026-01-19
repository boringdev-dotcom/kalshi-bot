# Kalshi Live Market Dashboard

Real-time trading dashboard for Kalshi markets built with React + TypeScript.

## Features

- **Live Price Charts**: Multi-series line charts with real-time updates using lightweight-charts
- **Order Books**: Live bid/ask depth visualization for selected markets
- **Trades Panel**: Scatter plot and table view of recent trades with statistics
- **Market Selector**: Browse markets by sport/league/event hierarchy
- **WebSocket Updates**: Real-time data streaming from Kalshi API

## Prerequisites

- Node.js 18+ 
- Python 3.11+ (for the backend)
- Kalshi API credentials

## Getting Started

### 1. Install Frontend Dependencies

```bash
cd frontend
npm install
```

### 2. Start the Backend API

In the project root directory:

```bash
# Make sure you have the environment variables set
# KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PEM, etc.

uvicorn src.api:app --reload --port 8000
```

### 3. Start the Frontend Dev Server

```bash
cd frontend
npm run dev
```

The dashboard will be available at `http://localhost:5173`

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── ConnectionStatus.tsx  # WebSocket connection indicator
│   │   ├── MarketSelector.tsx    # League/event/market picker
│   │   ├── Orderbook.tsx         # Order book visualization
│   │   ├── PriceChart.tsx        # Price chart using lightweight-charts
│   │   └── TradesPanel.tsx       # Trades scatter plot & table
│   ├── hooks/
│   │   └── useWebSocket.ts       # WebSocket connection hook
│   ├── api.ts                    # REST API client functions
│   ├── types.ts                  # TypeScript type definitions
│   ├── App.tsx                   # Main app component
│   ├── main.tsx                  # Entry point
│   └── index.css                 # Global styles (Tailwind)
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── tsconfig.json
```

## API Endpoints

The frontend connects to these backend endpoints:

### REST API

- `GET /api/leagues` - List available leagues
- `GET /api/markets` - List markets grouped by event
- `GET /api/markets/{ticker}` - Get market details
- `GET /api/markets/{ticker}/orderbook` - Get order book
- `GET /api/markets/{ticker}/trades` - Get recent trades
- `GET /api/markets/{ticker}/candlesticks` - Get price history
- `GET /api/live/{ticker}` - Get live snapshot (orderbook + trades)
- `GET /api/live-multi?tickers=X,Y` - Get live data for multiple markets

### WebSocket

- `WS /ws/market-data` - Real-time market data stream

Messages:
```json
// Subscribe
{"action": "subscribe", "tickers": ["TICKER1", "TICKER2"]}

// Unsubscribe
{"action": "unsubscribe", "tickers": ["TICKER1"]}

// Server messages
{"type": "orderbook", "ticker": "...", "data": {...}}
{"type": "trade", "ticker": "...", "data": {...}}
{"type": "ticker", "ticker": "...", "data": {...}}
```

## Development

### Build for Production

```bash
npm run build
```

The build output will be in the `dist/` directory.

### Type Checking

```bash
npm run lint
```

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool
- **Tailwind CSS** - Styling
- **lightweight-charts** - TradingView charting library
- **Lucide React** - Icons
