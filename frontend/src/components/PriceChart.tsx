import { useEffect, useRef, useMemo } from 'react';
import { createChart, IChartApi, ISeriesApi, LineData, Time } from 'lightweight-charts';
import type { SelectedMarket, ChartDataPoint, TickerData } from '../types';

interface PriceChartProps {
  markets: SelectedMarket[];
  priceHistory: Record<string, ChartDataPoint[]>;
  tickerData: Record<string, TickerData>;
  focusedTicker?: string | null;
}

// Color palette for different market lines
const COLORS = [
  '#00d4ff', // Blue
  '#ffab00', // Yellow/Orange
  '#00c853', // Green
  '#ff1744', // Red
  '#7b2cbf', // Purple
  '#ff6d00', // Orange
];

export function PriceChart({ markets, priceHistory, tickerData, focusedTicker }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map());

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#a0a0b0',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(42, 42, 62, 0.5)' },
        horzLines: { color: 'rgba(42, 42, 62, 0.5)' },
      },
      crosshair: {
        mode: 1,
        vertLine: {
          color: 'rgba(0, 212, 255, 0.4)',
          width: 1,
          style: 2,
        },
        horzLine: {
          color: 'rgba(0, 212, 255, 0.4)',
          width: 1,
          style: 2,
        },
      },
      rightPriceScale: {
        borderColor: '#2a2a3e',
        scaleMargins: {
          top: 0.1,
          bottom: 0.1,
        },
      },
      timeScale: {
        borderColor: '#2a2a3e',
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    });

    chartRef.current = chart;

    // Handle resize
    const resizeObserver = new ResizeObserver(entries => {
      if (entries.length > 0) {
        const { width, height } = entries[0].contentRect;
        chart.applyOptions({ width, height });
      }
    });

    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current.clear();
    };
  }, []);

  // Update series when markets change
  useEffect(() => {
    if (!chartRef.current) return;

    const chart = chartRef.current;
    const currentTickers = new Set(markets.map(m => m.ticker));
    
    // Remove series for markets that are no longer selected
    for (const [ticker, series] of seriesRef.current.entries()) {
      if (!currentTickers.has(ticker)) {
        chart.removeSeries(series);
        seriesRef.current.delete(ticker);
      }
    }

    // Add series for new markets
    markets.forEach((market, index) => {
      if (!seriesRef.current.has(market.ticker)) {
        const color = COLORS[index % COLORS.length];
        const isFocused = focusedTicker === market.ticker;
        const series = chart.addLineSeries({
          color: isFocused ? color : `${color}99`,
          lineWidth: isFocused ? 3 : 2,
          title: market.subtitle,
          priceFormat: {
            type: 'price',
            precision: 0,
            minMove: 1,
          },
        });
        seriesRef.current.set(market.ticker, series);
      }
    });
  }, [markets, focusedTicker]);

  // Update line styles when focus changes
  useEffect(() => {
    markets.forEach((market, index) => {
      const series = seriesRef.current.get(market.ticker);
      if (series) {
        const isFocused = focusedTicker === market.ticker;
        const color = COLORS[index % COLORS.length];
        series.applyOptions({
          lineWidth: isFocused ? 3 : 2,
          color: isFocused ? color : `${color}99`, // Add transparency to non-focused
        });
      }
    });
  }, [focusedTicker, markets]);

  // Update data when price history changes
  useEffect(() => {
    for (const market of markets) {
      const series = seriesRef.current.get(market.ticker);
      const history = priceHistory[market.ticker];
      
      if (series && history && history.length > 0) {
        // Convert to lightweight-charts format and sort by time
        const data: LineData[] = history
          .map(point => ({
            time: point.time as Time,
            value: point.value,
          }))
          .sort((a, b) => (a.time as number) - (b.time as number));
        
        // Remove duplicates by time
        const uniqueData: LineData[] = [];
        let lastTime: Time | null = null;
        for (const d of data) {
          if (d.time !== lastTime) {
            uniqueData.push(d);
            lastTime = d.time;
          }
        }
        
        if (uniqueData.length > 0) {
          series.setData(uniqueData);
        }
      }
    }
  }, [markets, priceHistory]);

  // Legend with current prices
  const legend = useMemo(() => {
    return markets.map((market, index) => {
      const ticker = tickerData[market.ticker];
      const lastPrice = ticker?.last_price ?? ticker?.yes_bid ?? '--';
      const color = COLORS[index % COLORS.length];
      const isFocused = focusedTicker === market.ticker;
      
      return {
        name: market.subtitle,
        ticker: market.ticker,
        color,
        price: lastPrice,
        isFocused,
      };
    });
  }, [markets, tickerData, focusedTicker]);

  return (
    <div className="relative h-full w-full">
      {/* Legend */}
      {legend.length > 0 && (
        <div className="absolute top-2 left-2 z-10 flex flex-wrap gap-3">
          {legend.map(item => (
            <div 
              key={item.ticker} 
              className={`flex items-center gap-2 px-2 py-1 rounded ${
                item.isFocused ? 'bg-bg-secondary/80' : ''
              }`}
            >
              <div 
                className={`rounded ${item.isFocused ? 'w-4 h-1' : 'w-3 h-0.5'}`}
                style={{ backgroundColor: item.color }}
              />
              <span className={`text-xs ${item.isFocused ? 'text-text-primary font-medium' : 'text-text-secondary'}`}>
                {item.name}
              </span>
              <span 
                className="text-xs font-mono font-semibold"
                style={{ color: item.color }}
              >
                {item.price}¢
              </span>
            </div>
          ))}
        </div>
      )}
      
      {/* Chart container */}
      <div ref={containerRef} className="h-full w-full" />
      
      {/* Empty state */}
      {markets.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-text-muted">
          Select markets to view price chart
        </div>
      )}
    </div>
  );
}
