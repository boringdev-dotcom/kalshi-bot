import { motion } from 'framer-motion'
import clsx from 'clsx'
import { Layers, LocateFixed } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { cents, pct, signedPct } from '../format'
import type { Game, LadderRung, Position, Side } from '../types'
import { Card, Empty, Segmented } from './ui'

export interface TicketTarget {
  rung: LadderRung
  side: Side
}

function PriceButton({
  side,
  price,
  bid,
  onClick,
  disabled,
}: {
  side: Side
  price: number | null
  bid: number | null
  onClick: () => void
  disabled: boolean
}) {
  const tone = side === 'under' ? 'mint' : 'coral'
  const off = price == null || disabled
  return (
    <button
      disabled={off}
      onClick={onClick}
      title={
        price == null
          ? 'No offer'
          : `Buy ${side} at ${cents(price)}${bid != null ? ` · bid ${cents(bid)}` : ''}`
      }
      className={clsx(
        'group/btn num flex h-8 w-full items-center justify-center gap-1 rounded-lg border text-xs font-semibold transition-all duration-150',
        off
          ? 'cursor-not-allowed border-transparent bg-white/[0.02] text-ink-600'
          : tone === 'mint'
            ? 'border-mint/15 bg-mint/[0.07] text-mint hover:border-mint/50 hover:bg-mint/20 active:scale-95'
            : 'border-coral/15 bg-coral/[0.07] text-coral hover:border-coral/50 hover:bg-coral/20 active:scale-95',
      )}
    >
      {cents(price)}
    </button>
  )
}

function EdgeChip({ edge }: { edge: number | null }) {
  if (edge == null) return <span className="num text-[11px] text-ink-600">—</span>
  const pos = edge > 0.004
  const neg = edge < -0.004
  return (
    <span
      className={clsx(
        'num inline-flex min-w-[52px] justify-center rounded-md px-1.5 py-[2px] text-[10.5px] font-semibold',
        pos ? 'bg-mint/15 text-mint' : neg ? 'bg-white/[0.03] text-dim' : 'bg-white/[0.04] text-mute',
      )}
      title="Model probability minus the price you would pay"
    >
      {signedPct(edge, 1)}
    </span>
  )
}

