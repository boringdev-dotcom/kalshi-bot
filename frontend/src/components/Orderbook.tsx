import { useMemo } from 'react';
import type { Orderbook as OrderbookType, OrderbookLevel } from '../types';

interface OrderbookProps {
  orderbook: OrderbookType | undefined;
  viewSide?: 'yes' | 'no';  // Which side to display as primary (YES = default)
}

// Normalize orderbook level - handles both array [price, qty] and object {price, quantity} formats
function normalizeLevel(level: OrderbookLevel | [number, number] | unknown): { price: number; quantity: number } | null {
  if (!level) return null;
  
  // Array format: [price, quantity]
  if (Array.isArray(level)) {
    const [price, quantity] = level;
    if (typeof price === 'number' && typeof quantity === 'number') {
      return { price, quantity };
    }
    return null;
  }
  
  // Object format: { price, quantity }
  if (typeof level === 'object' && 'price' in level && 'quantity' in level) {
    const obj = level as { price: number; quantity: number };
    if (typeof obj.price === 'number' && typeof obj.quantity === 'number') {
      return { price: obj.price, quantity: obj.quantity };
    }
  }
  
  return null;
}

export function Orderbook({ orderbook, viewSide = 'yes' }: OrderbookProps) {
  const isYesView = viewSide === 'yes';
  
  // Process orderbook data
  const { bids, asks, maxQuantity, spread, midPrice } = useMemo(() => {
    if (!orderbook) {
      return { bids: [], asks: [], maxQuantity: 1, spread: null, midPrice: null };
    }

    // Normalize and filter valid levels
    const rawYes = orderbook.yes || [];
    const yesLevels = rawYes
      .map(normalizeLevel)
      .filter((l): l is { price: number; quantity: number } => l !== null)
      .sort((a, b) => b.price - a.price)
      .slice(0, 10);
    
    const rawNo = orderbook.no || [];
    const noLevels = rawNo
      .map(normalizeLevel)
      .filter((l): l is { price: number; quantity: number } => l !== null)
      .sort((a, b) => a.price - b.price)
      .slice(0, 10);
    
    // Swap bids/asks if viewing NO side
    // When viewing YES: YES side = bids, NO side = asks
    // When viewing NO: NO side = bids, YES side = asks (prices inverted)
    const bids = isYesView ? yesLevels : noLevels;
    const asks = isYesView ? noLevels : yesLevels;

    // Find max quantity for bar scaling
    const allQuantities = [...bids, ...asks].map(l => l.quantity);
    const maxQuantity = Math.max(...allQuantities, 1);

    // Calculate spread and mid price
    const bestBid = bids[0]?.price;
    const bestAsk = asks[0]?.price ? 100 - asks[0].price : undefined;
    const spread = bestBid !== undefined && bestAsk !== undefined 
      ? bestAsk - bestBid 
      : null;
    const midPrice = bestBid !== undefined && bestAsk !== undefined
      ? (bestBid + bestAsk) / 2
      : null;

    return { bids, asks, maxQuantity, spread, midPrice };
  }, [orderbook, isYesView]);

  // Format price in cents
  const formatPrice = (price: number | undefined) => {
    if (price === undefined || price === null) return '--';
    return `${price}¢`;
  };
  
  // Format quantity with K/M suffixes
  const formatQuantity = (qty: number | undefined) => {
    if (qty === undefined || qty === null) return '--';
    if (qty >= 1000000) return `${(qty / 1000000).toFixed(1)}M`;
    if (qty >= 1000) return `${(qty / 1000).toFixed(1)}K`;
    return qty.toString();
  };

  // Calculate total value
  const formatTotal = (price: number | undefined, qty: number | undefined) => {
    if (price === undefined || qty === undefined || price === null || qty === null) return '--';
    const total = (price * qty) / 100;
    if (total >= 1000) return `$${(total / 1000).toFixed(1)}K`;
    return `$${total.toFixed(0)}`;
  };

  if (!orderbook) {
    return (
      <div className="h-full flex items-center justify-center text-text-muted text-sm">
        No orderbook data
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col text-xs">
      {/* View indicator */}
      {!isYesView && (
        <div className="px-2 py-1 bg-accent-red/10 text-accent-red text-[10px] font-medium text-center">
          Viewing NO side (inverted)
        </div>
      )}
      {/* Header with spread */}
      <div className="flex items-center justify-between px-2 py-1.5 border-b border-border-subtle">
        <div className="flex gap-4">
          <span className="text-text-muted">BID</span>
          <span className="text-accent-green font-mono">
            {bids[0]?.price ? formatPrice(bids[0].price) : '--'}
          </span>
        </div>
        <div className="flex gap-2 text-text-muted">
          <span>SPREAD</span>
          <span className="font-mono text-text-primary">
            {spread !== null ? `${spread}¢` : '--'}
          </span>
        </div>
        <div className="flex gap-4">
          <span className="text-text-muted">ASK</span>
          <span className="text-accent-red font-mono">
            {asks[0]?.price ? formatPrice(100 - asks[0].price) : '--'}
          </span>
        </div>
      </div>

      {/* Mid price */}
      {midPrice !== null && (
        <div className="flex items-center justify-center py-1 bg-bg-secondary/50">
          <span className="text-text-muted">MID:</span>
          <span className="ml-2 font-mono text-accent-blue font-semibold">
            {midPrice.toFixed(1)}¢
          </span>
        </div>
      )}

      {/* Orderbook body */}
      <div className="flex-1 flex overflow-hidden">
        {/* Bids (YES) - Left side */}
        <div className="flex-1 flex flex-col">
          <div className="flex px-2 py-1 text-text-muted border-b border-border-subtle">
            <span className="flex-1">PRICE (¢)</span>
            <span className="w-16 text-right">QTY</span>
            <span className="w-16 text-right">$TOTAL</span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {bids.map((level, i) => (
              <div
                key={`bid-${level.price}-${i}`}
                className="relative flex items-center px-2 py-0.5 hover:bg-accent-green/5"
              >
                {/* Background bar */}
                <div
                  className="absolute inset-y-0 left-0 bg-accent-green/[0.08]"
                  style={{ width: `${(level.quantity / maxQuantity) * 100}%` }}
                />
                {/* Content */}
                <span className="relative flex-1 font-mono text-accent-green">
                  {formatPrice(level.price)}
                </span>
                <span className="relative w-16 text-right font-mono text-text-primary">
                  {formatQuantity(level.quantity)}
                </span>
                <span className="relative w-16 text-right font-mono text-text-muted">
                  {formatTotal(level.price, level.quantity)}
                </span>
              </div>
            ))}
            {bids.length === 0 && (
              <div className="p-2 text-center text-text-muted">No bids</div>
            )}
          </div>
        </div>

        {/* Divider */}
        <div className="w-px bg-border-subtle" />

        {/* Asks (NO) - Right side */}
        <div className="flex-1 flex flex-col">
          <div className="flex px-2 py-1 text-text-muted border-b border-border-subtle">
            <span className="w-16">$TOTAL</span>
            <span className="w-16 text-right">QTY</span>
            <span className="flex-1 text-right">PRICE (¢)</span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {asks.map((level, i) => {
              const displayPrice = 100 - level.price; // Convert NO price to YES equivalent
              return (
                <div
                  key={`ask-${level.price}-${i}`}
                  className="relative flex items-center px-2 py-0.5 hover:bg-accent-red/5"
                >
                  {/* Background bar */}
                  <div
                    className="absolute inset-y-0 right-0 bg-accent-red/[0.08]"
                    style={{ width: `${(level.quantity / maxQuantity) * 100}%` }}
                  />
                  {/* Content */}
                  <span className="relative w-16 font-mono text-text-muted">
                    {formatTotal(displayPrice, level.quantity)}
                  </span>
                  <span className="relative w-16 text-right font-mono text-text-primary">
                    {formatQuantity(level.quantity)}
                  </span>
                  <span className="relative flex-1 text-right font-mono text-accent-red">
                    {formatPrice(displayPrice)}
                  </span>
                </div>
              );
            })}
            {asks.length === 0 && (
              <div className="p-2 text-center text-text-muted">No asks</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
