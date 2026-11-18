import clsx from 'clsx'
import { Binoculars, Eye, Receipt } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge, Card, Empty, Meter, Segmented } from '../../components/ui'
import { cents, money, pct, pnlColor, segmentLabel, signedPct } from '../../format'
import type { MarketKind, QuarterCell, QuarterLearning, Segment, Side } from '../../types'

type QuarterFilter = 'all' | Exclude<Segment, 'game'>

const EMPTY: QuarterLearning = { observations: 0, settled: 0, games: 0, cells: [], your_trades: [] }

/** Rows thinner than this are shown but not coloured as if they meant something. */
const TOO_FEW = 5
const THIN = 20

const bandStart = (bucket: string) => parseFloat(bucket) || 0

const sideName = (kind: MarketKind, side: Side) =>
  kind === 'spread' ? (side === 'over' ? 'Backed team covers' : 'Does not cover') : side === 'over' ? 'Over' : 'Under'

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

function Tile({ label, value, sub }: { label: string; value: React.ReactNode; sub: string }) {
  return (
    <div className="rounded-xl border border-hair bg-ink-950/50 p-3.5">
      <div className="label !text-[9.5px]">{label}</div>
      <div className="num mt-1.5 text-lg font-bold leading-none text-slate-50">{value}</div>
      <div className="mt-1.5 text-[10.5px] text-dim">{sub}</div>
    </div>
  )
}

const GRID = 'grid grid-cols-[minmax(150px,1.3fr)_52px_64px_64px_64px_minmax(90px,1fr)_84px] items-center gap-3'

