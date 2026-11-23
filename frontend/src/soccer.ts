/**
 * The soccer desk's data: types, API calls and a polling hook. Kept apart from the NBA
 * store and socket on purpose; soccer refreshes by polling /api/soccer.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from './api'
import type { WatchNote } from './types'

export type SSide = 'yes' | 'no'
export type SSegment = 'match' | '1h'
export type SKind = 'winner' | 'total' | 'spread'

export interface STeam {
  name: string
  short: string
  abbr: string
  color: string
  logo: string
  score: number
  half_score: number | null
  red_cards: number
}

export interface SMarket {
  ticker: string
  segment: SSegment
  kind: SKind
  outcome: 'home' | 'away' | 'tie' | null
  strike: number | null
  yes_label: string
  no_label: string
  yes_bid: number | null
  yes_ask: number | null
  no_bid: number | null
  no_ask: number | null
  volume: number
  p_yes: number | null
  result: string
  edge_yes: number | null
  edge_no: number | null
}

export interface SProjection {
  home_goals: number
  away_goals: number
  total: number
  p_home: number
  p_draw: number
  p_away: number
}

export interface SEvent {
  minute: string
  period: number
  type: string
  team: 'home' | 'away' | null
  text: string
  goal: boolean
}

export interface SMatch {
  id: string
  league: string
  league_name: string
  label: string
  home: STeam
  away: STeam
  start_time: string
  state: 'pre' | 'live' | 'final'
  period: number
  minute: number
  clock: string
  status: string
  halftime: boolean
  winner: Partial<Record<'home' | 'tie' | 'away', SMarket>> | null
  total_line: number | null
  projection: Record<SSegment, SProjection> | null
  last_goal: SEvent | null
  has_markets: boolean
}

export interface SPosition {
  id: number
  match_id: string
  match_label: string
  league: string
  ticker: string
  segment: SSegment
  kind: SKind
  side: SSide
  label: string
  contracts: number
  entry_price: number
  mark_price: number
  cost: number
  value: number
  pnl: number
  max_profit: number
  p_win: number | null
  p_entry: number | null
  mode: string
  opened_at: string
  can_sell: boolean
  /** The agent may sell it if it goes badly wrong. */
  watch: boolean
  watch_note: WatchNote | null
}

export interface STrade {
  id: number
  match_label: string
  label: string
  contracts: number
  entry_price: number
  exit_price: number
  cost: number
  pnl: number
  exit_reason: string
  closed_at: string
}

export interface SAccount {
  mode: 'paper' | 'live'
  cash: number
  exposure: number
  open_value: number
  pnl_open: number
  pnl_total: number
  wins: number
  losses: number
  open_positions: number
  paper_bankroll: number
}

export interface SBoard {
  leagues: { key: string; name: string }[]
  matches: SMatch[]
  account: SAccount
  positions: SPosition[]
  feeds: Record<string, { ok: boolean; detail: string }>
  updated_at: string | null
}

export interface SDetail {
  match: SMatch
  markets: SMarket[]
  first_half_line: number | null
  events: SEvent[]
  stats: Record<string, { home?: number; away?: number }>
  commentary: { minute: string; text: string }[]
  prior: { home_goals: number | null; away_goals: number | null; source: string }
  positions: SPosition[]
  account: SAccount
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api/soccer${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } })
  } catch {
    throw new ApiError('Backend unreachable', 0)
  }
  if (res.status === 401) window.dispatchEvent(new Event('courtside:unauthorized'))
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) detail = body.detail[0].msg
    } catch {
      /* keep default */
    }
    throw new ApiError(detail, res.status)
  }
  return (await res.json()) as T
}

export const soccerApi = {
  board: () => req<SBoard>(''),
  match: (id: string) => req<SDetail>(`/matches/${encodeURIComponent(id)}`),
  order: (o: { ticker: string; side: SSide; contracts: number; price: number; watch?: boolean }) =>
    req<SPosition>('/orders', { method: 'POST', body: JSON.stringify(o) }),
  close: (id: number) => req<STrade>(`/positions/${id}/close`, { method: 'POST' }),
  watch: (id: number, on: boolean) => req<SPosition>(`/positions/${id}/watch`, { method: 'POST', body: JSON.stringify({ on }) }),
  trades: (limit = 30) => req<STrade[]>(`/trades?limit=${limit}`),
}

/** Fetch now, then every `ms` while the page is visible. `reload` fetches again at once. */
export function usePoll<T>(load: () => Promise<T>, ms: number, key: string) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const loadRef = useRef(load)
  loadRef.current = load
  const tick = useCallback(async () => {
    try {
      setData(await loadRef.current())
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not load')
    }
  }, [])
  useEffect(() => {
    setData(null)
    void tick()
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') void tick()
    }, ms)
    return () => window.clearInterval(id)
  }, [key, ms, tick])
  return { data, error, reload: tick }
}

export const kickoff = (iso: string) => {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'Scheduled'
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export const dayLabel = (iso: string) => {
  const d = new Date(iso)
  const today = new Date()
  const tomorrow = new Date(today)
  tomorrow.setDate(today.getDate() + 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === tomorrow.toDateString()) return 'Tomorrow'
  return d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' })
}

export function matchStatus(m: SMatch) {
  if (m.state === 'pre') return `${dayLabel(m.start_time)} ${kickoff(m.start_time)}`
  if (m.state === 'final') return 'Full time'
  if (m.halftime) return 'Half time'
  return m.clock || 'Live'
}

export const askOf = (m: SMarket, side: SSide) => (side === 'yes' ? m.yes_ask : m.no_ask)
export const bidOf = (m: SMarket, side: SSide) => (side === 'yes' ? m.yes_bid : m.no_bid)
export const labelOf = (m: SMarket, side: SSide) => (side === 'yes' ? m.yes_label : m.no_label)
export const chanceOf = (m: SMarket, side: SSide) => (m.p_yes == null ? null : side === 'yes' ? m.p_yes : 1 - m.p_yes)
