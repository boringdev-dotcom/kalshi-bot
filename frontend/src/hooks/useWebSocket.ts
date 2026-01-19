import { useEffect, useRef, useCallback, useState } from 'react';
import type { WSMessage, Orderbook, Trade, TickerData } from '../types';

interface UseWebSocketOptions {
  onOrderbook?: (ticker: string, data: Orderbook) => void;
  onTrade?: (ticker: string, data: Trade) => void;
  onTicker?: (ticker: string, data: TickerData) => void;
  onTradesHistory?: (ticker: string, trades: Trade[]) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
}

interface UseWebSocketReturn {
  subscribe: (tickers: string[]) => void;
  unsubscribe: (tickers: string[]) => void;
  refresh: (tickers: string[]) => void;
  isConnected: boolean;
  subscribedTickers: Set<string>;
}

// Normalize orderbook data to handle both array and object formats
function normalizeOrderbook(data: unknown): Orderbook {
  const raw = data as { yes?: unknown[]; no?: unknown[]; ticker?: string };
  
  const normalizeLevel = (level: unknown): { price: number; quantity: number } | null => {
    if (Array.isArray(level) && level.length >= 2) {
      return { price: level[0], quantity: level[1] };
    }
    if (level && typeof level === 'object' && 'price' in level && 'quantity' in level) {
      const obj = level as { price: number; quantity: number };
      return { price: obj.price, quantity: obj.quantity };
    }
    return null;
  };
  
  return {
    ticker: raw.ticker || '',
    yes: (raw.yes || []).map(normalizeLevel).filter((l): l is { price: number; quantity: number } => l !== null),
    no: (raw.no || []).map(normalizeLevel).filter((l): l is { price: number; quantity: number } => l !== null),
  };
}

