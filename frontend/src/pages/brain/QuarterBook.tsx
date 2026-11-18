import clsx from 'clsx'
import { Binoculars, Receipt } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge, Card, Empty, Meter, Segmented, Stat } from '../../components/ui'
import { cents, money, pct, pnlColor, segmentLabel, signedPct } from '../../format'
import type { MarketKind, QuarterCell, QuarterLearning, Segment, Side } from '../../types'

type QuarterFilter = 'all' | Exclude<Segment, 'game'>

const EMPTY: QuarterLearning = { observations: 0, settled: 0, games: 0, cells: [], your_trades: [] }

/** Rows thinner than this are shown but not coloured as if they meant something. */
const TOO_FEW = 5
const THIN = 20

const GREEN = '#19c37d'
const RED = '#f2594b'
const GREY = '#6f7179'

const bandStart = (bucket: string) => parseFloat(bucket) || 0

const sideName = (kind: MarketKind, side: Side) =>
  kind === 'spread' ? (side === 'over' ? 'Backed team covers' : 'Backed team does not cover') : side === 'over' ? 'Over' : 'Under'

/** Merge the four quarters into one row per side and price band, weighting by sample size. */
function combine(cells: QuarterCell[]): QuarterCell[] {
  const groups = new Map<string, QuarterCell[]>()
  for (const c of cells) {
    const key = `${c.side}|${c.bucket}`
    groups.set(key, [...(groups.get(key) ?? []), c])
  }
  return [...groups.values()].map((list) => {
    const n = list.reduce((s, c) => s + c.n, 0)
    const avg = (pick: (c: QuarterCell) => number) => (n ? list.reduce((s, c) => s + pick(c) * c.n, 0) / n : 0)
    return {
      ...list[0],
      n,
      price: avg((c) => c.price),
      win_rate: avg((c) => c.win_rate),
      model: avg((c) => c.model),
      ret: avg((c) => c.ret),
    }
  })
}

const GRID = 'grid grid-cols-[minmax(150px,1.3fr)_56px_72px_56px_96px_minmax(90px,1fr)_96px] items-center gap-3'

