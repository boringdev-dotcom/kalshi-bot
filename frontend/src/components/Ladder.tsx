import { motion } from 'framer-motion'
import clsx from 'clsx'
import { Layers, Lock, LocateFixed } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { cents, fixed, mmss, noLabel, pct, segmentLabel, signedPct, teamColor, tradeLabel, yesLabel } from '../format'
import type { Game, LadderRung, MarketKind, Position, QuarterMarkets, QuarterSummary, Segment, Side } from '../types'
import { Card, Empty, LiveDot, Segmented, Skeleton } from './ui'

export interface TicketTarget {
  rung: LadderRung
  side: Side
}

/** Which market of a game the ladder is showing. */
export interface MarketView {
  segment: Segment
  kind: MarketKind
}

export const DEFAULT_VIEW: MarketView = { segment: 'game', kind: 'total' }

const QUARTERS: Segment[] = ['q1', 'q2', 'q3', 'q4']

function PriceButton({
  side,
  price,
  bid,
  name,
  onClick,
  disabled,
  children,
}: {
  side: Side
  price: number | null
  bid: number | null
  /** What is being bought, for the tooltip. */
  name: string
  onClick: () => void
  disabled: boolean
  children?: React.ReactNode
}) {
  const tone = side === 'under' ? 'mint' : 'coral'
  const off = price == null || disabled
  return (
    <button
      disabled={off}
      onClick={onClick}
      title={price == null ? 'No offer' : `Buy ${name} at ${cents(price)}${bid != null ? ` · bid ${cents(bid)}` : ''}`}
      className={clsx(
        'group/btn num flex h-8 w-full items-center justify-center gap-1.5 rounded-lg border px-1.5 text-xs font-semibold transition-all duration-150',
        off
          ? 'cursor-not-allowed border-transparent bg-white/[0.02] text-ink-600'
          : tone === 'mint'
            ? 'border-mint/15 bg-mint/[0.07] text-mint hover:border-mint/50 hover:bg-mint/20 active:scale-95'
            : 'border-coral/15 bg-coral/[0.07] text-coral hover:border-coral/50 hover:bg-coral/20 active:scale-95',
      )}
    >
      {children}
      {cents(price)}
    </button>
  )
}

function EdgeChip({ edge, title }: { edge: number | null; title?: string }) {
  if (edge == null) return <span className="num text-[11px] text-ink-600">—</span>
  const pos = edge > 0.004
  const neg = edge < -0.004
  return (
    <span
      className={clsx(
        'num inline-flex min-w-[52px] justify-center rounded-md px-1.5 py-[2px] text-[10.5px] font-semibold',
        pos ? 'bg-mint/15 text-mint' : neg ? 'bg-white/[0.03] text-dim' : 'bg-white/[0.04] text-mute',
      )}
      title={title ?? 'Model probability minus the price you would pay'}
    >
      {signedPct(edge, 1)}
    </span>
  )
}

/** Model chance as a bar, with a white tick where the price says the chance is. */
function ChanceBar({ p, price }: { p: number; price: number | null }) {
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-[6px] flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <motion.div
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ background: p > 0.9 ? '#3ddc97' : p > 0.6 ? '#8b9cff' : p > 0.35 ? '#f5b74e' : '#ff6b6b' }}
          initial={false}
          animate={{ width: `${Math.round(p * 100)}%` }}
          transition={{ type: 'spring', stiffness: 140, damping: 24 }}
        />
        {price != null && (
          <span className="absolute inset-y-0 w-[2px] bg-white/80" style={{ left: `${price}%` }} title={`Price implies ${price}%`} />
        )}
      </div>
      <span className="num w-[38px] text-right text-[11px] font-medium text-slate-300">
        {pct(p, p > 0.995 || p < 0.005 ? 1 : 0)}
      </span>
    </div>
  )
}

const vol = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : Math.round(v || 0))

const firstWord = (label: string) => label.trim().split(/\s+/)[0] || label

