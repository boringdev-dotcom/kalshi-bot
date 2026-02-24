import { useEffect, useRef, useMemo, useState, useCallback } from 'react';
import { createChart, IChartApi, ISeriesApi, LineData, Time } from 'lightweight-charts';
import type { SelectedMarket, ChartDataPoint, TickerData } from '../types';
import { fetchNBAOdds } from '../api';
import type { OddsApiGame } from '../api';

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

interface MarketOddsSnapshot {
  homeML: number | null;
  awayML: number | null;
  overOdds: number | null;
  underOdds: number | null;
}

function americanOddsToProbability(odds: number | null): number | null {
  if (odds === null || odds === 0) return null;
  if (odds > 0) {
    return (100 / (odds + 100)) * 100;
  }
  return (Math.abs(odds) / (Math.abs(odds) + 100)) * 100;
}

function formatProbability(probability: number | null | undefined): string {
  if (probability === null || probability === undefined || Number.isNaN(probability)) return '--';
  return `${probability.toFixed(1)}%`;
}

function tokenizeWords(value: string): string[] {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter(word => word.length > 2);
}

function countWordMatches(targetText: string, words: string[]): number {
  let score = 0;
  for (const word of words) {
    if (word.length > 3 && targetText.includes(word)) {
      score += 1;
    }
  }
  return score;
}

function extractGameOdds(game: OddsApiGame): MarketOddsSnapshot | null {
  const bookmaker = game.bookmakers?.find(b => b.key === 'fanduel') || game.bookmakers?.[0];
  if (!bookmaker) return null;

  const h2h = bookmaker.markets?.find(m => m.key === 'h2h');
  const totals = bookmaker.markets?.find(m => m.key === 'totals');

  const homeH2H = h2h?.outcomes?.find(o => o.name === game.home_team);
  const awayH2H = h2h?.outcomes?.find(o => o.name === game.away_team);
  const over = totals?.outcomes?.find(o => o.name === 'Over');
  const under = totals?.outcomes?.find(o => o.name === 'Under');

  return {
    homeML: homeH2H?.price ?? null,
    awayML: awayH2H?.price ?? null,
    overOdds: over?.price ?? null,
    underOdds: under?.price ?? null,
  };
}

function getExternalMarketProbability(market: SelectedMarket, games: OddsApiGame[]): number | null {
  const subtitle = market.subtitle.toLowerCase();
  const marketText = `${market.eventTitle} ${market.subtitle}`.toLowerCase();
  const subtitleWords = tokenizeWords(subtitle);

  for (const game of games) {
    const homeWords = tokenizeWords(game.home_team);
    const awayWords = tokenizeWords(game.away_team);
    const homeMatchScore = countWordMatches(marketText, homeWords);
    const awayMatchScore = countWordMatches(marketText, awayWords);
    const matchesHome = homeMatchScore > 0;
    const matchesAway = awayMatchScore > 0;

    if (!matchesHome && !matchesAway) continue;

    const oddsSnapshot = extractGameOdds(game);
    if (!oddsSnapshot) continue;

    if (subtitle.includes('over')) return americanOddsToProbability(oddsSnapshot.overOdds);
    if (subtitle.includes('under')) return americanOddsToProbability(oddsSnapshot.underOdds);

    const subtitleHomeScore = countWordMatches(subtitle, homeWords);
    const subtitleAwayScore = countWordMatches(subtitle, awayWords);

    if (subtitleHomeScore > subtitleAwayScore) return americanOddsToProbability(oddsSnapshot.homeML);
    if (subtitleAwayScore > subtitleHomeScore) return americanOddsToProbability(oddsSnapshot.awayML);

    const subtitleHasHomeCity = homeWords.some(word => word.length > 3 && subtitleWords.includes(word));
    const subtitleHasAwayCity = awayWords.some(word => word.length > 3 && subtitleWords.includes(word));

    if (subtitleHasHomeCity && !subtitleHasAwayCity) return americanOddsToProbability(oddsSnapshot.homeML);
    if (subtitleHasAwayCity && !subtitleHasHomeCity) return americanOddsToProbability(oddsSnapshot.awayML);

    if (homeMatchScore > awayMatchScore) return americanOddsToProbability(oddsSnapshot.homeML);
    if (awayMatchScore > homeMatchScore) return americanOddsToProbability(oddsSnapshot.awayML);

    if (matchesHome && !matchesAway) return americanOddsToProbability(oddsSnapshot.homeML);
    if (matchesAway && !matchesHome) return americanOddsToProbability(oddsSnapshot.awayML);
  }

  return null;
}

