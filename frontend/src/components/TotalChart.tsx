import { LineChart as LineIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fixed, periodLabel } from '../format'
import type { Game, Position, TimelinePoint } from '../types'
import { Card, Empty, Segmented, Skeleton } from './ui'

type View = 'finish' | 'game'

function elapsedLabel(t: number) {
  if (t >= 2880) {
    const ot = t - 2880
    const n = Math.floor(ot / 300) + 1
    const left = 300 - (ot % 300)
    return `${n > 1 ? `${n}OT` : 'OT'} ${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, '0')}`
  }
  const q = Math.min(4, Math.floor(t / 720) + 1)
  const left = 720 - (t - (q - 1) * 720)
  return `${periodLabel(q)} ${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, '0')}`
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-xl border border-hair2 bg-ink-800/95 px-3 py-2 shadow-lift backdrop-blur">
      <div className="num mb-1.5 text-[10.5px] font-semibold text-mute">{elapsedLabel(p.t)}</div>
      <div className="space-y-1 text-[11px]">
        <Row2 color="#e6e9f2" label="Total" value={fixed(p.total, 0)} />
        <Row2 color="#8b9cff" label="Projected" value={`${fixed(p.projected, 1)}  (${fixed(p.lo, 0)}–${fixed(p.hi, 0)})`} />
        {p.line != null && <Row2 color="#f5b74e" label="Book line" value={fixed(p.line, 1)} />}
      </div>
    </div>
  )
}

function Row2({ color, label, value }: { color: string; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-5">
      <span className="flex items-center gap-1.5 text-mute">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
        {label}
      </span>
      <span className="num font-semibold text-slate-100">{value}</span>
    </div>
  )
}

interface Row extends TimelinePoint {
  band: [number, number]
}

