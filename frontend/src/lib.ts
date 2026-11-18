// Small pure helpers shared by the Markets and Game screens.
import { useEffect, useState } from 'react'
import { api } from './api'
import type { Game, GameDetail, LadderRung, Segment, Side } from './types'

/** What the user has tapped: one side of one market. */
export interface Pick {
  ticker: string
  side: Side
}

/** Kalshi's taker fee in dollars: 7% of contracts x P x (1 - P), rounded up to a cent. Mirrors the backend. */
export function fee(contracts: number, priceCents: number) {
  const p = priceCents / 100
  return Math.ceil(0.07 * contracts * p * (1 - p) * 100 - 1e-9) / 100
}

/** How many contracts `dollars` buys at `priceCents`, fees included. */
export function sizeOrder(dollars: number, priceCents: number) {
  if (!(dollars > 0) || !(priceCents > 0)) return { contracts: 0, cost: 0, fees: 0 }
  let contracts = Math.floor(dollars / (priceCents / 100))
  while (contracts > 0) {
    const fees = fee(contracts, priceCents)
    const cost = (contracts * priceCents) / 100 + fees
    if (cost <= dollars + 1e-9) return { contracts, cost: Math.round(cost * 100) / 100, fees }
    contracts -= 1
  }
  return { contracts: 0, cost: 0, fees: 0 }
}

export const askOf = (r: LadderRung, side: Side) => (side === 'under' ? r.no_ask : r.yes_ask)
export const bidOf = (r: LadderRung, side: Side) => (side === 'under' ? r.no_bid : r.yes_bid)
export const modelChance = (r: LadderRung, side: Side) => (side === 'under' ? r.p_under : 1 - r.p_under)

/** The market's own 50/50 point for a list of total rungs: where "over" costs 50 cents. */
export function impliedLine(rungs: LadderRung[]): number | null {
  const pts = rungs
    .filter((r) => r.yes_bid != null && r.yes_ask != null)
    .map((r) => ({ strike: r.strike, mid: ((r.yes_bid as number) + (r.yes_ask as number)) / 2 }))
    .sort((a, b) => a.strike - b.strike)
  for (let i = 0; i + 1 < pts.length; i++) {
    const lo = pts[i]
    const hi = pts[i + 1]
    if (lo.mid >= 50 && hi.mid <= 50 && lo.mid !== hi.mid) {
      const x = lo.strike + ((lo.mid - 50) / (lo.mid - hi.mid)) * (hi.strike - lo.strike)
      return Math.round(x * 2) / 2
    }
  }
  return null
}

export interface LineInfo {
  value: number | null
  /** Where the number comes from, in a few words. */
  source: string
}

/** The betting line for the full game: the sportsbook's live total when we have it, else the market's own. */
export function gameLine(game: Game): LineInfo {
  const fd = game.fanduel
  if (fd?.total_line != null && (fd.live || game.state === 'pre')) {
    const who = fd.source === 'fanduel' ? 'FanDuel' : fd.source === 'sim' ? 'the practice sportsbook' : 'the sportsbooks'
    return { value: fd.total_line, source: game.state === 'pre' ? `the pregame number from ${who}` : `${who}'s live number, updated as the game goes` }
  }
  const implied = impliedLine(game.ladder ?? [])
  if (implied != null) return { value: implied, source: 'the point where Kalshi prices over and under at 50/50' }
  if (fd?.total_line != null) return { value: fd.total_line, source: 'the pregame number' }
  return { value: game.pregame_total ?? null, source: 'the pregame number' }
}

export const quarterNumber = (s: Segment) => (s === 'game' ? 0 : Number(s[1]))

/** Poll one game's detail (chart points and quarter markets) while it is on screen. */
export function useGameDetail(id: string | null) {
  const [detail, setDetail] = useState<GameDetail | null>(null)
  const [missing, setMissing] = useState(false)
  useEffect(() => {
    setMissing(false)
    if (!id) {
      setDetail(null)
      return
    }
    let alive = true
    setDetail((d) => (d && d.game.id === id ? d : null))
    const load = () =>
      api
        .game(id)
        .then((d) => alive && d && Array.isArray(d.timeline) && setDetail(d))
        .catch((e) => alive && (e as { status?: number })?.status === 404 && setMissing(true))
    void load()
    const timer = window.setInterval(load, 3000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [id])
  return { detail: detail && detail.game.id === id ? detail : null, missing }
}