function BookTable({ rows, kind }: { rows: QuarterCell[]; kind: MarketKind }) {
  const sides: Side[] = ['under', 'over']
  return (
    <div className="overflow-x-auto">
      <div className="min-w-[640px]">
        <div className={clsx(GRID, 'border-y border-hair bg-white/[0.015] px-4 py-1.5 text-[9.5px] font-semibold uppercase tracking-wider text-dim')}>
          <span>Side · price paid</span>
          <span className="text-right">Seen</span>
          <span className="text-right">Avg price</span>
          <span className="text-right">Won</span>
          <span className="text-right">Model said</span>
          <span>Won vs price</span>
          <span className="text-right">Per $ risked</span>
        </div>
        {sides.map((side) => {
          const list = rows.filter((r) => r.side === side).sort((a, b) => bandStart(a.bucket) - bandStart(b.bucket))
          if (list.length === 0) return null
          return (
            <div key={side}>
              <div className="flex items-center gap-2 border-b border-hair bg-white/[0.02] px-4 py-1.5">
                <span className={clsx('h-2.5 w-[3px] rounded-full', side === 'under' ? 'bg-mint' : 'bg-coral')} />
                <span className="text-[11.5px] font-semibold text-slate-200">{sideName(kind, side)}</span>
              </div>
              {list.map((r) => {
                const few = r.n < TOO_FEW
                const thin = r.n < THIN
                const beat = r.win_rate >= r.price / 100
                return (
                  <div
                    key={`${side}-${r.bucket}`}
                    className={clsx(GRID, 'border-b border-hair px-4 py-2 last:border-0', few && 'opacity-45')}
                    title={few ? 'Too few settled markets to read anything into this row' : undefined}
                  >
                    <span className="num text-[12px] text-slate-300">
                      bought at <span className="font-semibold text-slate-100">{r.bucket}¢</span>
                    </span>
                    <span className="num text-right text-[11.5px] text-mute">{r.n.toLocaleString()}</span>
                    <span className="num text-right text-[11.5px] text-slate-300">{cents(r.price)}</span>
                    <span className="num text-right text-[11.5px] font-semibold text-slate-100">{few ? '—' : pct(r.win_rate, 0)}</span>
                    <span className="num text-right text-[11.5px] text-peri">{pct(r.model, 0)}</span>
                    <div>
                      {few ? (
                        <span className="text-[10.5px] text-dim">too few</span>
                      ) : (
                        <Meter value={r.win_rate} marker={r.price / 100} tone={thin ? '#5d6577' : beat ? '#3ddc97' : '#ff6b6b'} height={5} />
                      )}
                    </div>
                    <span
                      className={clsx('num text-right text-[11.5px] font-semibold', few ? 'text-dim' : thin ? 'text-mute' : pnlColor(r.ret))}
                      title={thin && !few ? `Only ${r.n} settled: treat as a hint, not a result` : undefined}
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
        title="You have not traded a quarter market yet"
        body="Pick a game on the Desk, choose Q1 to Q4 above the ladder, and place a total or a spread. Your results are kept here by quarter and market, and the agent keeps a record of each one."
        className="!py-7"
      />
    )
  }
  const order = (s: Segment) => ['q1', 'q2', 'q3', 'q4'].indexOf(s)
  const sorted = [...rows].sort((a, b) => order(a.segment) - order(b.segment) || a.kind.localeCompare(b.kind))
  return (
    <table className="w-full text-left">
      <thead>
        <tr className="border-y border-hair bg-white/[0.015] text-[9.5px] font-semibold uppercase tracking-wider text-dim">
          <th className="px-4 py-1.5">Quarter</th>
          <th className="px-2 py-1.5">Market</th>
          <th className="px-2 py-1.5 text-right">Trades</th>
          <th className="px-2 py-1.5 text-right">Record</th>
          <th className="px-4 py-1.5 text-right">P&amp;L</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => (
          <tr key={`${r.segment}-${r.kind}`} className="border-b border-hair last:border-0">
            <td className="px-4 py-2 text-[12px] font-semibold text-slate-100">{segmentLabel(r.segment)}</td>
            <td className="px-2 py-2 text-[12px] capitalize text-slate-300">{r.kind}</td>
            <td className="num px-2 py-2 text-right text-[12px] text-mute">{r.n}</td>
            <td className="num px-2 py-2 text-right text-[12px] text-slate-300">
              {r.wins}–{Math.max(0, r.n - r.wins)}
            </td>
            <td className={clsx('num px-4 py-2 text-right text-[12px] font-semibold', pnlColor(r.pnl))}>{money(r.pnl, { sign: true })}</td>
          </tr>
        ))}
      </tbody>
    </table>
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
    <Card className="overflow-hidden">
      <div className="p-4 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <Binoculars size={15} className="text-peri" />
          <h3 className="text-sm font-semibold text-slate-100">Quarter markets</h3>
          <Badge tone="peri">
            <Eye size={10} /> Watching, not trading
          </Badge>
        </div>
        <p className="mt-2 max-w-3xl text-[12px] leading-relaxed text-mute">
          The agent records every quarter total and spread price shortly after each quarter starts and again with about six
          minutes left, then scores them when the quarter ends. It places no orders of its own in these markets. This is the
          evidence to look at before ever letting it trade them: which prices actually paid, and whether the model saw it
          coming.
        </p>
        <div className="mt-3 grid grid-cols-3 gap-3">
          <Tile label="Markets recorded" value={q.observations.toLocaleString()} sub="price snapshots taken" />
          <Tile label="Settled" value={q.settled.toLocaleString()} sub="scored against the result" />
          <Tile label="Games" value={q.games.toLocaleString()} sub="with at least one quarter watched" />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-hair px-4 py-2.5">
        <span className="label mr-1">Shadow book</span>
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
          title="Nothing scored yet"
          body="This fills in as real quarters finish. Each one adds a few dozen price snapshots, so a slate of games is enough to start seeing a pattern and a couple of weeks to start trusting one."
        />
      ) : rows.length === 0 ? (
        <Empty
          icon={<Binoculars size={18} />}
          title={`No ${quarter === 'all' ? '' : `${segmentLabel(quarter)} `}${kind} markets scored at this checkpoint yet`}
          body="Try another quarter, market or checkpoint. The book only shows what has actually settled."
          className="!py-8"
        />
      ) : (
        <>
          <BookTable rows={rows} kind={kind} />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-hair px-4 py-2 text-[10.5px] text-dim">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-[2px] bg-white/80" /> the price paid
            </span>
            <span>Bar = how often that side won. Past the tick means it paid better than its price.</span>
            <span className="ml-auto">Returns are after fees. Faint rows have too few results to mean anything.</span>
          </div>
        </>
      )}

      <div className="border-t border-hair">
        <div className="px-4 pb-2 pt-3">
          <h4 className="label">Your quarter trades</h4>
        </div>
        <YourTrades rows={q.your_trades ?? []} />
      </div>
    </Card>
  )
}
