import { useState, useEffect, useMemo } from 'react';
import { RefreshCw, Circle } from 'lucide-react';
import type { SelectedMarket, TickerData } from '../types';
import { clsx } from 'clsx';

interface LiveOddsPanelProps {
  selectedMarkets: SelectedMarket[];
  tickerData: Record<string, TickerData>;
  oddsApiKey: string | null;
}

interface GameOdds {
  id: string;
  homeTeam: string;
  awayTeam: string;
  commenceTime: string;
  bookmaker: string;
  // Moneyline
  homeML: number | null;
  awayML: number | null;
  // Spread
  homeSpread: number | null;
  homeSpreadOdds: number | null;
  awaySpread: number | null;
  awaySpreadOdds: number | null;
  // Totals
  totalPoints: number | null;
  overOdds: number | null;
  underOdds: number | null;
}

interface GroupedGame {
  game: GameOdds;
  markets: SelectedMarket[];
}

// Format American odds for display
function formatOdds(odds: number | null): string {
  if (odds === null) return '--';
  return odds > 0 ? `+${odds}` : `${odds}`;
}

// Format spread for display
function formatSpread(spread: number | null): string {
  if (spread === null) return '--';
  return spread > 0 ? `+${spread}` : `${spread}`;
}

export function LiveOddsPanel({ selectedMarkets, tickerData, oddsApiKey }: LiveOddsPanelProps) {
  const [odds, setOdds] = useState<GameOdds[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Fetch odds from The Odds API - NBA only, all markets
  const fetchOdds = async () => {
    if (!oddsApiKey) {
      setError('No API key configured');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `https://api.the-odds-api.com/v4/sports/basketball_nba/odds/?apiKey=${oddsApiKey}&regions=us&markets=h2h,spreads,totals&oddsFormat=american`
      );
      
      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }
      
      const data = await response.json();
      const allOdds: GameOdds[] = [];
      
      for (const game of data) {
        // Find FanDuel or fall back to first available
        let bookmaker = game.bookmakers?.find((b: any) => b.key === 'fanduel');
        if (!bookmaker && game.bookmakers?.length > 0) {
          bookmaker = game.bookmakers[0];
        }
        
        if (!bookmaker) continue;

        const h2h = bookmaker.markets?.find((m: any) => m.key === 'h2h');
        const spreads = bookmaker.markets?.find((m: any) => m.key === 'spreads');
        const totals = bookmaker.markets?.find((m: any) => m.key === 'totals');
        
        const homeH2H = h2h?.outcomes?.find((o: any) => o.name === game.home_team);
        const awayH2H = h2h?.outcomes?.find((o: any) => o.name === game.away_team);
        const homeSpread = spreads?.outcomes?.find((o: any) => o.name === game.home_team);
        const awaySpread = spreads?.outcomes?.find((o: any) => o.name === game.away_team);
        const over = totals?.outcomes?.find((o: any) => o.name === 'Over');
        const under = totals?.outcomes?.find((o: any) => o.name === 'Under');
        
        allOdds.push({
          id: game.id,
          homeTeam: game.home_team,
          awayTeam: game.away_team,
          commenceTime: game.commence_time,
          bookmaker: bookmaker.title || 'FanDuel',
          homeML: homeH2H?.price ?? null,
          awayML: awayH2H?.price ?? null,
          homeSpread: homeSpread?.point ?? null,
          homeSpreadOdds: homeSpread?.price ?? null,
          awaySpread: awaySpread?.point ?? null,
          awaySpreadOdds: awaySpread?.price ?? null,
          totalPoints: over?.point ?? null,
          overOdds: over?.price ?? null,
          underOdds: under?.price ?? null,
        });
      }

      setOdds(allOdds);
      setLastUpdated(new Date());
    } catch (e) {
      console.error('Failed to fetch odds:', e);
      setError(e instanceof Error ? e.message : 'Failed to fetch odds');
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch on mount only
  useEffect(() => {
    if (oddsApiKey && odds.length === 0) {
      fetchOdds();
    }
  }, [oddsApiKey]);

  // Group markets by game
  const groupedGames: GroupedGame[] = useMemo(() => {
    const groups: Map<string, GroupedGame> = new Map();
    
    for (const market of selectedMarkets) {
      const marketText = `${market.eventTitle} ${market.subtitle}`.toLowerCase();
      
      // Find matching game
      for (const game of odds) {
        const homeWords = game.homeTeam.toLowerCase().split(' ');
        const awayWords = game.awayTeam.toLowerCase().split(' ');
        
        const matchesHome = homeWords.some(word => word.length > 3 && marketText.includes(word));
        const matchesAway = awayWords.some(word => word.length > 3 && marketText.includes(word));
        
        if (matchesHome || matchesAway) {
          if (!groups.has(game.id)) {
            groups.set(game.id, { game, markets: [] });
          }
          groups.get(game.id)!.markets.push(market);
          break;
        }
      }
    }
    
    return Array.from(groups.values());
  }, [selectedMarkets, odds]);

  if (!oddsApiKey) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-text-muted p-8">
        <h3 className="text-lg font-medium text-text-primary mb-2">API Key Required</h3>
        <p className="text-center text-sm mb-4">
          Get a free key from{' '}
          <a href="https://the-odds-api.com/" target="_blank" rel="noopener noreferrer" className="text-accent-blue hover:underline">
            the-odds-api.com
          </a>
        </p>
        <code className="text-xs bg-bg-secondary px-2 py-1 rounded">VITE_ODDS_API_KEY=your_key</code>
      </div>
    );
  }

  if (selectedMarkets.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-text-muted">
        Star some markets to see live odds
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex-none flex items-center justify-between px-4 py-2 border-b border-border-subtle">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-text-primary">NBA Odds</span>
          {lastUpdated && (
            <span className="text-xs text-text-muted">
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
        </div>
        <button
          onClick={fetchOdds}
          disabled={isLoading}
          className="p-1.5 rounded hover:bg-bg-secondary transition-colors text-text-muted hover:text-text-primary disabled:opacity-50"
        >
          <RefreshCw className={clsx('w-4 h-4', isLoading && 'animate-spin')} />
        </button>
      </div>

      {error && (
        <div className="flex-none px-4 py-2 bg-accent-red/10 text-accent-red text-sm">
          {error}
        </div>
      )}

      {/* Column Headers - Hidden on mobile */}
      <div className="hidden md:grid flex-none grid-cols-[1fr_120px_100px_120px] gap-2 px-4 py-2 bg-bg-secondary/50 text-xs font-medium text-text-muted uppercase tracking-wide">
        <span>Game</span>
        <span className="text-center">Spread</span>
        <span className="text-center">Money</span>
        <span className="text-center">Total</span>
      </div>

      {/* Games */}
      <div className="flex-1 overflow-y-auto">
        {groupedGames.length === 0 && !isLoading && (
          <div className="p-8 text-center text-text-muted text-sm">
            No matching games found. Make sure you have NBA markets in your watchlist.
          </div>
        )}
        
        {groupedGames.map(({ game, markets }) => (
          <GameRow key={game.id} game={game} markets={markets} tickerData={tickerData} />
        ))}
      </div>

      {/* Footer */}
      <div className="flex-none px-4 py-2 border-t border-border-subtle text-xs text-text-muted">
        via {groupedGames[0]?.game.bookmaker || 'FanDuel'}
      </div>
    </div>
  );
}

// Game Row Component - FanDuel style, responsive
function GameRow({ game, markets, tickerData }: { game: GameOdds; markets: SelectedMarket[]; tickerData: Record<string, TickerData> }) {
  const gameTime = new Date(game.commenceTime);
  const now = new Date();
  const isLive = gameTime <= now;
  const isToday = gameTime.toDateString() === now.toDateString();
  
  // Find Kalshi prices for this game's markets
  const getKalshiPrice = (type: 'home' | 'away' | 'over' | 'under'): number | null => {
    for (const market of markets) {
      const subtitle = market.subtitle.toLowerCase();
      const ticker = tickerData[market.ticker];
      const price = ticker?.yes_bid ?? ticker?.last_price ?? null;
      
      if (type === 'home' && subtitle.includes(game.homeTeam.split(' ').pop()?.toLowerCase() || '')) {
        return price;
      }
      if (type === 'away' && subtitle.includes(game.awayTeam.split(' ').pop()?.toLowerCase() || '')) {
        return price;
      }
      if (type === 'over' && subtitle.toLowerCase().includes('over')) {
        return price;
      }
      if (type === 'under' && subtitle.toLowerCase().includes('under')) {
        return price;
      }
    }
    return null;
  };

  return (
    <div className="border-b border-border-subtle">
      {/* Game Header - Mobile */}
      <div className="md:hidden px-3 py-2 bg-bg-secondary/30 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {isLive && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-accent-red/20 text-accent-red text-xs font-medium rounded">
              <Circle className="w-2 h-2 fill-current" />
              LIVE
            </span>
          )}
          <span className="text-sm font-medium text-text-primary">
            {game.awayTeam.split(' ').pop()} @ {game.homeTeam.split(' ').pop()}
          </span>
        </div>
        <span className="text-xs text-text-muted">
          {isLive ? 'In Progress' : isToday ? gameTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : gameTime.toLocaleDateString()}
        </span>
      </div>

      {/* Mobile Layout - Stacked cards */}
      <div className="md:hidden px-3 py-2 grid grid-cols-3 gap-2">
        {/* Spread */}
        <div className="bg-bg-secondary/50 rounded p-2">
          <div className="text-[10px] text-text-muted uppercase mb-1">Spread</div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-text-secondary">{game.awayTeam.split(' ').pop()}</span>
              <span className="font-mono text-accent-blue">{formatSpread(game.awaySpread)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-secondary">{game.homeTeam.split(' ').pop()}</span>
              <span className="font-mono text-accent-blue">{formatSpread(game.homeSpread)}</span>
            </div>
          </div>
        </div>

        {/* Moneyline */}
        <div className="bg-bg-secondary/50 rounded p-2">
          <div className="text-[10px] text-text-muted uppercase mb-1">Money</div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-text-secondary">{game.awayTeam.split(' ').pop()}</span>
              <span className={clsx('font-mono', game.awayML && game.awayML > 0 ? 'text-accent-green' : 'text-accent-blue')}>
                {formatOdds(game.awayML)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-secondary">{game.homeTeam.split(' ').pop()}</span>
              <span className={clsx('font-mono', game.homeML && game.homeML > 0 ? 'text-accent-green' : 'text-accent-blue')}>
                {formatOdds(game.homeML)}
              </span>
            </div>
          </div>
        </div>

        {/* Total */}
        <div className="bg-bg-secondary/50 rounded p-2">
          <div className="text-[10px] text-text-muted uppercase mb-1">Total {game.totalPoints}</div>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-text-secondary">Over</span>
              <span className="font-mono text-accent-blue">{formatOdds(game.overOdds)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-secondary">Under</span>
              <span className="font-mono text-accent-blue">{formatOdds(game.underOdds)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Desktop Layout - Grid rows */}
      {/* Away Team Row */}
      <div className="hidden md:grid grid-cols-[1fr_120px_100px_120px] gap-2 px-4 py-2 hover:bg-bg-secondary/30 transition-colors">
        <div className="flex items-center gap-2">
          <span className="text-sm text-text-primary font-medium">{game.awayTeam}</span>
        </div>
        
        <OddsCell 
          line={formatSpread(game.awaySpread)} 
          odds={formatOdds(game.awaySpreadOdds)}
          kalshiPrice={null}
        />
        
        <OddsCell 
          odds={formatOdds(game.awayML)}
          kalshiPrice={getKalshiPrice('away')}
          highlight={game.awayML !== null && game.awayML > 0}
        />
        
        <OddsCell 
          line={game.totalPoints ? `O ${game.totalPoints}` : '--'} 
          odds={formatOdds(game.overOdds)}
          kalshiPrice={getKalshiPrice('over')}
        />
      </div>
      
      {/* Home Team Row */}
      <div className="hidden md:grid grid-cols-[1fr_120px_100px_120px] gap-2 px-4 py-2 hover:bg-bg-secondary/30 transition-colors">
        <div className="flex items-center gap-2">
          {isLive && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-accent-red/20 text-accent-red text-xs font-medium rounded">
              <Circle className="w-2 h-2 fill-current" />
              LIVE
            </span>
          )}
          <span className="text-sm text-text-primary font-medium">{game.homeTeam}</span>
        </div>
        
        <OddsCell 
          line={formatSpread(game.homeSpread)} 
          odds={formatOdds(game.homeSpreadOdds)}
          kalshiPrice={null}
        />
        
        <OddsCell 
          odds={formatOdds(game.homeML)}
          kalshiPrice={getKalshiPrice('home')}
          highlight={game.homeML !== null && game.homeML > 0}
        />
        
        <OddsCell 
          line={game.totalPoints ? `U ${game.totalPoints}` : '--'} 
          odds={formatOdds(game.underOdds)}
          kalshiPrice={getKalshiPrice('under')}
        />
      </div>
      
      {/* Game Time - Desktop */}
      <div className="hidden md:block px-4 py-1 text-xs text-text-muted bg-bg-secondary/20">
        {isLive ? 'In Progress' : isToday ? gameTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : gameTime.toLocaleDateString()}
        <span className="mx-2">•</span>
        {markets.length} Kalshi market{markets.length !== 1 ? 's' : ''}
      </div>

      {/* Kalshi markets count - Mobile */}
      <div className="md:hidden px-3 py-1.5 text-xs text-text-muted">
        {markets.length} Kalshi market{markets.length !== 1 ? 's' : ''} matched
      </div>
    </div>
  );
}

// Individual Odds Cell
function OddsCell({ line, odds, kalshiPrice, highlight }: { 
  line?: string; 
  odds: string; 
  kalshiPrice?: number | null;
  highlight?: boolean;
}) {
  return (
    <div className={clsx(
      'flex flex-col items-center justify-center px-2 py-1 rounded text-xs',
      highlight ? 'bg-accent-green/10' : 'bg-bg-secondary/50'
    )}>
      {line && <span className="text-text-primary font-medium">{line}</span>}
      <span className={clsx(
        'font-mono',
        highlight ? 'text-accent-green' : 'text-accent-blue'
      )}>
        {odds}
      </span>
      {kalshiPrice !== null && (
        <span className="text-text-muted text-[10px]">K: {kalshiPrice}¢</span>
      )}
    </div>
  );
}
