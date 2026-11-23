import { AnimatePresence, motion } from 'framer-motion'
import clsx from 'clsx'
import { Briefcase, ChevronDown, ChevronRight, History } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from 'recharts'
import { api, ApiError, type AccountHistory } from '../api'
import { Badge, Button, Dialog, Empty, Segmented, SimTag, Skeleton, Stat, Ticker } from '../components/ui'
import { WatchPill } from '../components/Watch'
import { cents, money, pct, pnlColor, relTime, segmentLabel, shortDate, tradeLabel } from '../format'
import { soccerApi, usePoll, type SPosition } from '../soccer'
import { useStore } from '../store'
import type { Position, Trade } from '../types'

const GREEN = '#19c37d'
const RED = '#f2594b'

/* ───────────────────────── Account chart ───────────────────────── */

function ChartTip({ active, payload, range }: { active?: boolean; payload?: { payload: { ts: string; value: number } }[]; range: Range }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  const d = new Date(p.ts)
  const when =
    range === '1D'
      ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
      : range === '1W' || range === '1M'
        ? shortDate(p.ts)
        : d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
  return (
    <div className="rounded-xl bg-ink-800 px-3 py-2 shadow-lift">
      <div className="num text-sm font-semibold text-white">{money(p.value)}</div>
      <div className="num text-xs text-dim">{when}</div>
    </div>
  )
}

const RANGES = ['1D', '1W', '1M', '1Y', 'YTD', 'MAX'] as const
type Range = (typeof RANGES)[number]
const RANGE_KEY = 'courtside.chart-range'
const RANGE_WORDS: Record<Range, string> = { '1D': 'past day', '1W': 'past week', '1M': 'past month', '1Y': 'past year', YTD: 'this year', MAX: 'all time' }

function sinceFor(r: Range): string | undefined {
  const now = new Date()
  const day = 86_400_000
  switch (r) {
    case '1D':
      return new Date(now.getTime() - day).toISOString()
    case '1W':
      return new Date(now.getTime() - 7 * day).toISOString()
    case '1M':
      return new Date(new Date(now).setMonth(now.getMonth() - 1)).toISOString()
    case '1Y':
      return new Date(new Date(now).setFullYear(now.getFullYear() - 1)).toISOString()
    case 'YTD':
      return new Date(now.getFullYear(), 0, 1).toISOString()
    default:
      return undefined
  }
}

/** The account's value over a range, Robinhood style: deposits and withdrawals are not gains. */
function useAccountHistory(range: Range, refresh: unknown) {
  const [data, setData] = useState<{ range: Range; h: AccountHistory } | null>(null)
  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .accountHistory(sinceFor(range))
        .then((h) => alive && setData({ range, h }))
        .catch(() => undefined)
    void load()
    const t = window.setInterval(load, 30_000)
    return () => {
      alive = false
      window.clearInterval(t)
    }
  }, [range, refresh])
  return data
}

function RangeChange({ h, range }: { h: AccountHistory | null; range: Range }) {
  if (!h || h.start == null) return <span className="text-dim">No history for the {RANGE_WORDS[range]} yet</span>
  const moved = h.net_deposits
  return (
    <>
      <span className={clsx('num font-medium', pnlColor(h.change))}>
        {money(h.change, { sign: true })} ({h.change >= 0 ? '+' : ''}
        {(h.change_pct * 100).toFixed(2)}%)
      </span>
      <span className="text-mute"> {RANGE_WORDS[range]}</span>
      {Math.abs(moved) >= 0.01 && (
        <span className="num block text-xs text-dim">
          Leaves out {money(Math.abs(moved))} {moved > 0 ? 'deposited' : 'withdrawn'}
        </span>
      )}
    </>
  )
}

