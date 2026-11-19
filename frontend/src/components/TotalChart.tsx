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
import { fixed, mmss, periodLabel } from '../format'
import { marginText, quarterNumber, spreadWinZone } from '../lib'
import type { Game, MarketKind, Position, QuarterPoint, Segment, TimelinePoint } from '../types'
import { Card, Empty, Segmented, Skeleton } from './ui'

type View = 'finish' | 'game'

const Q_SECONDS = 720

/** One point on the chart, whatever it measures: the game total, a quarter total, or a quarter margin. */
interface Row {
  t: number
  actual: number
  projected: number
  lo: number
  hi: number
  line: number | null
  band: [number, number]
}

interface Mark {
  key: number
  y: number
  label: string
  color: string
}

function gameElapsedLabel(t: number) {
  if (t >= 2880) {
    const ot = t - 2880
    const n = Math.floor(ot / 300) + 1
    return `${n > 1 ? `${n}OT` : 'OT'} ${mmss(300 - (ot % 300))}`
  }
  const q = Math.min(4, Math.floor(t / Q_SECONDS) + 1)
  return `${periodLabel(q)} ${mmss(Q_SECONDS - (t - (q - 1) * Q_SECONDS))}`
}

function ChartTooltip({
  active,
  payload,
  when,
  say,
  actualLabel,
}: {
  active?: boolean
  payload?: { payload: Row }[]
  when: (t: number) => string
  say: (v: number) => string
  actualLabel: string
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-xl border border-hair2 bg-ink-800/95 px-3 py-2 shadow-lift backdrop-blur">
      <div className="num mb-1.5 text-[10.5px] font-semibold text-mute">{when(p.t)}</div>
      <div className="space-y-1 text-[11px]">
        <Row2 color="#8a8c94" label={actualLabel} value={say(p.actual)} />
        <Row2 color="#f4f4f5" label="Heading for" value={`${say(p.projected)}  (${say(p.lo)} to ${say(p.hi)})`} />
        {p.line != null && <Row2 color="#e6a93c" label="The line" value={say(p.line)} />}
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

/**
 * How a market's number has moved: where it was, where the model thought it was heading, and
 * the line. For the full game it is the total over 48 minutes; for a quarter it is that
 * quarter's total, or its margin (home minus away) on the spread tab.
 */
export default function TotalChart({
  game,
  segment = 'game',
  kind = 'total',
  timeline,
  quarterTimeline,
  positions,
  loading,
}: {
  game: Game
  segment?: Segment
  kind?: MarketKind
  timeline: TimelinePoint[] | null
  quarterTimeline?: QuarterPoint[] | null
  positions: Position[]
  loading: boolean
}) {
  const [view, setView] = useState<View>('finish')
  const isGame = segment === 'game'
  const isSpread = !isGame && kind === 'spread'
  const qLabel = isGame ? '' : periodLabel(quarterNumber(segment))
  const quarter = isGame ? undefined : game.quarters?.[quarterNumber(segment) - 1]

  const rows = useMemo<Row[]>(() => {
    if (isGame) {
      return (timeline ?? []).map((p) => ({
        t: p.t,
        actual: p.total,
        projected: p.projected,
        lo: p.lo,
        hi: p.hi,
        line: p.line,
        band: [p.lo, p.hi],
      }))
    }
    return (quarterTimeline ?? []).map((p) =>
      isSpread
        ? { t: p.t, actual: p.margin, projected: p.m_projected, lo: p.m_lo, hi: p.m_hi, line: p.m_line, band: [p.m_lo, p.m_hi] }
        : { t: p.t, actual: p.total, projected: p.projected, lo: p.lo, hi: p.hi, line: p.line, band: [p.lo, p.hi] },
    )
  }, [isGame, isSpread, timeline, quarterTimeline])

  const say = (v: number) => (isSpread ? marginText(v, game.home.abbr, game.away.abbr, true) : fixed(v, isGame || Number.isInteger(v) ? 0 : 1))

  // Bets you hold on this market, drawn as lines across the chart.
  const marks = useMemo<Mark[]>(() => {
    const seen = new Set<number>()
    const out: Mark[] = []
    for (const p of positions) {
      if ((p.segment ?? 'game') !== segment || (p.kind ?? 'total') !== (isGame ? 'total' : kind)) continue
      if (isSpread) {
        const y = spreadWinZone(p, p.side, game.home.abbr).threshold
        if (seen.has(y)) continue
        seen.add(y)
        out.push({ key: p.id, y, label: p.label.replace(/^Q\d\s+/, ''), color: '#19c37d' })
      } else {
        if (seen.has(p.strike)) continue
        seen.add(p.strike)
        const under = p.side === 'under'
        out.push({ key: p.id, y: p.strike, label: `${under ? 'U' : 'O'} ${p.strike}`, color: under ? '#19c37d' : '#f2594b' })
      }
    }
    return out
  }, [positions, segment, kind, isGame, isSpread, game.home.abbr])

  const xMax = useMemo(() => {
    if (!isGame) return Q_SECONDS
    const lastT = rows.length ? rows[rows.length - 1].t : 0
    return Math.max(2880, Math.ceil(lastT / 300) * 300)
  }, [isGame, rows])

  const yDomain = useMemo<[number, number]>(() => {
    if (!rows.length) return isGame ? [180, 260] : isSpread ? [-10, 10] : [40, 70]
    if (isSpread) {
      // A margin: keep the tie on screen so it is clear which side of it things are.
      const vals = [0, ...marks.map((m) => m.y)]
      for (const r of rows) {
        vals.push(r.lo, r.hi, r.projected)
        if (r.line != null) vals.push(r.line)
        if (view === 'game') vals.push(r.actual)
      }
      const lo = Math.min(...vals) - 1
      const hi = Math.max(...vals) + 1
      const step = marginStep(hi - lo)
      return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step]
    }
    if (view === 'finish') {
      // Keep the focus on where it is heading; ignore the wide early band.
      const tail = rows.slice(Math.floor(rows.length * 0.35))
      const focus: number[] = marks.map((m) => m.y)
      for (const r of tail) {
        focus.push(r.lo, r.hi)
        if (r.line != null) focus.push(r.line)
      }
      const lo = Math.min(...focus)
      const hi = Math.max(...focus)
      const pad = Math.max(isGame ? 4 : 2, (hi - lo) * 0.18)
      return [Math.floor(lo - pad), Math.ceil(hi + pad)]
    }
    const vals = marks.map((m) => m.y)
    for (const r of rows) vals.push(r.hi, r.projected, r.actual, ...(r.line != null ? [r.line] : []))
    const step = isGame ? 10 : 5
    return [0, Math.ceil((Math.max(...vals) + (isGame ? 8 : 3)) / step) * step]
  }, [rows, marks, view, isGame, isSpread])

  const ticks = useMemo(() => {
    if (!isGame) return [0, 180, 360, 540, 720]
    const t = [0, 720, 1440, 2160, 2880]
    for (let x = 3180; x <= xMax; x += 300) t.push(x)
    return t
  }, [isGame, xMax])

  // Margins get round ticks that always include the tie.
  const yTicks = useMemo(() => {
    if (!isSpread) return undefined
    const step = marginStep(yDomain[1] - yDomain[0])
    const out: number[] = []
    for (let v = Math.ceil(yDomain[0] / step) * step; v <= yDomain[1]; v += step) out.push(v)
    return out
  }, [isSpread, yDomain])

  const xTick = (t: number) =>
    isGame ? (t >= 2880 ? (t === 2880 ? 'End' : 'OT') : `Q${t / 720 + 1}`) : t === Q_SECONDS ? 'End' : mmss(Q_SECONDS - t)
  const when = (t: number) => (isGame ? gameElapsedLabel(t) : `${qLabel} ${mmss(Q_SECONDS - t)}`)
  const yTick = (v: number) => {
    if (!isSpread) return String(v)
    if (v === 0) return 'Tied'
    return `${v > 0 ? game.home.abbr : game.away.abbr} by ${Math.abs(v)}`
  }

  const title = isGame ? 'How the total has moved' : isSpread ? `How the ${qLabel} margin has moved` : `How the ${qLabel} total has moved`
  const actualLabel = isSpread ? 'Margin' : isGame ? 'Total' : 'Points'
  const views = [
    { value: 'finish' as View, label: 'Where it is heading' },
    { value: 'game' as View, label: isSpread ? 'Actual margin' : 'Points scored' },
  ]

  let empty: { title: string; body: string } | null = null
  if (rows.length < 2) {
    if (isGame) {
      empty = { title: game.state === 'pre' ? 'Chart starts at tip-off' : 'Collecting data', body: 'The projection, the line and your bets are plotted here as the game unfolds.' }
    } else if (!quarter || quarter.status === 'upcoming') {
      empty = { title: `Chart starts when ${qLabel} begins`, body: `The projection, Kalshi's line and your bets are plotted here as ${qLabel} unfolds.` }
    } else if (quarter.status === 'final' && rows.length === 0) {
      empty = { title: `Nothing recorded for ${qLabel}`, body: 'It ended before Courtside started watching this game.' }
    } else {
      empty = { title: 'Collecting data', body: `The first points appear a few seconds into ${qLabel}.` }
    }
  }

  return (
    <Card className="p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-4">
          <h3 className="text-sm font-medium text-white">{title}</h3>
          <div className="hidden items-center gap-3 text-xs text-mute sm:flex">
            {view === 'game' && <Legend color="#8a8c94" label={isSpread ? 'Margin' : 'Actual'} />}
            <Legend color="#f4f4f5" label="Heading for" dashed={view === 'game'} />
            <Legend color="#e6a93c" label="The line" />
            {marks.length > 0 && <Legend color="#19c37d" label="Your bets" dashed />}
          </div>
        </div>
        <Segmented<View> id={`chart-view-${segment}-${kind}`} value={view} onChange={setView} options={views} />
      </div>

      <div className="h-[250px]">
        {loading && rows.length === 0 ? (
          <Skeleton className="h-full w-full !rounded-xl" />
        ) : empty ? (
          <Empty icon={<LineIcon size={18} />} title={empty.title} body={empty.body} />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 6, right: isSpread ? 12 : 44, bottom: 0, left: isSpread ? -4 : -14 }}>
              <defs>
                <linearGradient id="bandFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#f4f4f5" stopOpacity={0.22} />
                  <stop offset="100%" stopColor="#f4f4f5" stopOpacity={0.06} />
                </linearGradient>
                <linearGradient id="totalFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#8a8c94" stopOpacity={0.12} />
                  <stop offset="100%" stopColor="#8a8c94" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="t" type="number" domain={[0, xMax]} ticks={ticks} tickFormatter={xTick} axisLine={false} tickLine={false} dy={4} />
              <YAxis domain={yDomain} axisLine={false} tickLine={false} width={isSpread ? 70 : 48} allowDecimals={false} ticks={yTicks} interval={0} tickFormatter={yTick} />
              <Tooltip
                content={<ChartTooltip when={when} say={say} actualLabel={actualLabel} />}
                cursor={{ stroke: 'rgba(255,255,255,0.14)', strokeDasharray: '3 3' }}
                isAnimationActive={false}
              />
              {ticks.slice(1).map((t) => (
                <ReferenceLine key={t} x={t} stroke="rgba(255,255,255,0.05)" />
              ))}
              {isSpread && <ReferenceLine y={0} stroke="rgba(255,255,255,0.22)" />}
              <Area dataKey="band" stroke="none" fill="url(#bandFill)" isAnimationActive={false} activeDot={false} connectNulls />
              {view === 'game' &&
                (isSpread ? (
                  <Line
                    dataKey="actual"
                    type="stepAfter"
                    stroke="#8a8c94"
                    strokeWidth={1.8}
                    dot={false}
                    isAnimationActive={false}
                    activeDot={{ r: 3, fill: '#8a8c94', stroke: '#0b0b0c' }}
                  />
                ) : (
                  <Area
                    dataKey="actual"
                    stroke="#8a8c94"
                    strokeWidth={1.8}
                    fill="url(#totalFill)"
                    dot={false}
                    isAnimationActive={false}
                    activeDot={{ r: 3, fill: '#8a8c94', stroke: '#0b0b0c' }}
                  />
                ))}
              <Line
                dataKey="line"
                type="stepAfter"
                stroke="#e6a93c"
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
                connectNulls
                activeDot={{ r: 3, fill: '#e6a93c', stroke: '#0b0b0c' }}
              />
              <Line
                dataKey="projected"
                stroke="#f4f4f5"
                strokeWidth={2}
                strokeDasharray={view === 'game' ? '5 4' : undefined}
                dot={false}
                isAnimationActive={false}
                activeDot={{ r: 3.5, fill: '#f4f4f5', stroke: '#0b0b0c' }}
              />
              {marks.map((m) => (
                <ReferenceLine
                  key={m.key}
                  y={m.y}
                  stroke={m.color}
                  strokeDasharray="6 4"
                  strokeWidth={1.2}
                  label={{ value: m.label, position: isSpread ? 'insideTopRight' : 'right', fill: m.color, fontSize: 10 }}
                />
              ))}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  )
}

/** A round tick spacing that gives four to six ticks across a margin range. */
function marginStep(range: number) {
  return [2, 3, 5, 10, 15, 20].find((s) => range / s <= 6) ?? 25
}

function Legend({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block h-0 w-4 border-t-2" style={{ borderColor: color, borderStyle: dashed ? 'dashed' : 'solid' }} />
      {label}
    </span>
  )
}