function BookTable({ rows, kind }: { rows: QuarterCell[]; kind: MarketKind }) {
  const sides: Side[] = ['under', 'over']
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[700px]">
        <div className={clsx(GRID, 'border-b border-hair px-5 py-2 text-xs text-dim')}>
          <span>Price paid</span>
          <span className="text-right">Seen</span>
          <span className="text-right">Avg price</span>
          <span className="text-right">Won</span>
          <span className="text-right">Model expected</span>
          <span>Won vs price</span>
          <span className="text-right">Per $1 risked</span>
        </div>
        {sides.map((side) => {
          const list = rows.filter((r) => r.side === side).sort((a, b) => bandStart(a.bucket) - bandStart(b.bucket))
          if (list.length === 0) return null
          return (
            <div key={side}>
              <div className="border-b border-hair bg-white/[0.02] px-5 py-2 text-[13px] font-semibold text-white">{sideName(kind, side)}</div>
              {list.map((r) => {
                const few = r.n < TOO_FEW
                const thin = r.n < THIN
                const beat = r.win_rate >= r.price / 100
                return (
                  <div
                    key={`${side}-${r.bucket}`}
                    className={clsx(GRID, 'border-b border-hair px-5 py-2.5 last:border-0', few && 'opacity-45')}
                    title={few ? 'Too few results to read anything into this row' : undefined}
                  >
                    <span className="num text-[13px] text-slate-200">{r.bucket}¢</span>
                    <span className="num text-right text-[13px] text-mute">{r.n.toLocaleString()}</span>
                    <span className="num text-right text-[13px] text-slate-200">{cents(r.price)}</span>
                    <span className="num text-right text-[13px] font-semibold text-white">{few ? '—' : pct(r.win_rate, 0)}</span>
                    <span className="num text-right text-[13px] text-mute">{pct(r.model, 0)}</span>
                    <div>
                      {few ? (
                        <span className="text-xs text-dim">too few</span>
                      ) : (
                        <Meter value={r.win_rate} marker={r.price / 100} tone={thin ? GREY : beat ? GREEN : RED} height={6} />
                      )}
                    </div>
                    <span
                      className={clsx('num text-right text-[13px] font-semibold', few ? 'text-dim' : thin ? 'text-mute' : pnlColor(r.ret))}
                      title={thin && !few ? `Only ${r.n} results: treat as a hint, not a finding` : undefined}
                    >
                      {few ? 'too few' : signedPct(r.ret, 1)}
                    </span>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function YourTrades({ rows }: { rows: QuarterLearning['your_trades'] }) {
  if (rows.length === 0) {
    return (
      <Empty
        icon={<Receipt size={18} />}
        title="You have not traded a quarter yet"
        body="Open a game from Markets, pick Q1 to Q4, and buy a total or a spread. Your results are kept here by quarter, and the agent keeps a record of each one."
        className="!py-8"
      />
    )
  }
  const order = (s: Segment) => ['q1', 'q2', 'q3', 'q4'].indexOf(s)
  const sorted = [...rows].sort((a, b) => order(a.segment) - order(b.segment) || a.kind.localeCompare(b.kind))
  return (
    <div className="px-5">
      {sorted.map((r) => (
        <div key={`${r.segment}-${r.kind}`} className="flex items-center gap-4 border-b border-hair py-3 last:border-b-0">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-white">
              {segmentLabel(r.segment)} {r.kind === 'spread' ? 'spread' : 'total'}
            </div>
            <div className="num text-xs text-dim">
              {r.n} {r.n === 1 ? 'trade' : 'trades'} · won {r.wins}, lost {Math.max(0, r.n - r.wins)}
            </div>
          </div>
          <div className={clsx('num text-sm font-semibold', pnlColor(r.pnl))}>{money(r.pnl, { sign: true })}</div>
        </div>
      ))}
    </div>
  )
}

export default function QuarterBook({ data }: { data: QuarterLearning | undefined | null }) {
  const q = data ?? EMPTY
  const cells = q.cells ?? []
  const [quarter, setQuarter] = useState<QuarterFilter>('all')
  const [kind, setKind] = useState<MarketKind>('total')
  const [checkpoint, setCheckpoint] = useState<'open' | 'mid'>('open')

  const rows = useMemo(() => {
    const match = cells.filter((c) => c.kind === kind && c.checkpoint === checkpoint && (quarter === 'all' || c.segment === quarter))
    return quarter === 'all' ? combine(match) : match
  }, [cells, quarter, kind, checkpoint])

  return (
    <section>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="h-section">Quarter markets</h3>
        <Badge>Watching, not trading</Badge>
      </div>
      <p className="hint mt-1 max-w-2xl">
        The agent does not trade quarter totals or spreads. It writes down their prices shortly after each quarter starts and
        again with about six minutes left, then checks which side won. This is the record to look at before ever letting it
        trade them.
      </p>

      <Card className="mt-3 overflow-hidden">
        <div className="grid grid-cols-3 gap-4 p-5">
          <Stat label="Prices recorded" sub="snapshots taken">
            {q.observations.toLocaleString()}
          </Stat>
          <Stat label="Checked" sub="compared with the result">
            {q.settled.toLocaleString()}
          </Stat>
          <Stat label="Games" sub="with a quarter watched">
            {q.games.toLocaleString()}
          </Stat>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-hair px-5 py-3">
          <span className="mr-1 text-sm font-semibold text-white">What paid</span>
          <Segmented<QuarterFilter>
            id="qb-quarter"
            value={quarter}
            onChange={setQuarter}
            options={[
              { value: 'all', label: 'All' },
              { value: 'q1', label: 'Q1' },
              { value: 'q2', label: 'Q2' },
              { value: 'q3', label: 'Q3' },
              { value: 'q4', label: 'Q4' },
            ]}
          />
          <Segmented<MarketKind>
            id="qb-kind"
            value={kind}
            onChange={setKind}
            options={[
              { value: 'total', label: 'Total' },
              { value: 'spread', label: 'Spread' },
            ]}
          />
          <Segmented<'open' | 'mid'>
            id="qb-checkpoint"
            value={checkpoint}
            onChange={setCheckpoint}
            options={[
              { value: 'open', label: 'At the start' },
              { value: 'mid', label: 'About 6:00 left' },
            ]}
          />
        </div>

        {cells.length === 0 ? (
          <Empty
            icon={<Binoculars size={18} />}
            title="Nothing checked yet"
            body="This fills in as quarters finish. A night of games is enough to start seeing a pattern, and a couple of weeks to start trusting one."
          />
        ) : rows.length === 0 ? (
          <Empty
            icon={<Binoculars size={18} />}
            title={`No ${quarter === 'all' ? '' : `${segmentLabel(quarter)} `}${kind === 'spread' ? 'spreads' : 'totals'} checked at this point yet`}
            body="Try another quarter, market or moment. Only prices that have a result are shown."
            className="!py-8"
          />
        ) : (
          <>
            <BookTable rows={rows} kind={kind} />
            <p className="hint border-t border-hair px-5 py-3 text-xs">
              The bar is how often that side won; the white tick is the price paid. A bar past the tick means it paid better than
              its price. Returns are after fees. Faint rows have too few results to mean anything.
            </p>
          </>
        )}

        <div className="border-t border-hair">
          <h4 className="px-5 pb-1 pt-4 text-sm font-semibold text-white">Your quarter trades</h4>
          <YourTrades rows={q.your_trades ?? []} />
        </div>
      </Card>
    </section>
  )
}
