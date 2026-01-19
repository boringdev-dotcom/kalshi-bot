import { useMemo, useState } from 'react';
import type { Trade, SelectedMarket, TradeStats } from '../types';
import { clsx } from 'clsx';
import { BarChart3, List, Filter } from 'lucide-react';

interface TradesPanelProps {
  trades: (Trade & { ticker: string; subtitle?: string })[];
  selectedMarkets: SelectedMarket[];
  compact?: boolean;
}

// Color palette matching the chart
const MARKET_COLORS: Record<string, string> = {};
const COLORS = ['#00d4ff', '#ffab00', '#00c853', '#ff1744', '#7b2cbf', '#ff6d00'];

function getMarketColor(ticker: string, markets: SelectedMarket[]): string {
  if (!MARKET_COLORS[ticker]) {
    const index = markets.findIndex(m => m.ticker === ticker);
    MARKET_COLORS[ticker] = COLORS[index >= 0 ? index % COLORS.length : 0];
  }
  return MARKET_COLORS[ticker];
}

export function TradesPanel({ trades, selectedMarkets, compact = false }: TradesPanelProps) {
  const [view, setView] = useState<'scatter' | 'table'>('table'); // Default to table for clarity
  const [threshold, setThreshold] = useState<number>(0);

  // Calculate statistics
  const stats: TradeStats | null = useMemo(() => {
    const filteredTrades = trades.filter(t => t.count >= threshold);
    if (filteredTrades.length === 0) return null;

    const counts = filteredTrades.map(t => t.count);
    const sum = counts.reduce((a, b) => a + b, 0);
    const mean = sum / counts.length;
    const variance = counts.reduce((a, c) => a + Math.pow(c - mean, 2), 0) / counts.length;
    const std = Math.sqrt(variance);

    return {
      mean,
      std,
      count: filteredTrades.length,
      min: Math.min(...counts),
      max: Math.max(...counts),
    };
  }, [trades, threshold]);

  // Filter trades by threshold
  const filteredTrades = useMemo(() => 
    trades.filter(t => t.count >= threshold),
    [trades, threshold]
  );

  // Format time
  const formatTime = (timeStr: string | null) => {
    if (!timeStr) return '--:--:--';
    const date = new Date(timeStr);
    return date.toLocaleTimeString('en-US', { hour12: false });
  };

  // Get scatter plot dimensions
  const scatterData = useMemo((): {
    points: { x: number; y: number; ticker: string; subtitle?: string; taker_side: string | null }[];
    timeRange: [number, number];
    maxCount: number;
  } => {
    if (filteredTrades.length === 0) return { points: [], timeRange: [0, 0] as [number, number], maxCount: 1 };

    const now = Date.now();
    const points = filteredTrades.map(t => ({
      x: t.created_time ? new Date(t.created_time).getTime() : now,
      y: t.count,
      ticker: t.ticker,
      subtitle: t.subtitle,
      taker_side: t.taker_side,
    }));

    const times = points.map(p => p.x);
    const timeRange: [number, number] = [Math.min(...times), Math.max(...times)];
    const maxCount = Math.max(...points.map(p => p.y), 1);

    return { points, timeRange, maxCount };
  }, [filteredTrades]);

  // Compact mode: simplified view without controls
  if (compact) {
    return (
      <div className="h-full overflow-hidden">
        <TradesTable 
          trades={trades.slice(0, 50)}
          formatTime={formatTime}
          selectedMarkets={selectedMarkets}
          compact
        />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Compact Controls */}
      <div className="flex-none flex items-center justify-between px-3 py-2 border-b border-border-subtle">
        {/* Left: Stats */}
        <div className="flex items-center gap-3 text-xs">
          {stats && (
            <>
              <span className="text-text-muted">
                {stats.count} trades
              </span>
              <span className="text-text-muted">
                avg <span className="font-mono text-text-primary">{stats.mean.toFixed(0)}</span>
              </span>
            </>
          )}
        </div>

        {/* Right: Controls */}
        <div className="flex items-center gap-2">
          {/* Threshold filter */}
          <div className="flex items-center gap-1.5 text-xs">
            <Filter className="w-3 h-3 text-text-muted" />
            <input
              type="number"
              min="0"
              value={threshold}
              onChange={e => setThreshold(Math.max(0, parseInt(e.target.value) || 0))}
              placeholder="min"
              className="w-12 px-1.5 py-0.5 bg-bg-secondary border border-border-subtle rounded text-text-primary font-mono text-xs"
            />
          </div>
          
          {/* View toggle */}
          <div className="flex border border-border-subtle rounded overflow-hidden">
            <button
              onClick={() => setView('table')}
              className={clsx(
                'p-1 transition-colors',
                view === 'table' ? 'bg-accent-blue/15 text-accent-blue' : 'text-text-muted hover:text-text-primary'
              )}
              title="Table view"
            >
              <List className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setView('scatter')}
              className={clsx(
                'p-1 transition-colors',
                view === 'scatter' ? 'bg-accent-blue/15 text-accent-blue' : 'text-text-muted hover:text-text-primary'
              )}
              title="Scatter view"
            >
              <BarChart3 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {view === 'scatter' ? (
          <ScatterPlot 
            data={scatterData} 
            selectedMarkets={selectedMarkets}
          />
        ) : (
          <TradesTable 
            trades={filteredTrades}
            formatTime={formatTime}
            selectedMarkets={selectedMarkets}
          />
        )}
      </div>
    </div>
  );
}