/* ───────────────────────── switcher ───────────────────────── */

function MarketSwitcher({
  game,
  view,
  onChange,
}: {
  game: Game
  view: MarketView
  onChange: (v: MarketView) => void
}) {
  const quarters = game.quarters ?? []
  const byseg = new Map(quarters.map((q) => [q.segment, q]))
  const chips: { segment: Segment; label: string; q?: QuarterSummary }[] = [
    { segment: 'game', label: 'Game total' },
    ...QUARTERS.map((s) => ({ segment: s, label: s.toUpperCase(), q: byseg.get(s) })),
  ]
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="inline-flex rounded-xl border border-hair bg-ink-900/70 p-1">
        {chips.map((c) => {
          const active = view.segment === c.segment
          const status = c.q?.status
          return (
            <button
              key={c.segment}
              type="button"
              onClick={() => onChange({ segment: c.segment, kind: c.segment === 'game' ? 'total' : view.kind })}
              title={
                c.segment === 'game'
                  ? 'Full-game total points'
                  : status === 'live'
                    ? `${c.label} is being played`
                    : status === 'final'
                      ? `${c.label} is over`
                      : `${c.label} has not started`
              }
              className={clsx(
                'relative flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11.5px] font-semibold transition-colors',
                active ? 'text-slate-50' : status === 'final' ? 'text-ink-600 hover:text-dim' : 'text-dim hover:text-slate-300',
              )}
            >
              {active && (
                <motion.span
                  layoutId={`market-seg-${game.id}`}
                  className="absolute inset-0 rounded-lg bg-white/[0.09] shadow-[inset_0_0_0_1px_rgba(139,156,255,0.35)]"
                  transition={{ type: 'spring', stiffness: 500, damping: 36 }}
                />
              )}
              <span className="relative flex items-center gap-1.5">
                {status === 'live' && <LiveDot size={6} color="#3ddc97" />}
                {status === 'final' && <span className="h-1.5 w-1.5 rounded-full bg-ink-600" />}
                {status === 'upcoming' && <span className="h-1.5 w-1.5 rounded-full border border-dim" />}
                {c.label}
              </span>
            </button>
          )
        })}
      </div>
      {view.segment !== 'game' && (
        <Segmented<MarketKind>
          id={`market-kind-${game.id}`}
          size="md"
          value={view.kind}
          onChange={(kind) => onChange({ ...view, kind })}
          options={[
            { value: 'total', label: 'Total' },
            { value: 'spread', label: 'Spread' },
          ]}
        />
      )}
    </div>
  )
}