export default function Ladder({
  game,
  positions,
  onPick,
}: {
  game: Game
  positions: Position[]
  onPick: (t: TicketTarget) => void
}) {
  const [range, setRange] = useState<'near' | 'all'>('near')
  const rows = useMemo(() => [...game.ladder].sort((a, b) => a.strike - b.strike), [game.ladder])
  const anchor = game.fanduel?.total_line ?? game.projection?.mean ?? game.pregame_total
  const anchorIdx = useMemo(() => {
    if (anchor == null || rows.length === 0) return -1
    let best = 0
    for (let i = 1; i < rows.length; i++)
      if (Math.abs(rows[i].strike - anchor) < Math.abs(rows[best].strike - anchor)) best = i
    return best
  }, [rows, anchor])

  const visible = useMemo(() => {
    if (range === 'all' || anchorIdx < 0) return rows
    // Unders live above the line, so show more room above than below.
    return rows.slice(Math.max(0, anchorIdx - 3), anchorIdx + 11)
  }, [rows, range, anchorIdx])

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
    if (range === 'all') recenter()
  }, [range, game.id])

  const closed = game.state === 'final'
  const bestEdge = Math.max(0, ...visible.map((r) => r.edge_under ?? 0))

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 pb-3 pt-4">
        <div>
          <h3 className="label">Kalshi totals ladder</h3>
          <p className="mt-1 text-[11px] text-dim">
            Under pays if the final total stays below the strike. Tap a price to open a ticket.
          </p>
        </div>
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
      </div>

      {rows.length === 0 ? (
        <Empty
          icon={<Layers size={18} />}
          title="No totals market for this game yet"
          body="Kalshi usually lists the totals ladder the day of the game. It appears here as soon as it opens."
        />
      ) : (
        <>
          <div className="grid grid-cols-[70px_84px_minmax(90px,1fr)_70px_84px_56px] items-center gap-2 border-y border-hair bg-white/[0.015] px-4 py-1.5 text-[9.5px] font-semibold uppercase tracking-wider text-dim">
            <span>Strike</span>
            <span className="text-center">Buy under</span>
            <span>Model: stays under</span>
            <span className="text-center">Edge</span>
            <span className="text-center">Buy over</span>
            <span className="text-right">Vol</span>
          </div>
          <div ref={scrollRef} className={clsx('relative', range === 'all' && 'max-h-[440px] overflow-y-auto')}>
            {visible.map((r) => {
              const isAnchor = anchorIdx >= 0 && rows[anchorIdx].ticker === r.ticker
              const pos = held.get(r.ticker)
              const top = bestEdge > 0.01 && r.edge_under === bestEdge
              return (
                <div
                  key={r.ticker}
                  ref={isAnchor ? anchorRef : undefined}
                  className={clsx(
                    'group relative grid grid-cols-[70px_84px_minmax(90px,1fr)_70px_84px_56px] items-center gap-2 px-4 py-1.5 transition-colors hover:bg-white/[0.035]',
                    isAnchor && 'bg-gold/[0.05]',
                    pos && 'bg-peri/[0.06]',
                  )}
                >
                  {isAnchor && <span className="absolute inset-y-0 left-0 w-[2px] bg-gold" />}
                  {pos && <span className="absolute inset-y-0 left-0 w-[2px] bg-peri" />}
                  <div className="flex items-center gap-1.5">
                    <span className="num text-[13px] font-semibold text-slate-100">{r.strike.toFixed(1)}</span>
                    {isAnchor && (
                      <span className="rounded bg-gold/15 px-1 text-[8.5px] font-bold uppercase tracking-wider text-gold" title="Closest strike to the book line">
                        {game.fanduel?.source === 'fanduel' ? 'FD' : 'Line'}
                      </span>
                    )}
                  </div>
                  <PriceButton
                    side="under"
                    price={r.no_ask}
                    bid={r.no_bid}
                    disabled={closed}
                    onClick={() => onPick({ rung: r, side: 'under' })}
                  />
                  <div className="flex items-center gap-2">
                    <div className="relative h-[6px] flex-1 overflow-hidden rounded-full bg-white/[0.06]">
                      <motion.div
                        className="absolute inset-y-0 left-0 rounded-full"
                        style={{
                          background:
                            r.p_under > 0.9 ? '#3ddc97' : r.p_under > 0.6 ? '#8b9cff' : r.p_under > 0.35 ? '#f5b74e' : '#ff6b6b',
                        }}
                        initial={false}
                        animate={{ width: `${Math.round(r.p_under * 100)}%` }}
                        transition={{ type: 'spring', stiffness: 140, damping: 24 }}
                      />
                      {r.no_ask != null && (
                        <span
                          className="absolute inset-y-0 w-[2px] bg-white/80"
                          style={{ left: `${r.no_ask}%` }}
                          title={`Price implies ${r.no_ask}%`}
                        />
                      )}
                    </div>
                    <span className="num w-[38px] text-right text-[11px] font-medium text-slate-300">
                      {pct(r.p_under, r.p_under > 0.995 || r.p_under < 0.005 ? 1 : 0)}
                    </span>
                  </div>
                  <div className="flex justify-center">
                    <span className={clsx(top && 'rounded-md ring-1 ring-mint/50')}>
                      <EdgeChip edge={r.edge_under} />
                    </span>
                  </div>
                  <PriceButton
                    side="over"
                    price={r.yes_ask}
                    bid={r.yes_bid}
                    disabled={closed}
                    onClick={() => onPick({ rung: r, side: 'over' })}
                  />
                  <div className="num text-right text-[10.5px] text-dim">
                    {r.volume >= 1000 ? `${(r.volume / 1000).toFixed(1)}k` : Math.round(r.volume)}
                  </div>
                  {pos && (
                    <span className="num pointer-events-none absolute right-[70px] top-1/2 hidden -translate-y-1/2 rounded bg-peri/20 px-1 text-[9px] font-semibold text-peri xl:block">
                      holding {pos.contracts} {pos.side}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
          <div className="flex items-center gap-4 border-t border-hair px-4 py-2 text-[10.5px] text-dim">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-[2px] bg-white/80" /> price-implied chance
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-4 rounded-full bg-peri" /> model chance
            </span>
            <span className="ml-auto">Edge = model − price</span>
          </div>
        </>
      )}
    </Card>
  )
}