// Scatter Plot Component
interface ScatterPlotProps {
  data: {
    points: { x: number; y: number; ticker: string; subtitle?: string; taker_side: string | null }[];
    timeRange: [number, number];
    maxCount: number;
  };
  selectedMarkets: SelectedMarket[];
}

function ScatterPlot({ data, selectedMarkets }: ScatterPlotProps) {
  const { points, timeRange, maxCount } = data;

  if (points.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-text-muted text-sm">
        No trades to display
      </div>
    );
  }

  const width = 100;
  const height = 100;
  const padding = { top: 10, right: 10, bottom: 20, left: 30 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  // Scale functions
  const xScale = (x: number) => {
    const range = timeRange[1] - timeRange[0] || 1;
    return padding.left + ((x - timeRange[0]) / range) * plotWidth;
  };

  const yScale = (y: number) => {
    return height - padding.bottom - (y / maxCount) * plotHeight;
  };

  // Y-axis ticks
  const yTicks = [0, maxCount * 0.5, maxCount].map(v => Math.round(v));

  // Time labels
  const formatAxisTime = (ts: number) => {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  };

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-full" preserveAspectRatio="xMidYMid meet">
      {/* Grid lines */}
      {yTicks.map(tick => (
        <line
          key={tick}
          x1={padding.left}
          y1={yScale(tick)}
          x2={width - padding.right}
          y2={yScale(tick)}
          stroke="rgba(42, 42, 62, 0.5)"
          strokeWidth="0.5"
        />
      ))}

      {/* Y-axis labels */}
      {yTicks.map(tick => (
        <text
          key={tick}
          x={padding.left - 3}
          y={yScale(tick)}
          textAnchor="end"
          dominantBaseline="middle"
          fill="#606070"
          fontSize="3"
        >
          {tick}
        </text>
      ))}

      {/* X-axis labels */}
      <text
        x={padding.left}
        y={height - 5}
        textAnchor="start"
        fill="#606070"
        fontSize="2.5"
      >
        {formatAxisTime(timeRange[0])}
      </text>
      <text
        x={width - padding.right}
        y={height - 5}
        textAnchor="end"
        fill="#606070"
        fontSize="2.5"
      >
        {formatAxisTime(timeRange[1])}
      </text>

      {/* Data points */}
      {points.map((point, i) => {
        const color = getMarketColor(point.ticker, selectedMarkets);
        const radius = 1.5 + Math.min(point.y / maxCount, 1) * 2;
        
        return (
          <circle
            key={i}
            cx={xScale(point.x)}
            cy={yScale(point.y)}
            r={radius}
            fill={color}
            opacity={0.8}
          >
            <title>
              {point.subtitle}: {point.y} contracts @ {formatAxisTime(point.x)}
            </title>
          </circle>
        );
      })}
    </svg>
  );
}