export default function TotalChart({
  game,
  timeline,
  positions,
  loading,
}: {
  game: Game
  timeline: TimelinePoint[] | null
  positions: Position[]
  loading: boolean
}) {
  const [view, setView] = useState<View>('finish')

  const rows = useMemo<Row[]>(
    () => (timeline ?? []).map((p) => ({ ...p, band: [p.lo, p.hi] as [number, number] })),
    [timeline],
  )

  const strikes = useMemo(() => {
    const seen = new Map<number, Position>()
    for (const p of positions) if (!seen.has(p.strike)) seen.set(p.strike, p)
    return [...seen.values()]
  }, [positions])

  const { yDomain, xMax } = useMemo(() => {
    const lastT = rows.length ? rows[rows.length - 1].t : 0
    const xMax = Math.max(2880, Math.ceil(lastT / 300) * 300)
    if (!rows.length) return { yDomain: [180, 260] as [number, number], xMax }
    const vals: number[] = []
    for (const r of rows) {
      vals.push(r.lo, r.hi, r.projected)
      if (r.line != null) vals.push(r.line)
      if (view === 'game') vals.push(r.total)
    }
    for (const s of strikes) vals.push(s.strike)
    if (view === 'finish') {
      // Keep the focus on where the game is heading; ignore the wide early band.
      const tail = rows.slice(Math.floor(rows.length * 0.35))
      const focus: number[] = []
      for (const r of tail) {
        focus.push(r.lo, r.hi)
        if (r.line != null) focus.push(r.line)
      }
      for (const s of strikes) focus.push(s.strike)
      const lo = Math.min(...focus)
      const hi = Math.max(...focus)
      const pad = Math.max(4, (hi - lo) * 0.18)
      return { yDomain: [Math.floor(lo - pad), Math.ceil(hi + pad)] as [number, number], xMax }
    }
    const hi = Math.max(...vals)
    return { yDomain: [0, Math.ceil((hi + 8) / 10) * 10] as [number, number], xMax }
  }, [rows, strikes, view])

  const quarterTicks = useMemo(() => {
    const ticks = [0, 720, 1440, 2160, 2880]
    for (let t = 3180; t <= xMax; t += 300) ticks.push(t)
    return ticks
  }, [xMax])

  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-4">
          <h3 className="label">Total points</h3>
          <div className="hidden items-center gap-3 text-[10.5px] text-mute sm:flex">
            {view === 'game' && <Legend color="#e6e9f2" label="Actual" />}
            <Legend color="#8b9cff" label="Projected final" dashed={view === 'game'} />
            <Legend color="#f5b74e" label="Book line" />
            {strikes.length > 0 && <Legend color="#3ddc97" label="Your strikes" dashed />}
          </div>
        </div>
        <Segmented<View>
          id="chart-view"
          value={view}
          onChange={setView}
          options={[
            { value: 'finish', label: 'Where it lands' },
            { value: 'game', label: 'Full game' },
          ]}
        />
      </div>

      <div className="h-[250px]">
        {loading && rows.length === 0 ? (
          <Skeleton className="h-full w-full !rounded-xl" />
        ) : rows.length < 2 ? (
          <Empty
            icon={<LineIcon size={18} />}
            title={game.state === 'pre' ? 'Chart starts at tip-off' : 'Collecting data'}
            body="The projection, the book line and your strikes are plotted here as the game unfolds."
          />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 6, right: 44, bottom: 0, left: -14 }}>
              <defs>
                <linearGradient id="bandFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#8b9cff" stopOpacity={0.22} />
                  <stop offset="100%" stopColor="#8b9cff" stopOpacity={0.06} />
                </linearGradient>
                <linearGradient id="totalFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#e6e9f2" stopOpacity={0.12} />
                  <stop offset="100%" stopColor="#e6e9f2" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                domain={[0, xMax]}
                ticks={quarterTicks}
                tickFormatter={(t: number) => (t >= 2880 ? (t === 2880 ? 'End' : 'OT') : `Q${t / 720 + 1}`)}
                axisLine={false}
                tickLine={false}
                dy={4}
              />
              <YAxis domain={yDomain} axisLine={false} tickLine={false} width={48} allowDecimals={false} />
              <Tooltip
                content={<ChartTooltip />}
                cursor={{ stroke: 'rgba(255,255,255,0.14)', strokeDasharray: '3 3' }}
                isAnimationActive={false}
              />
              {[720, 1440, 2160, 2880].map((t) => (
                <ReferenceLine key={t} x={t} stroke="rgba(255,255,255,0.05)" />
              ))}
              <Area
                dataKey="band"
                stroke="none"
                fill="url(#bandFill)"
                isAnimationActive={false}
                activeDot={false}
                connectNulls
              />
              {view === 'game' && (
                <Area
                  dataKey="total"
                  stroke="#e6e9f2"
                  strokeWidth={1.8}
                  fill="url(#totalFill)"
                  dot={false}
                  isAnimationActive={false}
                  activeDot={{ r: 3, fill: '#e6e9f2', stroke: '#090b10' }}
                />
              )}
              <Line
                dataKey="line"
                type="stepAfter"
                stroke="#f5b74e"
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
                connectNulls
                activeDot={{ r: 3, fill: '#f5b74e', stroke: '#090b10' }}
              />
              <Line
                dataKey="projected"
                stroke="#8b9cff"
                strokeWidth={2}
                strokeDasharray={view === 'game' ? '5 4' : undefined}
                dot={false}
                isAnimationActive={false}
                activeDot={{ r: 3.5, fill: '#8b9cff', stroke: '#090b10' }}
              />
              {strikes.map((p) => (
                <ReferenceLine
                  key={p.id}
                  y={p.strike}
                  stroke={p.side === 'under' ? '#3ddc97' : '#ff6b6b'}
                  strokeDasharray="6 4"
                  strokeWidth={1.2}
                  label={{
                    value: `${p.side === 'under' ? 'U' : 'O'} ${p.strike}`,
                    position: 'right',
                    fill: p.side === 'under' ? '#3ddc97' : '#ff6b6b',
                    fontSize: 10,
                    fontFamily: 'JetBrains Mono, monospace',
                  }}
                />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  )
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="inline-block h-0 w-4 border-t-2"
        style={{ borderColor: color, borderStyle: dashed ? 'dashed' : 'solid' }}
      />
      {label}
    </span>
  )
}