function AccountChart({ h, range, onRange }: { h: AccountHistory | null; range: Range; onRange: (r: Range) => void }) {
  const data = useMemo(() => (h?.points ?? []).map((p, i) => ({ ...p, i })), [h])
  const up = !h || h.change >= 0
  return (
    <div>
      {!h ? (
        <Skeleton className="h-[200px] w-full !rounded-xl2" />
      ) : data.length < 2 ? (
        <div className="flex h-[200px] items-center">
          <p className="hint">Nothing to chart for the {RANGE_WORDS[range]} yet.</p>
        </div>
      ) : (
        <div className="h-[200px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 0, bottom: 8, left: 0 }}>
              <YAxis hide domain={['dataMin', 'dataMax']} />
              <Tooltip content={<ChartTip range={range} />} cursor={{ stroke: 'rgba(255,255,255,0.18)' }} />
              <Line dataKey="value" type="linear" stroke={up ? GREEN : RED} strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="mt-2 flex justify-between border-b border-hair pb-3" role="tablist" aria-label="Chart range">
        {RANGES.map((r) => (
          <button
            key={r}
            type="button"
            role="tab"
            aria-selected={r === range}
            onClick={() => onRange(r)}
            className={clsx(
              'num rounded-full px-3 py-1.5 text-[13px] font-semibold transition-colors',
              r === range ? (up ? 'bg-mint/[0.14] text-mint' : 'bg-coral/[0.14] text-coral') : 'text-mute hover:text-white',
            )}
          >
            {r === 'MAX' ? 'Max' : r}
          </button>
        ))}
      </div>
    </div>
  )
}

/* ───────────────────────── Open positions ───────────────────────── */

const who = (by: 'agent' | 'user') => (by === 'agent' ? 'Agent' : 'You')

function PositionRow({ p, onSell, onWatch }: { p: Position; onSell: (p: Position) => void; onWatch: (p: Position, on: boolean) => Promise<void> }) {
  const worry = p.risk?.level && p.risk.level !== 'low' ? (p.risk.flags?.[0] ?? (p.risk.level === 'high' ? 'High risk' : 'Caution')) : null
  return (
    <motion.li layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="row">
      <div className="min-w-0 flex-1">
        <div className="break-words text-sm font-semibold text-white">
          {tradeLabel(p)} <span className="font-normal text-mute">· {p.game_label}</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-dim">
          <span>{who(p.opened_by)}</span>
          <span>·</span>
          <span>
            {p.contracts} at {cents(p.entry_price)}
          </span>
          <span>·</span>
          <span>{relTime(p.opened_at)}</span>
          {p.simulated && <SimTag />}
          {p.mode === 'live' && <Badge tone="coral">Live</Badge>}
        </div>
        {p.opened_by === 'user' && (
          <div className="mt-1.5">
            <WatchPill on={p.watch} note={p.watch_note} onChange={(on) => onWatch(p, on)} />
          </div>
        )}
      </div>
      <div className="hidden w-[200px] shrink-0 sm:block">
        <div className="num text-[13px] text-slate-200" title={`${pct(p.p_win_entry)} when it was bought`}>
          {pct(p.p_win)} chance now
        </div>
        {worry && (
          <div className={clsx('break-words text-xs', p.risk.level === 'high' ? 'text-coral' : 'text-gold')} title={p.risk.flags?.join(' · ')}>
            {worry}
          </div>
        )}
      </div>
      <div className="w-[96px] shrink-0 text-right">
        <Ticker value={p.value} format={(n) => money(n)} flash={false} className="text-sm font-semibold text-white" />
        <div className={clsx('num text-xs', pnlColor(p.pnl))}>{money(p.pnl, { sign: true })}</div>
      </div>
      <Button size="xs" variant="outline" onClick={() => onSell(p)} className="shrink-0">
        Sell
      </Button>
    </motion.li>
  )
}

/* ───────────────────────── Soccer ───────────────────────── */

/** Soccer keeps its own book; it is listed here so every open bet is in one place. Tap to manage it on its match page. */
function SoccerRow({ p, onWatch }: { p: SPosition; onWatch: (on: boolean) => Promise<void> }) {
  return (
    <li className="border-b border-hair last:border-b-0">
      <Link to={`/soccer/${p.match_id}`} className="row row-hover group !border-b-0">
        <div className="min-w-0 flex-1">
          <div className="break-words text-sm font-semibold text-white">
            {p.label} <span className="font-normal text-mute">· {p.match_label}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-dim">
            <span>
              {p.contracts} at {cents(p.entry_price)}
            </span>
            <span>·</span>
            <span>{relTime(p.opened_at)}</span>
            {p.mode === 'live' && <Badge tone="coral">Live</Badge>}
          </div>
          <div className="mt-1.5">
            <WatchPill on={p.watch} note={p.watch_note} onChange={onWatch} />
          </div>
        </div>
        <div className="hidden w-[200px] shrink-0 sm:block">
          <div className="num text-[13px] text-slate-200">{p.p_win != null ? `${pct(p.p_win)} chance now` : ''}</div>
        </div>
        <div className="w-[96px] shrink-0 text-right">
          <div className="num text-sm font-semibold text-white">{money(p.value)}</div>
          <div className={clsx('num text-xs', pnlColor(p.pnl))}>{money(p.pnl, { sign: true })}</div>
        </div>
        <ChevronRight size={16} className="shrink-0 text-dim group-hover:text-white" />
      </Link>
    </li>
  )
}

function SoccerPositions() {
  const { data, reload } = usePoll(soccerApi.board, 10000, 'portfolio-soccer')
  const toast = useStore((s) => s.toast)
  const watch = async (id: number, on: boolean) => {
    try {
      await soccerApi.watch(id, on)
      reload()
    } catch (e) {
      toast({ level: 'error', title: 'Could not change that', body: e instanceof ApiError ? e.message : '' })
    }
  }
  if (!data) return null
  const { positions, account } = data
  const record = account.wins + account.losses
  return (
    <section className="mt-10">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="h-section">Soccer positions</h2>
        <Link to="/soccer" className="text-[13px] text-mute hover:text-white">
          Soccer desk
        </Link>
      </div>
      <p className="hint mt-1">
        Its own book: {money(account.exposure)} at risk
        {record > 0 && (
          <>
            {' '}· settled <span className={clsx('num', pnlColor(account.pnl_total))}>{money(account.pnl_total, { sign: true })}</span> ({account.wins}W {account.losses}L)
          </>
        )}
        .
      </p>
      {positions.length === 0 ? (
        <p className="mt-3 text-[13px] text-dim">No soccer bets open.</p>
      ) : (
        <ul className="mt-2">
          {positions.map((p) => (
            <SoccerRow key={p.id} p={p} onWatch={(on) => watch(p.id, on)} />
          ))}
        </ul>
      )}
    </section>
  )
}

/* ───────────────────────── History ───────────────────────── */

function outcome(t: Trade): { text: string; className: string } {
  switch (t.exit_reason) {
    case 'settled_win':
      return { text: 'Won', className: 'text-mint' }
    case 'settled_loss':
      return { text: 'Lost', className: 'text-coral' }
    case 'take_profit':
      return { text: 'Took profit', className: 'text-mint' }
    case 'manual':
      return { text: 'Closed by you', className: 'text-mute' }
    default: {
      const who = t.opened_by === 'user' ? 'Agent sold it' : 'Sold early' // your bet, sold because you had it watched
      if (t.exit_verdict === 'saved') return { text: `${who}: avoided a loss`, className: 'text-mint' }
      if (t.exit_verdict === 'shaken_out') return { text: `${who}: would have won`, className: 'text-gold' }
      return { text: who, className: 'text-mute' }
    }
  }
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] text-dim">{label}</div>
      <div className="num text-[13px] text-slate-200">{children}</div>
    </div>
  )
}

