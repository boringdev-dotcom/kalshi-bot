import { useState, useMemo } from 'react';
import { ChevronDown, RefreshCw, Search, Star } from 'lucide-react';
import type { LeagueData, SelectedMarket, Event, TickerData } from '../types';
import { clsx } from 'clsx';

interface MarketSelectorProps {
  leagues: LeagueData[];
  selectedMarkets: SelectedMarket[];
  focusedMarket: SelectedMarket | null;
  tickerData: Record<string, TickerData>;
  onMarketsChange: (markets: SelectedMarket[]) => void;
  onFocusMarket: (market: SelectedMarket) => void;
  isLoading: boolean;
}

export function MarketSelector({
  leagues,
  selectedMarkets,
  focusedMarket,
  tickerData,
  onMarketsChange,
  onFocusMarket,
  isLoading,
}: MarketSelectorProps) {
  const [selectedLeague, setSelectedLeague] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<Event | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Get events for selected league
  const events = useMemo(() => {
    if (!selectedLeague) return [];
    const league = leagues.find(l => l.league_id === selectedLeague);
    return league?.events || [];
  }, [leagues, selectedLeague]);

  // Filter events by search query
  const filteredEvents = useMemo(() => {
    if (!searchQuery.trim()) return events;
    const query = searchQuery.toLowerCase();
    return events.filter(e => 
      e.title.toLowerCase().includes(query) ||
      e.markets.some(m => m.subtitle.toLowerCase().includes(query))
    );
  }, [events, searchQuery]);

  // Check if a market is in watchlist
  const isMarketWatched = (ticker: string) => 
    selectedMarkets.some(m => m.ticker === ticker);

  // Check if a market is focused
  const isMarketFocused = (ticker: string) => 
    focusedMarket?.ticker === ticker;

  // Toggle market in watchlist
  const toggleWatchlist = (market: { ticker: string; subtitle: string }, event: Event, e: React.MouseEvent) => {
    e.stopPropagation();
    const isWatched = isMarketWatched(market.ticker);
    
    if (isWatched) {
      onMarketsChange(selectedMarkets.filter(m => m.ticker !== market.ticker));
    } else {
      onMarketsChange([
        ...selectedMarkets,
        {
          ticker: market.ticker,
          subtitle: market.subtitle,
          eventTitle: event.title,
          league: event.league,
        },
      ]);
    }
  };

  // Focus on a market (and add to watchlist)
  const handleFocusMarket = (market: { ticker: string; subtitle: string }, event: Event) => {
    onFocusMarket({
      ticker: market.ticker,
      subtitle: market.subtitle,
      eventTitle: event.title,
      league: event.league,
    });
  };

  // Clear watchlist
  const clearWatchlist = () => {
    onMarketsChange([]);
  };

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center text-text-muted">
        <RefreshCw className="w-4 h-4 animate-spin mr-2" />
        Loading...
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Search + Filters */}
      <div className="flex-none p-3 space-y-2 border-b border-border-subtle">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted" />
          <input
            type="text"
            placeholder="Search markets..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1.5 bg-bg-secondary border border-border-subtle rounded-md text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue/50"
          />
        </div>
        
        {/* League Filter */}
        <div className="relative">
          <select
            value={selectedLeague || ''}
            onChange={e => {
              setSelectedLeague(e.target.value || null);
              setSelectedEvent(null);
            }}
            className="w-full appearance-none bg-bg-secondary border border-border-subtle rounded-md px-3 py-1.5 pr-8 text-sm text-text-primary focus:outline-none focus:border-accent-blue/50 cursor-pointer"
          >
            <option value="">All Leagues</option>
            {leagues.map(league => (
              <option key={league.league_id} value={league.league_id}>
                {league.display_name}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-muted pointer-events-none" />
        </div>
      </div>

      {/* Watchlist Section */}
      {selectedMarkets.length > 0 && (
        <div className="flex-none border-b border-border-subtle">
          <div className="px-3 py-2 flex items-center justify-between">
            <span className="text-xs font-medium text-text-secondary uppercase tracking-wide">
              Watchlist ({selectedMarkets.length})
            </span>
            <button
              onClick={clearWatchlist}
              className="text-xs text-text-muted hover:text-accent-red transition-colors"
            >
              Clear
            </button>
          </div>
          <div className="max-h-32 overflow-y-auto">
            {selectedMarkets.map(market => (
              <MarketRow
                key={market.ticker}
                market={market}
                tickerData={tickerData[market.ticker]}
                isFocused={isMarketFocused(market.ticker)}
                isWatched={true}
                onFocus={() => onFocusMarket(market)}
                onToggleWatch={(e) => {
                  e.stopPropagation();
                  onMarketsChange(selectedMarkets.filter(m => m.ticker !== market.ticker));
                }}
              />
            ))}
          </div>
        </div>
      )}

      {/* Market List */}
      <div className="flex-1 overflow-y-auto">
        {!selectedLeague ? (
          <div className="p-4 text-center text-text-muted text-sm">
            Select a league to browse markets
          </div>
        ) : filteredEvents.length === 0 ? (
          <div className="p-4 text-center text-text-muted text-sm">
            No events found
          </div>
        ) : (
          filteredEvents.map(event => (
            <div key={event.event_id} className="border-b border-border-subtle last:border-b-0">
              {/* Event Header */}
              <button
                onClick={() => setSelectedEvent(selectedEvent?.event_id === event.event_id ? null : event)}
                className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-bg-secondary/50 transition-colors"
              >
                <span className="text-xs text-text-secondary truncate pr-2">{event.title}</span>
                <ChevronDown className={clsx(
                  'w-4 h-4 text-text-muted flex-none transition-transform',
                  selectedEvent?.event_id === event.event_id && 'rotate-180'
                )} />
              </button>
              
              {/* Event Markets */}
              {selectedEvent?.event_id === event.event_id && (
                <div className="bg-bg-secondary/30">
                  {event.markets.map(market => (
                    <MarketRow
                      key={market.ticker}
                      market={{
                        ticker: market.ticker,
                        subtitle: market.subtitle,
                        eventTitle: event.title,
                        league: event.league,
                      }}
                      tickerData={tickerData[market.ticker] || {
                        ticker: market.ticker,
                        yes_bid: market.yes_bid,
                        yes_ask: market.yes_ask,
                        no_bid: market.no_bid,
                        no_ask: market.no_ask,
                        last_price: market.last_price,
                        volume: market.volume,
                      }}
                      isFocused={isMarketFocused(market.ticker)}
                      isWatched={isMarketWatched(market.ticker)}
                      onFocus={() => handleFocusMarket(market, event)}
                      onToggleWatch={(e) => toggleWatchlist(market, event, e)}
                    />
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// Compact Market Row Component
interface MarketRowProps {
  market: SelectedMarket;
  tickerData: TickerData | undefined;
  isFocused: boolean;
  isWatched: boolean;
  onFocus: () => void;
  onToggleWatch: (e: React.MouseEvent) => void;
}

function MarketRow({ market, tickerData, isFocused, isWatched, onFocus, onToggleWatch }: MarketRowProps) {
  return (
    <button
      onClick={onFocus}
      className={clsx(
        'w-full px-3 py-2 flex items-center gap-2 text-left transition-colors',
        isFocused 
          ? 'bg-accent-blue/10 border-l-2 border-accent-blue' 
          : 'hover:bg-bg-secondary/50 border-l-2 border-transparent'
      )}
    >
      {/* Watch toggle */}
      <button
        onClick={onToggleWatch}
        className={clsx(
          'flex-none p-0.5 rounded transition-colors',
          isWatched ? 'text-yellow-500' : 'text-text-muted hover:text-yellow-500'
        )}
      >
        <Star className={clsx('w-3.5 h-3.5', isWatched && 'fill-current')} />
      </button>
      
      {/* Market info */}
      <div className="flex-1 min-w-0">
        <div className="text-sm text-text-primary truncate">{market.subtitle}</div>
      </div>
      
      {/* Price chips */}
      <div className="flex-none flex items-center gap-1.5 font-mono text-xs">
        <span className="text-accent-green">{tickerData?.yes_bid ?? '--'}</span>
        <span className="text-text-muted">/</span>
        <span className="text-accent-red">{tickerData?.yes_ask ?? '--'}</span>
      </div>
    </button>
  );
}