function QuarterStrip({ game, q, kind }: { game: Game; q: QuarterSummary; kind: MarketKind }) {
  const proj = q.projection
  const total = q.home_points + q.away_points
  const started = q.status !== 'upcoming'
  const lead = proj ? (proj.margin_mean >= 0 ? game.home.abbr : game.away.abbr) : null
  return (
    <div className="grid grid-cols-3 divide-x divide-hair border-b border-hair bg-white/[0.015]">
      <div className="px-4 py-2.5">
        <div className="label !text-[9.5px]">{q.label} score</div>
        <div className="num mt-1 flex items-baseline gap-1.5 text-[15px] font-semibold">
          <span style={{ color: teamColor(game.away.color) }}>{game.away.abbr}</span>
          <span className="text-slate-100">{started ? q.away_points : '–'}</span>
          <span className="text-dim">·</span>
          <span className="text-slate-100">{started ? q.home_points : '–'}</span>
          <span style={{ color: teamColor(game.home.color) }}>{game.home.abbr}</span>
        </div>
        <div className="num mt-0.5 text-[10.5px] text-dim">{started ? `${total} points so far` : 'Not started'}</div>
      </div>
      <div className="px-4 py-2.5">
        <div className="label !text-[9.5px]">Time left in {q.label}</div>
        <div className="num mt-1 flex items-center gap-1.5 text-[15px] font-semibold text-slate-100">
          {q.status === 'live' && <LiveDot size={6} />}
          {q.status === 'final' ? 'Over' : mmss(q.seconds_remaining)}
        </div>
        <div className="mt-0.5 text-[10.5px] text-dim">
          {q.status === 'final' ? 'Settled on the score at the horn' : q.status === 'live' ? 'In play' : 'Opens at the tip of the quarter'}
        </div>
      </div>
      <div className="px-4 py-2.5">
        <div className="label !text-[9.5px]">{kind === 'spread' ? `Projected ${q.label} margin` : `Projected ${q.label} total`}</div>
        <div className="num mt-1 text-[15px] font-semibold text-peri">
          {q.status === 'final'
            ? kind === 'spread'
              ? q.home_points === q.away_points
                ? 'Level'
                : `${q.home_points > q.away_points ? game.home.abbr : game.away.abbr} by ${Math.abs(q.home_points - q.away_points)}`
              : total
            : !proj
              ? '—'
              : kind === 'spread'
                ? Math.abs(proj.margin_mean) < 0.05
                  ? 'Level'
                  : `${lead} by ${fixed(Math.abs(proj.margin_mean), 1)}`
                : fixed(proj.total_mean, 1)}
        </div>
        <div className="num mt-0.5 text-[10.5px] text-dim">
          {q.status === 'final' ? 'Final' : proj ? `± ${fixed(kind === 'spread' ? proj.margin_sd : proj.total_sd, 1)} pts` : 'No projection yet'}
        </div>
      </div>
    </div>
  )
}

/* ───────────────────────── rows ───────────────────────── */

const TOTAL_GRID = 'grid grid-cols-[70px_84px_minmax(90px,1fr)_70px_84px_56px] items-center gap-2'
const SPREAD_GRID = 'grid grid-cols-[92px_78px_minmax(80px,1fr)_66px_minmax(118px,auto)_48px] items-center gap-2'

function HoldingTag({ pos }: { pos: Position }) {
  return (
    <span className="num pointer-events-none absolute right-[70px] top-1/2 hidden -translate-y-1/2 rounded bg-peri/20 px-1 text-[9px] font-semibold text-peri xl:block">
      holding {pos.contracts} · {tradeLabel(pos)}
    </span>
  )
}

function TotalRows({
  rows,
  held,
  closed,
  anchorTicker,
  anchorTag,
  anchorRef,
  onPick,
}: {
  rows: LadderRung[]
  held: Map<string, Position>
  closed: boolean
  anchorTicker: string | null
  anchorTag: string
  anchorRef: React.MutableRefObject<HTMLDivElement | null>
  onPick: (t: TicketTarget) => void
}) {
  const bestEdge = Math.max(0, ...rows.map((r) => r.edge_under ?? 0))
  return (
    <>
      {rows.map((r) => {
        const isAnchor = anchorTicker === r.ticker
        const pos = held.get(r.ticker)
        const top = bestEdge > 0.01 && r.edge_under === bestEdge
        return (
          <div
            key={r.ticker}
            ref={isAnchor ? anchorRef : undefined}
            className={clsx(
              TOTAL_GRID,
              'group relative px-4 py-1.5 transition-colors hover:bg-white/[0.035]',
              isAnchor && 'bg-gold/[0.05]',
              pos && 'bg-peri/[0.06]',
              closed && 'opacity-60',
            )}
          >
            {isAnchor && <span className="absolute inset-y-0 left-0 w-[2px] bg-gold" />}
            {pos && <span className="absolute inset-y-0 left-0 w-[2px] bg-peri" />}
            <div className="flex items-center gap-1.5">
              <span className="num text-[13px] font-semibold text-slate-100">{r.strike.toFixed(1)}</span>
              {isAnchor && (
                <span className="rounded bg-gold/15 px-1 text-[8.5px] font-bold uppercase tracking-wider text-gold" title="Closest strike to the book line">
                  {anchorTag}
                </span>
              )}
            </div>
            <PriceButton side="under" price={r.no_ask} bid={r.no_bid} name={noLabel(r)} disabled={closed} onClick={() => onPick({ rung: r, side: 'under' })} />
            <ChanceBar p={r.p_under} price={r.no_ask} />
            <div className="flex justify-center">
              <span className={clsx(top && 'rounded-md ring-1 ring-mint/50')}>
                <EdgeChip edge={r.edge_under} />
              </span>
            </div>
            <PriceButton side="over" price={r.yes_ask} bid={r.yes_bid} name={yesLabel(r)} disabled={closed} onClick={() => onPick({ rung: r, side: 'over' })} />
            <div className="num text-right text-[10.5px] text-dim">{vol(r.volume)}</div>
            {pos && <HoldingTag pos={pos} />}
          </div>
        )
      })}
    </>
  )
}