export function useWebSocket(options: UseWebSocketOptions): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [subscribedTickers, setSubscribedTickers] = useState<Set<string>>(new Set());
  const reconnectTimeoutRef = useRef<number | null>(null);
  const heartbeatIntervalRef = useRef<number | null>(null);
  const optionsRef = useRef(options);
  const reconnectAttempts = useRef(0);
  const pendingSubscriptions = useRef<Set<string>>(new Set());
  
  // Keep options ref updated
  optionsRef.current = options;

  const clearTimers = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = null;
    }
  }, []);

  const startHeartbeat = useCallback((ws: WebSocket) => {
    // Clear any existing heartbeat
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current);
    }
    
    // Send ping every 30 seconds to keep connection alive
    heartbeatIntervalRef.current = window.setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'ping' }));
      }
    }, 30000);
  }, []);

  const connect = useCallback(() => {
    // Don't connect if already connected or connecting
    if (wsRef.current?.readyState === WebSocket.OPEN || 
        wsRef.current?.readyState === WebSocket.CONNECTING) {
      return;
    }

    // Build WebSocket URL from API URL or use current host
    let wsUrl: string;
    const apiUrl = import.meta.env.VITE_API_URL;
    
    if (apiUrl && apiUrl.startsWith('http')) {
      // Convert HTTP URL to WebSocket URL
      const url = new URL(apiUrl);
      const wsProtocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      wsUrl = `${wsProtocol}//${url.host}/ws/market-data`;
    } else {
      // Use current host (same-origin)
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host;
      wsUrl = `${protocol}//${host}/ws/market-data`;
    }

    console.log('Connecting to WebSocket:', wsUrl);
    
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connected');
        setIsConnected(true);
        reconnectAttempts.current = 0;
        optionsRef.current.onConnect?.();
        
        // Start heartbeat
        startHeartbeat(ws);
        
        // Re-subscribe to previously subscribed tickers
        const tickersToSubscribe = new Set([
          ...subscribedTickers,
          ...pendingSubscriptions.current
        ]);
        
        if (tickersToSubscribe.size > 0) {
          ws.send(JSON.stringify({
            action: 'subscribe',
            tickers: Array.from(tickersToSubscribe),
          }));
        }
        
        pendingSubscriptions.current.clear();
      };

      ws.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason);
        setIsConnected(false);
        clearTimers();
        optionsRef.current.onDisconnect?.();
        
        // Exponential backoff for reconnection (max 30 seconds)
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
        reconnectAttempts.current++;
        
        console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts.current})`);
        reconnectTimeoutRef.current = window.setTimeout(() => {
          connect();
        }, delay);
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        optionsRef.current.onError?.(error);
      };

      ws.onmessage = (event) => {
        try {
          const message: WSMessage = JSON.parse(event.data);
          
          switch (message.type) {
            case 'orderbook':
              if (message.ticker && message.data) {
                const orderbook = normalizeOrderbook(message.data);
                orderbook.ticker = message.ticker;
                optionsRef.current.onOrderbook?.(message.ticker, orderbook);
              }
              break;
              
            case 'trade':
              if (message.ticker && message.data) {
                optionsRef.current.onTrade?.(message.ticker, message.data as Trade);
              }
              break;
              
            case 'ticker':
              if (message.ticker && message.data) {
                optionsRef.current.onTicker?.(message.ticker, message.data as TickerData);
              }
              break;
              
            case 'trades_history':
            case 'trades':  // Also handle 'trades' from refresh
              if (message.ticker && message.data) {
                optionsRef.current.onTradesHistory?.(message.ticker, message.data as Trade[]);
              }
              break;
              
            case 'subscribed':
              console.log('Subscribed to:', message.tickers);
              if (message.tickers) {
                setSubscribedTickers(prev => {
                  const next = new Set(prev);
                  message.tickers!.forEach(t => next.add(t));
                  return next;
                });
              }
              break;
              
            case 'unsubscribed':
              console.log('Unsubscribed from:', message.tickers);
              if (message.tickers) {
                setSubscribedTickers(prev => {
                  const next = new Set(prev);
                  message.tickers!.forEach(t => next.delete(t));
                  return next;
                });
              }
              break;
              
            case 'pong':
              // Heartbeat response received - connection is alive
              break;
              
            case 'ping':
              // Server ping - respond with pong
              if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: 'ping' }));
              }
              break;
              
            case 'error':
              console.error('WebSocket error message:', message.message);
              break;
              
            default:
              // Ignore unknown message types silently
              break;
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };
    } catch (e) {
      console.error('Failed to create WebSocket:', e);
      // Retry connection
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
      reconnectAttempts.current++;
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect();
      }, delay);
    }
  }, [subscribedTickers, clearTimers, startHeartbeat]);

  // Connect on mount
  useEffect(() => {
    connect();
    
    return () => {
      clearTimers();
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounting');
        wsRef.current = null;
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const subscribe = useCallback((tickers: string[]) => {
    if (!tickers.length) return;
    
    // Update local state immediately
    setSubscribedTickers(prev => {
      const next = new Set(prev);
      tickers.forEach(t => next.add(t));
      return next;
    });
    
    // Send to server if connected, otherwise queue for when connected
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        action: 'subscribe',
        tickers,
      }));
    } else {
      // Queue subscriptions for when we connect
      tickers.forEach(t => pendingSubscriptions.current.add(t));
    }
  }, []);

  const unsubscribe = useCallback((tickers: string[]) => {
    if (!tickers.length) return;
    
    // Update local state immediately
    setSubscribedTickers(prev => {
      const next = new Set(prev);
      tickers.forEach(t => next.delete(t));
      return next;
    });
    
    // Remove from pending if not yet sent
    tickers.forEach(t => pendingSubscriptions.current.delete(t));
    
    // Send to server if connected
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        action: 'unsubscribe',
        tickers,
      }));
    }
  }, []);

  const refresh = useCallback((tickers: string[]) => {
    if (!tickers.length) return;
    
    // Request fresh data for tickers
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        action: 'refresh',
        tickers,
      }));
    }
  }, []);

  return {
    subscribe,
    unsubscribe,
    refresh,
    isConnected,
    subscribedTickers,
  };
}