export function PriceChart({ markets, priceHistory, tickerData, focusedTicker }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map());
  const [marketProbabilities, setMarketProbabilities] = useState<Record<string, number | null>>({});

  const refreshMarketProbabilities = useCallback(async () => {
    if (markets.length === 0) {
      setMarketProbabilities({});
      return;
    }

    try {
      const games = await fetchNBAOdds();
      const next: Record<string, number | null> = {};

      for (const market of markets) {
        const yesSideProbability = getExternalMarketProbability(market, games);
        next[market.ticker] = market.viewSide === 'no' && yesSideProbability !== null
          ? 100 - yesSideProbability
          : yesSideProbability;
      }

      setMarketProbabilities(next);
    } catch {
      // Odds feed is optional; keep chart functional even when unavailable.
      const fallback: Record<string, number | null> = {};
      for (const market of markets) {
        fallback[market.ticker] = null;
      }
      setMarketProbabilities(fallback);
    }
  }, [markets]);

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

  // Update data when price history or viewSide changes
  useEffect(() => {
    for (const market of markets) {
      const series = seriesRef.current.get(market.ticker);
      const history = priceHistory[market.ticker];
      const isNoView = market.viewSide === 'no';
      
      if (series && history && history.length > 0) {
        // Convert to lightweight-charts format and sort by time
        // Invert prices if viewing NO side (NO price = 100 - YES price)
        const data: LineData[] = history
          .map(point => ({
            time: point.time as Time,
            value: isNoView ? 100 - point.value : point.value,
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

  // Pull external market odds so chart legend can compare Kalshi vs market probability
  useEffect(() => {
    void refreshMarketProbabilities();
    const interval = setInterval(() => {
      void refreshMarketProbabilities();
    }, 30000);

    return () => clearInterval(interval);
  }, [refreshMarketProbabilities]);

  // Legend with current prices
  const legend = useMemo(() => {
    return markets.map((market, index) => {
      const ticker = tickerData[market.ticker];
      const isNoView = market.viewSide === 'no';
      
      // Get price based on view side
      let lastPrice: number | string = '--';
      if (ticker) {
        const yesPrice = ticker.last_price ?? ticker.yes_bid;
        if (yesPrice !== null && yesPrice !== undefined) {
          lastPrice = isNoView ? 100 - yesPrice : yesPrice;
        }
      }
      const kalshiProbability = typeof lastPrice === 'number' ? lastPrice : null;
      const marketProbability = marketProbabilities[market.ticker] ?? null;
      
      const color = COLORS[index % COLORS.length];
      const isFocused = focusedTicker === market.ticker;
      
      return {
        name: market.subtitle,
        ticker: market.ticker,
        color,
        price: lastPrice,
        kalshiProbability,
        marketProbability,
        isFocused,
        viewSide: market.viewSide || 'yes',
      };
    });
  }, [markets, tickerData, focusedTicker, marketProbabilities]);

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
              {item.viewSide === 'no' && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-accent-red/20 text-accent-red font-medium">
                  NO
                </span>
              )}
              <span 
                className="text-xs font-mono font-semibold"
                style={{ color: item.color }}
              >
                {typeof item.price === 'number' ? `${item.price}¢` : '--'}
              </span>
              <span className="text-[10px] text-text-muted font-mono">
                Kalshi: {formatProbability(item.kalshiProbability)} | Market: {formatProbability(item.marketProbability)}
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