function SpreadRows({
  game,
  rows,
  held,
  closed,
  onPick,
}: {
  game: Game
  rows: LadderRung[]
  held: Map<string, Position>
  closed: boolean
  onPick: (t: TicketTarget) => void
}) {
  // Two groups, away first (the order a matchup is written in), each strike ascending.
  const groups = useMemo(() => {
    const by = new Map<string, LadderRung[]>()
    for (const r of rows) {
      const key = r.team ?? '—'
      by.set(key, [...(by.get(key) ?? []), r])
    }
    const order = [game.away.abbr, game.home.abbr]
    return [...by.entries()]
      .sort((a, b) => {
        const ia = order.indexOf(a[0])
        const ib = order.indexOf(b[0])
        return (ia < 0 ? 9 : ia) - (ib < 0 ? 9 : ib)
      })
      .map(([team, list]) => ({ team, list: list.sort((a, b) => a.strike - b.strike) }))
  }, [rows, game.away.abbr, game.home.abbr])

  const colorOf = (team: string) =>
    team === game.home.abbr ? teamColor(game.home.color) : team === game.away.abbr ? teamColor(game.away.color) : '#8d96a8'
  const nameOf = (team: string) => (team === game.home.abbr ? game.home.name : team === game.away.abbr ? game.away.name : team)

  return (
    <>
      {groups.map((g) => (
        <div key={g.team}>
          <div className="flex items-center gap-2 border-b border-hair bg-white/[0.02] px-4 py-1.5">
            <span className="h-2.5 w-[3px] rounded-full" style={{ background: colorOf(g.team) }} />
            <span className="text-[11.5px] font-bold tracking-wide" style={{ color: colorOf(g.team) }}>
              {g.team}
            </span>
            <span className="truncate text-[10.5px] text-dim">{nameOf(g.team)} to win the quarter by more than…</span>
          </div>
          {g.list.map((r) => {
            const pos = held.get(r.ticker)
            const pYes = 1 - r.p_under
            return (
              <div
                key={r.ticker}
                className={clsx(
                  SPREAD_GRID,
                  'group relative px-4 py-1.5 transition-colors hover:bg-white/[0.035]',
                  pos && 'bg-peri/[0.06]',
                  closed && 'opacity-60',
                )}
              >
                {pos && <span className="absolute inset-y-0 left-0 w-[2px] bg-peri" />}
                <span className="num truncate text-[12.5px] font-semibold" style={{ color: colorOf(g.team) }}>
                  {yesLabel(r)}
                </span>
                <PriceButton side="over" price={r.yes_ask} bid={r.yes_bid} name={yesLabel(r)} disabled={closed} onClick={() => onPick({ rung: r, side: 'over' })} />
                <ChanceBar p={pYes} price={r.yes_ask} />
                <div className="flex justify-center">
                  <EdgeChip edge={r.edge_over} title={`${yesLabel(r)}: model chance minus the price`} />
                </div>
                <div
                  title={
                    r.edge_under == null
                      ? `${noLabel(r)}: no offer`
                      : `${noLabel(r)}: model ${pct(r.p_under, 0)}, edge ${signedPct(r.edge_under, 1)}`
                  }
                >
                  <PriceButton side="under" price={r.no_ask} bid={r.no_bid} name={noLabel(r)} disabled={closed} onClick={() => onPick({ rung: r, side: 'under' })}>
                    <span className="truncate font-sans text-[10.5px] font-medium opacity-80">{noLabel(r)}</span>
                  </PriceButton>
                </div>
                <div className="num text-right text-[10.5px] text-dim">{vol(r.volume)}</div>
                {pos && <HoldingTag pos={pos} />}
              </div>
            )
          })}
        </div>
      ))}
    </>
  )
}