// Trades Table Component
interface TradesTableProps {
  trades: (Trade & { ticker: string; subtitle?: string })[];
  formatTime: (time: string | null) => string;
  selectedMarkets: SelectedMarket[];
  compact?: boolean;
}

function TradesTable({ trades, formatTime, selectedMarkets, compact = false }: TradesTableProps) {
  if (trades.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-text-muted text-sm">
        No trades to display
      </div>
    );
  }

  // Compact table for overview panels
  if (compact) {
    return (
      <div className="h-full overflow-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-bg-panel">
            <tr>
              <th className="text-left">TIME</th>
              <th className="text-center">SIDE</th>
              <th className="text-right">PRICE</th>
              <th className="text-right">QTY</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade, i) => {
              const isYes = trade.taker_side === 'yes';
              return (
                <tr 
                  key={`${trade.trade_id || i}-${trade.created_time}`}
                  className="hover:bg-bg-secondary/30"
                >
                  <td className="font-mono text-text-muted text-xs">
                    {formatTime(trade.created_time)}
                  </td>
                  <td className="text-center">
                    <span className={clsx(
                      'text-xs font-medium',
                      isYes ? 'text-accent-green' : 'text-accent-red'
                    )}>
                      {trade.taker_side?.toUpperCase() || '--'}
                    </span>
                  </td>
                  <td className={clsx(
                    'text-right font-mono text-xs',
                    isYes ? 'text-accent-green' : 'text-accent-red'
                  )}>
                    {trade.yes_price ?? trade.price ?? '--'}¢
                  </td>
                  <td className="text-right font-mono text-xs text-text-primary">
                    {trade.count}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  // Full table
  return (
    <div className="h-full overflow-auto">
      <table className="w-full">
        <thead className="sticky top-0 bg-bg-panel">
          <tr>
            <th className="text-left">#</th>
            <th className="text-left">TIME</th>
            <th className="text-left">MARKET</th>
            <th className="text-center">SIDE</th>
            <th className="text-right">YES</th>
            <th className="text-right">NO</th>
            <th className="text-right">QTY</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade, i) => {
            const color = getMarketColor(trade.ticker, selectedMarkets);
            const isYes = trade.taker_side === 'yes';
            
            return (
              <tr 
                key={`${trade.trade_id || i}-${trade.created_time}`}
                className="hover:bg-bg-secondary/30"
              >
                <td className="text-text-muted">{i + 1}</td>
                <td className="font-mono text-text-secondary">
                  {formatTime(trade.created_time)}
                </td>
                <td>
                  <span 
                    className="inline-block w-2 h-2 rounded-full mr-2"
                    style={{ backgroundColor: color }}
                  />
                  <span className="text-text-primary">{trade.subtitle || trade.ticker}</span>
                </td>
                <td className="text-center">
                  <span className={clsx(
                    'px-1.5 py-0.5 rounded text-xs font-medium',
                    isYes ? 'bg-accent-green/15 text-accent-green' : 'bg-accent-red/15 text-accent-red'
                  )}>
                    {trade.taker_side?.toUpperCase() || '--'}
                  </span>
                </td>
                <td className={clsx(
                  'text-right font-mono',
                  isYes ? 'text-accent-green' : 'text-text-secondary'
                )}>
                  {trade.yes_price ?? trade.price ?? '--'}¢
                </td>
                <td className={clsx(
                  'text-right font-mono',
                  !isYes ? 'text-accent-red' : 'text-text-secondary'
                )}>
                  {trade.no_price ?? (trade.yes_price ? 100 - trade.yes_price : '--')}¢
                </td>
                <td className="text-right font-mono font-semibold text-text-primary">
                  {trade.count}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
