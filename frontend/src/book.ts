// Kalshi's order book, so an order form shows what a buy or sale of that size really fills at.
// One price only holds so many contracts; a bigger order works through the next prices too.
import { useEffect, useState } from 'react'
import { api } from './api'

/** Resting bids on each side, best first, as [cents, contracts]. `floor` is how low a sale goes. */
export interface Book {
  yes: [number, number][]
  no: [number, number][]
  floor: { yes: number | null; no: number | null }
}

/** 'yes' / 'no' for the book. NBA's over is YES and under is NO. */
export type BookSide = 'yes' | 'no'
export const bookSide = (side: string): BookSide => (side === 'yes' || side === 'over' ? 'yes' : 'no')

const EVERY_MS = 3000

/** The live book for one market, refreshed every few seconds while the form is open. */
export function useBook(ticker: string | null): Book | null {
  const [book, setBook] = useState<Book | null>(null)
  useEffect(() => {
    setBook(null)
    if (!ticker) return
    let alive = true
    const load = () =>
      api.book(ticker).then(
        (b) => alive && setBook(b),
        () => {
          /* no book: the form falls back to the quoted price */
        },
      )
    load()
    const timer = window.setInterval(load, EVERY_MS)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [ticker])
  return book
}

/** Offers to buy `side` from, cheapest first: someone's bid on the other side at 100 - p. */
export const asksFor = (book: Book, side: BookSide): [number, number][] =>
  (side === 'yes' ? book.no : book.yes).map(([p, n]) => [100 - p, n] as [number, number])

/** Taker fee across the prices an order touched, rounded up to a cent once, like Kalshi. */
function feeAcross(fills: [number, number][]) {
  const raw = fills.reduce((sum, [p, n]) => sum + 0.07 * n * (p / 100) * (1 - p / 100), 0)
  return Math.ceil(raw * 100 - 1e-9) / 100
}

export interface BuyPlan {
  contracts: number
  cost: number
  fees: number
  /** Average price per contract, in cents. */
  avg: number | null
  /** The highest price the order reaches. */
  worst: number | null
  /** How many prices it works through. */
  levels: number
  /** True when Kalshi has fewer contracts on offer than the money would buy. */
  short: boolean
}

/** Whole contracts `dollars` buys from these offers (fees included), never above `maxPrice`. */
export function planBuy(dollars: number, asks: [number, number][], maxPrice = 99): BuyPlan {
  const none: BuyPlan = { contracts: 0, cost: 0, fees: 0, avg: null, worst: null, levels: 0, short: false }
  if (!(dollars > 0)) return none
  const usable = asks.filter(([p]) => p <= maxPrice)
  const fit = (count: number) => {
    const fills: [number, number][] = []
    let left = count
    for (const [p, n] of usable) {
      if (left <= 0) break
      const take = Math.min(n, left)
      fills.push([p, take])
      left -= take
    }
    const spent = fills.reduce((s, [p, n]) => s + (p * n) / 100, 0)
    return { fills, got: count - Math.max(left, 0), spent }
  }
  const onOffer = Math.floor(usable.reduce((s, [, n]) => s + n, 0))
  let lo = 0
  let hi = onOffer
  while (lo < hi) {
    // the most contracts whose total cost, fees included, fits the money
    const mid = Math.ceil((lo + hi) / 2)
    const { fills, spent } = fit(mid)
    if (spent + feeAcross(fills) <= dollars + 1e-9) lo = mid
    else hi = mid - 1
  }
  if (lo === 0) return { ...none, short: onOffer === 0 }
  const { fills, spent } = fit(lo)
  const fees = feeAcross(fills)
  const worst = fills[fills.length - 1][0]
  // Short when the money would have bought more: it fits the next contract, but nobody is selling it.
  const short = lo === onOffer && spent + fees + worst / 100 <= dollars
  return { contracts: lo, cost: Math.round((spent + fees) * 100) / 100, fees, avg: (spent * 100) / lo, worst, levels: fills.length, short }
}

export interface SellPlan {
  sold: number
  /** What the sale brings in after the fee, in dollars. */
  proceeds: number
  avg: number | null
  lowest: number | null
  /** Contracts nobody is bidding for down to the floor: they would stay yours. */
  left: number
}

/** Selling `contracts` into the bids for that side, down to `floor`. */
export function planSell(contracts: number, bids: [number, number][], floor: number | null): SellPlan {
  const fills: [number, number][] = []
  let left = contracts
  for (const [p, n] of bids) {
    if (left <= 0.005 || (floor != null && p < floor)) break
    const take = Math.min(n, left)
    fills.push([p, take])
    left -= take
  }
  const sold = contracts - Math.max(left, 0)
  const gross = fills.reduce((s, [p, n]) => s + (p * n) / 100, 0)
  return {
    sold: Math.round(sold * 100) / 100,
    proceeds: Math.round((gross - feeAcross(fills)) * 100) / 100,
    avg: sold > 0 ? (gross * 100) / sold : null,
    lowest: fills.length ? fills[fills.length - 1][0] : null,
    left: left > 0.005 ? Math.round(left * 100) / 100 : 0,
  }
}

/** "223" or "78.57": Kalshi fills can be fractions of a contract. */
export const count = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0$/, ''))
