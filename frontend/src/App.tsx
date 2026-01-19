import { useState, useCallback, useEffect } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { fetchMarkets } from './api';
import { MarketSelector } from './components/MarketSelector';
import { PriceChart } from './components/PriceChart';
import { Orderbook } from './components/Orderbook';
import { TradesPanel } from './components/TradesPanel';
import { ConnectionStatus } from './components/ConnectionStatus';
import type { 
  LeagueData, 
  SelectedMarket, 
  Orderbook as OrderbookType, 
  Trade, 
  TickerData,
  ChartDataPoint 
} from './types';
import { Activity, TrendingUp, BookOpen, List, ChevronRight, ChevronLeft, DollarSign, Menu, X } from 'lucide-react';
import { LiveOddsPanel } from './components/LiveOddsPanel';
import { clsx } from 'clsx';

type MainTab = 'overview' | 'orderbook' | 'trades' | 'live-odds';

// Get API key from environment
const ODDS_API_KEY = import.meta.env.VITE_ODDS_API_KEY || null;

function App() {
  // Market data state
  const [leagues, setLeagues] = useState<LeagueData[]>([]);
  const [selectedMarkets, setSelectedMarkets] = useState<SelectedMarket[]>([]); // watchlist
  const [focusedMarket, setFocusedMarket] = useState<SelectedMarket | null>(null); // single focus
  const [activeTab, setActiveTab] = useState<MainTab>('overview');
  const [showSignals, setShowSignals] = useState(false); // right strip toggle
  const [showMobileMenu, setShowMobileMenu] = useState(false); // mobile sidebar
  const [orderbooks, setOrderbooks] = useState<Record<string, OrderbookType>>({});
  const [trades, setTrades] = useState<Record<string, Trade[]>>({});
  const [tickerData, setTickerData] = useState<Record<string, TickerData>>({});
  const [priceHistory, setPriceHistory] = useState<Record<string, ChartDataPoint[]>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // WebSocket handlers
  const handleOrderbook = useCallback((ticker: string, data: OrderbookType) => {
    setOrderbooks(prev => ({ ...prev, [ticker]: data }));
  }, []);

  const handleTrade = useCallback((ticker: string, data: Trade) => {
    setTrades(prev => ({
      ...prev,
      [ticker]: [data, ...(prev[ticker] || [])].slice(0, 500),
    }));
    
    // Add to price history
    if (data.yes_price || data.price) {
      const price = data.yes_price || data.price;
      const time = data.created_time 
        ? new Date(data.created_time).getTime() / 1000 
        : Date.now() / 1000;
      
      setPriceHistory(prev => ({
        ...prev,
        [ticker]: [...(prev[ticker] || []), { time, value: price! }].slice(-1000),
      }));
    }
  }, []);

  const handleTicker = useCallback((ticker: string, data: TickerData) => {
    setTickerData(prev => ({ ...prev, [ticker]: data }));
  }, []);

  const handleTradesHistory = useCallback((ticker: string, tradesData: Trade[]) => {
    setTrades(prev => ({
      ...prev,
      [ticker]: tradesData,
    }));
    
    // Build price history from trades
    const history: ChartDataPoint[] = tradesData
      .filter(t => t.yes_price || t.price)
      .map(t => ({
        time: t.created_time ? new Date(t.created_time).getTime() / 1000 : Date.now() / 1000,
        value: (t.yes_price || t.price)!,
      }))
      .reverse();
    
    setPriceHistory(prev => ({
      ...prev,
      [ticker]: history,
    }));
  }, []);

  // WebSocket connection
  const { subscribe, unsubscribe, refresh, isConnected, subscribedTickers } = useWebSocket({
    onOrderbook: handleOrderbook,
    onTrade: handleTrade,
    onTicker: handleTicker,
    onTradesHistory: handleTradesHistory,
  });

  // Load initial market data
  useEffect(() => {
    async function loadMarkets() {
      try {
        setIsLoading(true);
        const data = await fetchMarkets();
        setLeagues(data);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load markets');
      } finally {
        setIsLoading(false);
      }
    }
    loadMarkets();
  }, []);

  // Periodically refresh data for selected markets (every 10 seconds)
  useEffect(() => {
    if (!isConnected || selectedMarkets.length === 0) return;
    
    const interval = setInterval(() => {
      // Refresh up to 3 tickers at a time (rotating through all)
      const tickers = selectedMarkets.map(m => m.ticker);
      if (tickers.length > 0) {
        // Pick a random subset to refresh
        const shuffled = [...tickers].sort(() => Math.random() - 0.5);
        const toRefresh = shuffled.slice(0, 3);
        refresh(toRefresh);
      }
    }, 10000); // Every 10 seconds
    
    return () => clearInterval(interval);
  }, [isConnected, selectedMarkets, refresh]);

  // Handle market selection changes (watchlist)
  const handleMarketsChange = useCallback(async (markets: SelectedMarket[]) => {
    const oldTickers = selectedMarkets.map(m => m.ticker);
    const newTickers = markets.map(m => m.ticker);
    
    // Unsubscribe from removed tickers
    const removed = oldTickers.filter(t => !newTickers.includes(t));
    if (removed.length > 0) {
      unsubscribe(removed);
    }
    
    // Subscribe to new tickers
    // WebSocket will send initial orderbook and trades_history when subscribed
    const added = newTickers.filter(t => !oldTickers.includes(t));
    if (added.length > 0) {
      subscribe(added);
    }
    
    setSelectedMarkets(markets);
    
    // If focused market was removed, clear it or pick first
    if (focusedMarket && !newTickers.includes(focusedMarket.ticker)) {
      setFocusedMarket(markets.length > 0 ? markets[0] : null);
    }
  }, [selectedMarkets, focusedMarket, subscribe, unsubscribe]);

  // Handle focusing a single market
  const handleFocusMarket = useCallback((market: SelectedMarket) => {
    setFocusedMarket(market);
    // Also add to watchlist if not already there
    if (!selectedMarkets.some(m => m.ticker === market.ticker)) {
      handleMarketsChange([...selectedMarkets, market]);
    }
  }, [selectedMarkets, handleMarketsChange]);

  // Toggle YES/NO view side for a market
  const handleToggleViewSide = useCallback((ticker: string) => {
    setSelectedMarkets(prev => prev.map(m => 
      m.ticker === ticker 
        ? { ...m, viewSide: m.viewSide === 'yes' ? 'no' : 'yes' }
        : m
    ));
    // Also update focused market if it's the same
    if (focusedMarket?.ticker === ticker) {
      setFocusedMarket(prev => prev ? {
        ...prev,
        viewSide: prev.viewSide === 'yes' ? 'no' : 'yes'
      } : null);
    }
  }, [focusedMarket]);

  // Get combined trades for all selected markets
  const allTrades = selectedMarkets.flatMap(m => 
    (trades[m.ticker] || []).map(t => ({ ...t, ticker: m.ticker, subtitle: m.subtitle }))
  ).sort((a, b) => {
    const timeA = a.created_time ? new Date(a.created_time).getTime() : 0;
    const timeB = b.created_time ? new Date(b.created_time).getTime() : 0;
    return timeB - timeA;
  }).slice(0, 100);

  // Focused market data
  const focusedTicker = focusedMarket?.ticker;
  const focusedTrades = focusedTicker 
    ? (trades[focusedTicker] || []).map(t => ({ ...t, ticker: focusedTicker, subtitle: focusedMarket?.subtitle }))
    : [];
  const focusedTickerData = focusedTicker ? tickerData[focusedTicker] : null;

  return (
    <div className="h-screen bg-bg-primary flex flex-col overflow-hidden">
      {/* Top Bar */}
      <header className="flex-none px-3 md:px-4 py-2 md:py-3 border-b border-border-subtle flex items-center justify-between">
        <div className="flex items-center gap-2 md:gap-3">
          {/* Mobile menu button */}
          <button
            onClick={() => setShowMobileMenu(!showMobileMenu)}
            className="md:hidden p-1.5 -ml-1 rounded hover:bg-bg-secondary transition-colors"
          >
            {showMobileMenu ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
          <Activity className="w-5 h-5 md:w-6 md:h-6 text-accent-blue" />
          <h1 className="text-base md:text-lg font-semibold text-text-primary">Kalshi</h1>
        </div>
        <ConnectionStatus isConnected={isConnected} tickerCount={subscribedTickers.size} />
      </header>

      {error && (
        <div className="flex-none mx-4 mt-3 p-3 bg-accent-red/10 border border-accent-red/30 rounded-lg text-accent-red text-sm">
          {error}
        </div>
      )}

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Mobile Overlay */}
        {showMobileMenu && (
          <div 
            className="md:hidden absolute inset-0 bg-black/50 z-20"
            onClick={() => setShowMobileMenu(false)}
          />
        )}

        {/* Left: Market List - Slide in on mobile */}
        <div className={clsx(
          'flex-none border-r border-border-subtle flex flex-col bg-bg-primary z-30',
          'w-72 md:w-80',
          // Mobile: absolute positioned, slides in
          'absolute md:relative inset-y-0 left-0',
          'transform transition-transform duration-200 ease-out',
          showMobileMenu ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        )}>
          <MarketSelector
            leagues={leagues}
            selectedMarkets={selectedMarkets}
            focusedMarket={focusedMarket}
            tickerData={tickerData}
            onMarketsChange={handleMarketsChange}
            onFocusMarket={(market) => {
              handleFocusMarket(market);
              setShowMobileMenu(false); // Close menu on mobile after selection
            }}
            onToggleViewSide={handleToggleViewSide}
            isLoading={isLoading}
          />
        </div>

        {/* Center: Main Focus Panel */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Tabs */}
          <div className="flex-none px-2 md:px-4 py-2 border-b border-border-subtle flex items-center gap-0.5 md:gap-1 overflow-x-auto">
            <TabButton 
              active={activeTab === 'overview'} 
              onClick={() => setActiveTab('overview')}
              icon={<TrendingUp className="w-4 h-4" />}
            >
              <span className="hidden sm:inline">Overview</span>
            </TabButton>
            <TabButton 
              active={activeTab === 'orderbook'} 
              onClick={() => setActiveTab('orderbook')}
              icon={<BookOpen className="w-4 h-4" />}
            >
              <span className="hidden sm:inline">Orderbook</span>
            </TabButton>
            <TabButton 
              active={activeTab === 'trades'} 
              onClick={() => setActiveTab('trades')}
              icon={<List className="w-4 h-4" />}
            >
              <span className="hidden sm:inline">Trades</span>
            </TabButton>
            <TabButton 
              active={activeTab === 'live-odds'} 
              onClick={() => setActiveTab('live-odds')}
              icon={<DollarSign className="w-4 h-4" />}
            >
              <span className="hidden sm:inline">Live Odds</span>
            </TabButton>
            
            {/* Focused market info - hidden on mobile */}
            {focusedMarket && (
              <div className="ml-auto hidden lg:flex items-center gap-3 text-sm">
                <span className="text-text-secondary truncate max-w-[150px]">{focusedMarket.eventTitle}</span>
                <span className="text-text-primary font-medium">{focusedMarket.subtitle}</span>
                {focusedTickerData && (
                  <div className="flex items-center gap-2 font-mono text-xs">
                    <span className="text-accent-green">{focusedTickerData.yes_bid ?? '--'}¢</span>
                    <span className="text-text-muted">/</span>
                    <span className="text-accent-red">{focusedTickerData.yes_ask ?? '--'}¢</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-hidden p-2 md:p-4">
            {selectedMarkets.length === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted">
                Star markets from the list to add them to your watchlist
              </div>
            ) : activeTab === 'overview' ? (
              <div className="h-full flex flex-col gap-4">
                {/* Chart - shows ALL watched markets */}
                <div className="flex-1 glass-panel p-3 min-h-0">
                  <PriceChart
                    markets={selectedMarkets}
                    priceHistory={priceHistory}
                    tickerData={tickerData}
                    focusedTicker={focusedTicker}
                  />
                </div>
                {/* Recent Trades (compact) - shows focused market trades or all if none focused */}
                <div className="flex-none h-48 glass-panel overflow-hidden">
                  <div className="panel-header">
                    <span className="text-xs font-medium text-text-secondary">
                      {focusedMarket ? `${focusedMarket.subtitle} Trades` : 'All Watchlist Trades'}
                    </span>
                  </div>
                  <TradesPanel 
                    trades={focusedMarket ? focusedTrades.slice(0, 10) : allTrades.slice(0, 10)} 
                    selectedMarkets={selectedMarkets}
                    compact
                  />
                </div>
              </div>
            ) : activeTab === 'orderbook' ? (
              <div className="h-full glass-panel overflow-hidden">
                {focusedMarket ? (
                  <Orderbook 
                    orderbook={orderbooks[focusedTicker!]} 
                    viewSide={focusedMarket.viewSide || 'yes'}
                  />
                ) : (
                  <div className="h-full flex items-center justify-center text-text-muted">
                    Click a market to view its orderbook
                  </div>
                )}
              </div>
            ) : activeTab === 'trades' ? (
              <div className="h-full glass-panel overflow-hidden">
                <TradesPanel 
                  trades={focusedMarket ? focusedTrades : allTrades} 
                  selectedMarkets={selectedMarkets}
                />
              </div>
            ) : (
              <div className="h-full glass-panel overflow-hidden">
                <LiveOddsPanel 
                  selectedMarkets={selectedMarkets}
                  tickerData={tickerData}
                  oddsApiKey={ODDS_API_KEY}
                />
              </div>
            )}
          </div>
        </div>

        {/* Right: Signals Strip (collapsible) - Hidden on mobile */}
        <div className={clsx(
          'hidden md:flex flex-none border-l border-border-subtle flex-col transition-all duration-200',
          showSignals ? 'w-72' : 'w-10'
        )}>
          <button
            onClick={() => setShowSignals(!showSignals)}
            className="flex-none p-2 border-b border-border-subtle text-text-muted hover:text-text-primary transition-colors"
          >
            {showSignals ? <ChevronRight className="w-5 h-5" /> : <ChevronLeft className="w-5 h-5" />}
          </button>
          {showSignals && (
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="px-3 py-2 border-b border-border-subtle">
                <span className="text-xs font-medium text-text-secondary">All Watchlist Trades</span>
              </div>
              <div className="flex-1 overflow-hidden">
                <TradesPanel 
                  trades={allTrades} 
                  selectedMarkets={selectedMarkets}
                  compact
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Tab Button Component
function TabButton({ 
  active, 
  onClick, 
  icon, 
  children 
}: { 
  active: boolean; 
  onClick: () => void; 
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
        active 
          ? 'bg-accent-blue/15 text-accent-blue' 
          : 'text-text-secondary hover:text-text-primary hover:bg-bg-secondary'
      )}
    >
      {icon}
      {children}
    </button>
  );
}

export default App;