function TradeRow({ t }: { t: Trade }) {
  const [open, setOpen] = useState(false)
  const o = outcome(t)
  const settled =
    t.final_total == null
      ? 'Game not finished'
      : t.kind === 'spread'
        ? `${t.team ?? 'Backed team'} ${t.final_total > 0 ? `+${t.final_total}` : t.final_total} in ${segmentLabel(t.segment)}`
        : `${t.final_total} points`
  return (
    <li className="border-b border-hair last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-4 rounded-xl px-1 py-3.5 text-left transition-colors hover:bg-white/[0.035]"
      >
        <span className="min-w-0 flex-1">
          <span className="block break-words text-sm font-semibold text-white">
            {tradeLabel(t)} <span className="font-normal text-mute">· {t.game_label}</span>
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-dim">
            <span className={o.className}>{o.text}</span>
            <span>·</span>
            <span>{who(t.opened_by)}</span>
            <span>·</span>
            <span>{shortDate(t.closed_at)}</span>
            {t.simulated && <SimTag />}
            {t.mode === 'live' && <Badge tone="coral">Live</Badge>}
          </span>
        </span>
        <span className={clsx('num shrink-0 text-sm font-semibold', pnlColor(t.pnl))}>{money(t.pnl, { sign: true })}</span>
        <ChevronDown size={15} className={clsx('shrink-0 text-dim transition-transform', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.16 }}
            className="overflow-hidden"
          >
            <div className="mb-3 grid grid-cols-2 gap-x-6 gap-y-3 rounded-xl bg-ink-800 px-4 py-3 sm:grid-cols-4">
              <Fact label="Bought at → sold at">
                {cents(t.entry_price)} → {cents(t.exit_price)}
              </Fact>
              <Fact label="Cost">
                {money(t.cost)} for {t.contracts}
              </Fact>
              <Fact label="Settled on">{settled}</Fact>
              <Fact label="If held to the end">
                {t.counterfactual_pnl == null ? (
                  'Waiting for the final'
                ) : (
                  <span className={pnlColor(t.counterfactual_pnl)}>{money(t.counterfactual_pnl, { sign: true })}</span>
                )}
              </Fact>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

/* ───────────────────────── Page ───────────────────────── */

export default function Portfolio() {
  const account = useStore((s) => s.app?.account)
  const positions = useStore((s) => s.positions)
  const trades = useStore((s) => s.trades)
  const tradeTick = useStore((s) => s.tradeTick)
  const addTrade = useStore((s) => s.addTrade)
  const upsertPosition = useStore((s) => s.upsertPosition)
  const toast = useStore((s) => s.toast)
  const [range, setRangeState] = useState<Range>(() => {
    try {
      const r = localStorage.getItem(RANGE_KEY) as Range | null
      return r && RANGES.includes(r) ? r : '1D'
    } catch {
      return '1D'
    }
  })
  const setRange = (r: Range) => {
    setRangeState(r)
    try {
      localStorage.setItem(RANGE_KEY, r)
    } catch {
      // the choice just won't be remembered
    }
  }
  const loaded = useAccountHistory(range, tradeTick)
  // Keep the last range's chart up while the new one loads, rather than flashing empty.
  const history = loaded?.h ?? null
  const [closing, setClosing] = useState<Position | null>(null)
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState<'all' | 'agent' | 'user'>('all')

  const shownTrades = useMemo(
    () => (filter === 'all' ? trades : trades.filter((t) => t.opened_by === filter)),
    [trades, filter],
  )
  // Keep the dialog's numbers live while it is open.
  const closingLive = closing ? positions.find((p) => p.id === closing.id) ?? closing : null

  const watchBet = async (p: Position, on: boolean) => {
    try {
      upsertPosition(await api.watchPosition(p.id, on))
    } catch (e) {
      toast({ level: 'error', title: 'Could not change that', body: e instanceof ApiError ? e.message : '' })
    }
  }

  const confirmClose = async () => {
    if (!closing) return
    setBusy(true)
    try {
      const trade = await api.closePosition(closing.id)
      addTrade(trade, closing.id)
      toast({
        level: trade.pnl >= 0 ? 'success' : 'warn',
        title: `Sold ${tradeLabel(trade)}: ${money(trade.pnl, { sign: true })}`,
        body: `${trade.contracts} sold at ${cents(trade.exit_price)} · ${trade.game_label}`,
      })
      setClosing(null)
    } catch (e) {
      toast({ level: 'error', title: 'Could not sell that position', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(false)
    }
  }

  const record = account ? account.wins + account.losses : 0

  return (
    <div className="page">
      <h1 className="h-page">Portfolio</h1>
      <p className="hint mt-1">What your account is worth, what is open right now, and how past trades turned out.</p>

      {/* Hero: the one number that matters, and its chart. */}
      <div className="mt-6">
        <div className="label">Account value</div>
        <div className="mt-1 text-[40px] font-semibold leading-none tracking-tight text-white">
          {account ? <Ticker value={account.equity} format={(n) => money(n)} flash={false} /> : <Skeleton className="h-10 w-48" />}
        </div>
        <div className="mt-2 min-h-5 text-sm">
          {loaded?.range === range ? <RangeChange h={loaded.h} range={range} /> : <Skeleton className="h-5 w-40" />}
        </div>
        {account && record > 0 && (
          <div className="num mt-1 text-xs text-dim">{money(account.pnl_total, { sign: true })} from finished trades, all time</div>
        )}
      </div>
      <div className="mt-3">
        <AccountChart h={history} range={range} onRange={setRange} />
      </div>

      <div className="mt-5 grid grid-cols-3 gap-4 border-y border-hair py-4">
        <Stat label="Buying power" sub="free to use">
          {account ? money(account.cash) : '—'}
        </Stat>
        <Stat label="At risk" sub={account ? `${account.open_positions} open ${account.open_positions === 1 ? 'position' : 'positions'}` : undefined}>
          {account ? money(account.exposure) : '—'}
        </Stat>
        <Stat label="Record" sub={account && record > 0 ? `${pct(account.wins / record)} won` : 'no finished trades yet'}>
          {account ? `${account.wins} – ${account.losses}` : '—'}
        </Stat>
      </div>

      <section className="mt-10">
        <h2 className="h-section">NBA positions</h2>
        {positions.length === 0 ? (
          <Empty
            icon={<Briefcase size={18} />}
            title="Nothing open right now"
            body="Any NBA bet you or the agent makes shows up here with what it is worth and its chance of winning."
          />
        ) : (
          <ul className="mt-2">
            <AnimatePresence initial={false}>
              {positions.map((p) => (
                <PositionRow key={p.id} p={p} onSell={setClosing} onWatch={watchBet} />
              ))}
            </AnimatePresence>
          </ul>
        )}
      </section>

      <SoccerPositions />

      <section className="mt-10">
        <div className="flex items-center justify-between gap-3">
          <h2 className="h-section">History</h2>
          <Segmented
            id="trade-filter"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: 'All' },
              { value: 'agent', label: 'Agent' },
              { value: 'user', label: 'You' },
            ]}
          />
        </div>
        {shownTrades.length === 0 ? (
          <Empty
            icon={<History size={18} />}
            title={filter === 'all' ? 'No finished trades yet' : filter === 'agent' ? 'The agent has no finished trades yet' : 'You have no finished trades yet'}
            body="Once a position wins, loses or is sold, it lands here. Tap one to see what holding to the end would have paid."
          />
        ) : (
          <ul className="mt-2">
            {shownTrades.map((t) => (
              <TradeRow key={t.id} t={t} />
            ))}
          </ul>
        )}
      </section>

      <Dialog
        open={!!closing}
        onClose={() => !busy && setClosing(null)}
        title={closingLive ? `Sell ${tradeLabel(closingLive)}?` : 'Sell this position?'}
        subtitle={closingLive ? closingLive.game_label : undefined}
        width={420}
      >
        {closingLive && (
          <>
            <div className="rounded-2xl bg-ink-800 px-4 py-1 text-sm">
              <div className="flex items-baseline justify-between gap-4 border-b border-hair py-3">
                <span className="text-mute">If you sell now</span>
                <span className="num shrink-0 text-right text-white">
                  <span className="block whitespace-nowrap">about {money(closingLive.value)} back</span>
                  <span className={clsx('block whitespace-nowrap text-xs font-semibold', pnlColor(closingLive.pnl))}>{money(closingLive.pnl, { sign: true })}</span>
                </span>
              </div>
              <div className="flex items-baseline justify-between gap-4 border-b border-hair py-3">
                <span className="text-mute">If you hold and it wins</span>
                <span className="num shrink-0 text-right text-white">
                  <span className="block whitespace-nowrap">{money(closingLive.contracts)} back</span>
                  <span className="block whitespace-nowrap text-xs font-semibold text-mint">{money(closingLive.max_profit, { sign: true })}</span>
                </span>
              </div>
              <div className="flex items-baseline justify-between gap-4 py-3">
                <span className="text-mute">If you hold and it loses</span>
                <span className="num shrink-0 whitespace-nowrap text-right font-semibold text-coral">{money(-closingLive.cost, { sign: true })}</span>
              </div>
            </div>
            <p className="hint mt-3">
              The model gives it a {pct(closingLive.p_win)} chance of winning right now.{' '}
              {closingLive.mode === 'live'
                ? 'This sends a real sell order to Kalshi at the current price.'
                : 'This is a paper position, so nothing is sent to Kalshi.'}
            </p>
            <div className="mt-5 flex gap-2">
              <Button variant="ghost" size="md" className="flex-1" onClick={() => setClosing(null)} disabled={busy}>
                Keep it
              </Button>
              <Button variant="primary" size="md" className="flex-[2]" onClick={confirmClose} loading={busy}>
                Sell now
              </Button>
            </div>
          </>
        )}
      </Dialog>
    </div>
  )
}