/* ───────────────────────── card ───────────────────────── */

export default function Ladder({
  game,
  quarterMarkets,
  positions,
  view,
  onViewChange,
  onPick,
}: {
  game: Game
  /** Quarter rungs from the game detail call. null while it is still loading. */
  quarterMarkets: QuarterMarkets[] | null
  positions: Position[]
  view: MarketView
  onViewChange: (v: MarketView) => void
  onPick: (t: TicketTarget) => void
}) {
  const [range, setRange] = useState<'near' | 'all'>('near')
  const isGame = view.segment === 'game'
  const quarter = (game.quarters ?? []).find((q) => q.segment === view.segment) ?? null
  const qm = quarterMarkets?.find((m) => m.segment === view.segment) ?? null
  const loadingQuarter = !isGame && quarterMarkets == null

  const rows = useMemo(() => {
    const list = isGame ? game.ladder ?? [] : (view.kind === 'spread' ? qm?.spreads : qm?.totals) ?? []
    return [...list].sort((a, b) => a.strike - b.strike)
  }, [isGame, game.ladder, qm, view.kind])

  const anchor = game.fanduel?.total_line ?? game.projection?.mean ?? game.pregame_total
  const anchorIdx = useMemo(() => {
    if (!isGame || anchor == null || rows.length === 0) return -1
    let best = 0
    for (let i = 1; i < rows.length; i++)
      if (Math.abs(rows[i].strike - anchor) < Math.abs(rows[best].strike - anchor)) best = i
    return best
  }, [rows, anchor, isGame])

  const visible = useMemo(() => {
    if (!isGame || range === 'all' || anchorIdx < 0) return rows
    // Unders live above the line, so show more room above than below.
    return rows.slice(Math.max(0, anchorIdx - 3), anchorIdx + 11)
  }, [rows, range, anchorIdx, isGame])

  const held = useMemo(() => {
    const m = new Map<string, Position>()
    for (const p of positions) m.set(p.ticker, p)
    return m
  }, [positions])

  const anchorRef = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const recenter = () => {
    const el = anchorRef.current
    const box = scrollRef.current
    if (el && box) box.scrollTo({ top: el.offsetTop - box.clientHeight / 2 + el.clientHeight / 2, behavior: 'smooth' })
  }
  useEffect(() => {
    if (isGame && range === 'all') recenter()
  }, [range, game.id, isGame])

  const quarterOver = !isGame && quarter?.status === 'final'
  const closed = game.state === 'final' || quarterOver
  const segName = segmentLabel(view.segment)
  const marketName = isGame ? 'totals' : `${segName} ${view.kind}`
  const noWord = rows[0] ? firstWord(noLabel(rows[0])) : 'Under'
  const yesWord = rows[0] ? firstWord(yesLabel(rows[0])) : 'Over'

  return (
    <div className="space-y-2">
      <MarketSwitcher game={game} view={view} onChange={onViewChange} />
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 pb-3 pt-4">
          <div>
            <h3 className="label">
              {isGame ? 'Kalshi totals ladder' : `Kalshi ${segName} ${view.kind === 'spread' ? 'spread' : 'total'}`}
            </h3>
            <p className="mt-1 text-[11px] text-dim">
              {isGame
                ? 'Under pays if the final total stays below the strike. Tap a price to open a ticket.'
                : view.kind === 'spread'
                  ? `Each line is a team winning ${segName} by more than the number. The right-hand button is the other side: that team does not.`
                  : `Points scored by both teams in ${segName} only${view.segment === 'q4' ? ', overtime not counted' : ''}. Tap a price to open a ticket.`}
            </p>
          </div>
          {isGame && (
            <div className="flex items-center gap-2">
              {range === 'all' && anchorIdx >= 0 && (
                <button
                  onClick={recenter}
                  className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-mute hover:bg-white/[0.05] hover:text-slate-200"
                >
                  <LocateFixed size={12} /> Line
                </button>
              )}
              <Segmented
                id="ladder-range"
                value={range}
                onChange={setRange}
                options={[
                  { value: 'near', label: 'Near the line' },
                  { value: 'all', label: `All ${rows.length}` },
                ]}
              />
            </div>
          )}
        </div>

        {!isGame && quarter && (
          <div className="border-t border-hair">
            <QuarterStrip game={game} q={quarter} kind={view.kind} />
          </div>
        )}

        {quarterOver && rows.length > 0 && (
          <div className="flex items-center gap-2 border-b border-hair bg-white/[0.02] px-4 py-2 text-[11.5px] text-mute">
            <Lock size={12} className="text-dim" /> This quarter is over. These markets have settled and can no longer be traded.
          </div>
        )}

        {loadingQuarter ? (
          <div className="space-y-2 px-4 py-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <Empty
            icon={<Layers size={18} />}
            title={isGame ? 'No totals market for this game yet' : `Kalshi has no ${marketName} market for this game yet`}
            body={
              isGame
                ? 'Kalshi usually lists the totals ladder the day of the game. It appears here as soon as it opens.'
                : 'Quarter markets are usually listed the day of the game. This fills in as soon as Kalshi opens one.'
            }
          />
        ) : view.kind === 'spread' && !isGame ? (
          <>
            <div className={clsx(SPREAD_GRID, 'border-y border-hair bg-white/[0.015] px-4 py-1.5 text-[9.5px] font-semibold uppercase tracking-wider text-dim')}>
              <span>Line</span>
              <span className="text-center">Buy</span>
              <span>Model: covers</span>
              <span className="text-center">Edge</span>
              <span className="text-center">Buy the other side</span>
              <span className="text-right">Vol</span>
            </div>
            <SpreadRows game={game} rows={visible} held={held} closed={closed} onPick={onPick} />
          </>
        ) : (
          <>
            <div className={clsx(TOTAL_GRID, 'border-y border-hair bg-white/[0.015] px-4 py-1.5 text-[9.5px] font-semibold uppercase tracking-wider text-dim')}>
              <span>Strike</span>
              <span className="text-center">Buy {noWord.toLowerCase()}</span>
              <span>Model: stays {noWord.toLowerCase()}</span>
              <span className="text-center">Edge</span>
              <span className="text-center">Buy {yesWord.toLowerCase()}</span>
              <span className="text-right">Vol</span>
            </div>
            <div ref={scrollRef} className={clsx('relative', isGame && range === 'all' && 'max-h-[440px] overflow-y-auto')}>
              <TotalRows
                rows={visible}
                held={held}
                closed={closed}
                anchorTicker={anchorIdx >= 0 ? rows[anchorIdx].ticker : null}
                anchorTag={game.fanduel?.source === 'fanduel' ? 'FD' : 'Line'}
                anchorRef={anchorRef}
                onPick={onPick}
              />
            </div>
          </>
        )}

        {rows.length > 0 && !loadingQuarter && (
          <div className="flex items-center gap-4 border-t border-hair px-4 py-2 text-[10.5px] text-dim">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-[2px] bg-white/80" /> price-implied chance
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-4 rounded-full bg-peri" /> model chance
            </span>
            <span className="ml-auto">Edge = model − price</span>
          </div>
        )}
      </Card>
    </div>
  )
}
