import { AnimatePresence, motion } from 'framer-motion'
import clsx from 'clsx'
import { Grid3x3, LogOut, Play, Target } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../../api'
import { Badge, Button, Card, Empty, Meter, Segmented, Skeleton, Slider, Stat } from '../../components/ui'
import { money, pct, pnlColor, signedPct } from '../../format'
import { useStore } from '../../store'
import type { Arm, ExitArm, LearningState, TrainResult } from '../../types'
import QuarterBook from './QuarterBook'

const GREEN = '#19c37d'
const RED = '#f2594b'

/* ───────────────────────── Headline numbers ───────────────────────── */

function Totals({ t }: { t: LearningState['totals'] }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Card className="p-5">
        <Stat
          label="Trades"
          sub={t.sim_episodes > 0 ? `plus ${t.sim_episodes.toLocaleString()} practice games in the gym` : 'finished trades it has learned from'}
        >
          {t.trades.toLocaleString()}
        </Stat>
      </Card>
      <Card className="p-5">
        <Stat label="Win rate" sub="of finished trades">
          {t.trades ? pct(t.win_rate, 1) : '—'}
        </Stat>
      </Card>
      <Card className="p-5">
        <Stat
          label="Average result per trade"
          sub={
            t.trades
              ? `wins average ${money(t.avg_win, { sign: true })}, losses ${money(-Math.abs(t.avg_loss), { sign: true })}`
              : 'wins and losses averaged together'
          }
        >
          <span className={pnlColor(t.expectancy)}>{t.trades ? money(t.expectancy, { sign: true }) : '—'}</span>
        </Stat>
      </Card>
      <Card className="p-5">
        <Stat label="Selling early" sub="compared with holding to the end">
          <span className="text-mint">{t.exits_saved}</span>
          <span className="mx-1.5 text-sm font-normal text-mute">helped</span>
          <span className="text-gold">{t.exits_shaken}</span>
          <span className="ml-1.5 text-sm font-normal text-mute">hurt</span>
        </Stat>
      </Card>
    </div>
  )
}

/* ───────────────────────── Where the play works ───────────────────────── */

interface Cell {
  buffer: string
  time: string
  arms: Arm[]
  n: number
  wins: number
  simN: number
  pWin: number
  breakeven: number
  meanReturn: number
}

const MARGIN_WORDS: Record<string, string> = { close: 'Close games', mid: 'In between', blowout: 'Blowouts' }
const marginWord = (m: string) => MARGIN_WORDS[m] ?? m

function uniq(list: string[]) {
  return [...new Set(list)]
}

function aggregate(arms: Arm[], buffer: string, time: string): Cell | null {
  if (arms.length === 0) return null
  let w = 0
  let p = 0
  let be = 0
  let n = 0
  let wins = 0
  let simN = 0
  let ret = 0
  for (const a of arms) {
    const weight = a.n + a.sim_n * 0.25 + 1
    w += weight
    p += a.p_win * weight
    be += a.breakeven * weight
    n += a.n
    wins += a.wins
    simN += a.sim_n
    ret += a.mean_return * Math.max(a.n, 0)
  }
  return { buffer, time, arms, n, wins, simN, pWin: p / w, breakeven: be / w, meanReturn: n ? ret / n : 0 }
}

function cellStyle(c: Cell) {
  const delta = c.pWin - c.breakeven
  const strength = Math.min(1, Math.abs(delta) / 0.06)
  const evidence = c.n + c.simN * 0.25
  const fade = evidence <= 0 ? 0.3 : Math.min(1, 0.45 + evidence / 30)
  const alpha = (0.08 + strength * 0.4) * fade
  const rgb = delta >= 0 ? '25,195,125' : '242,89,75'
  return { background: `rgba(${rgb},${alpha.toFixed(3)})` }
}

function LegendSwatch({ rgb, alpha, children }: { rgb: string; alpha: number; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="h-3 w-3 rounded" style={{ background: `rgba(${rgb},${alpha})` }} />
      {children}
    </span>
  )
}

function Heatmap({ arms }: { arms: Arm[] }) {
  const margins = useMemo(() => uniq(arms.map((a) => a.dims.margin)), [arms])
  const [margin, setMargin] = useState<string>('all')
  const [picked, setPicked] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)

  const buffers = useMemo(() => uniq(arms.map((a) => a.dims.buffer)), [arms])
  const times = useMemo(() => uniq(arms.map((a) => a.dims.time)), [arms])

  const cells = useMemo(() => {
    const m = new Map<string, Cell>()
    for (const b of buffers)
      for (const t of times) {
        const list = arms.filter(
          (a) => a.dims.buffer === b && a.dims.time === t && (margin === 'all' || a.dims.margin === margin),
        )
        const c = aggregate(list, b, t)
        if (c) m.set(`${b}|${t}`, c)
      }
    return m
  }, [arms, buffers, times, margin])

  const activeKey = hover ?? picked
  const active = activeKey ? cells.get(activeKey) ?? null : null

  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="h-section">Where the play works</h3>
          <p className="hint mt-1 max-w-2xl">
            Each box is a situation: how much cushion the strike had above the line, and how much time was left. The number is
            how often the agent now expects to win there, next to the win rate it needs just to break even at typical prices.
          </p>
        </div>
        {margins.length > 1 && (
          <Segmented
            id="heat-margin"
            value={margin}
            onChange={setMargin}
            options={[{ value: 'all', label: 'All games' }, ...margins.map((m) => ({ value: m, label: marginWord(m) }))]}
          />
        )}
      </div>

      {arms.length === 0 ? (
        <Card className="mt-3 py-10">
          <Empty
            icon={<Grid3x3 size={18} />}
            title="Nothing learned yet"
            body="This fills in as the agent trades. You can also run the practice gym further down to give it a head start in practice mode."
          />
        </Card>
      ) : (
        <Card className="mt-3 p-5">
          <div className="overflow-x-auto">
            <div
              className="grid min-w-[520px] gap-1.5"
              style={{ gridTemplateColumns: `120px repeat(${times.length}, minmax(88px, 1fr))` }}
            >
              <div className="flex items-end pb-1 text-xs text-dim">Cushion ↓ · Minutes left →</div>
              {times.map((t) => (
                <div key={t} className="num pb-1 text-center text-xs font-medium text-mute">
                  {t}
                </div>
              ))}
              {buffers.map((b) => (
                <FragmentRow key={b}>
                  <div className="num flex items-center text-[13px] font-medium text-slate-200">{b} pts</div>
                  {times.map((t) => {
                    const key = `${b}|${t}`
                    const c = cells.get(key)
                    if (!c) return <div key={key} className="h-[64px] rounded-xl bg-white/[0.02]" />
                    const isActive = activeKey === key
                    return (
                      <button
                        key={key}
                        type="button"
                        onMouseEnter={() => setHover(key)}
                        onMouseLeave={() => setHover(null)}
                        onFocus={() => setHover(key)}
                        onBlur={() => setHover(null)}
                        onClick={() => setPicked((p) => (p === key ? null : key))}
                        className={clsx(
                          'flex h-[64px] flex-col items-center justify-center rounded-xl transition-shadow',
                          isActive && 'ring-2 ring-white/60',
                        )}
                        style={cellStyle(c)}
                      >
                        <span className="num text-base font-semibold leading-none text-white">{pct(c.pWin, 0)}</span>
                        <span className="num mt-1 text-[11px] text-white/60">needs {pct(c.breakeven, 0)}</span>
                      </button>
                    )
                  })}
                </FragmentRow>
              ))}
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-mute">
            <LegendSwatch rgb="25,195,125" alpha={0.45}>
              Wins often enough to pay
            </LegendSwatch>
            <LegendSwatch rgb="242,89,75" alpha={0.45}>
              Does not win often enough
            </LegendSwatch>
            <LegendSwatch rgb="255,255,255" alpha={0.08}>
              Faint: too few trades to say
            </LegendSwatch>
          </div>

          <div className="mt-4 min-h-[72px] rounded-xl bg-ink-800 px-4 py-3">
            <AnimatePresence mode="wait" initial={false}>
              {active ? (
                <motion.div key={activeKey} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }}>
                  <p className="text-[13px] leading-relaxed text-slate-200">
                    <span className="font-semibold text-white">
                      {active.buffer} points of cushion with {active.time} minutes left
                      {margin !== 'all' && `, ${marginWord(margin).toLowerCase()}`}:
                    </span>{' '}
                    {active.n > 0 ? (
                      <>
                        won {active.wins} of {active.n} {active.n === 1 ? 'trade' : 'trades'}, returning{' '}
                        <span className={clsx('num font-semibold', pnlColor(active.meanReturn))}>{signedPct(active.meanReturn, 1)}</span> per
                        dollar put down.
                      </>
                    ) : (
                      'no real trades here yet, so this is the model’s starting guess.'
                    )}{' '}
                    It needs to win {pct(active.breakeven, 1)} of the time to break even.
                    {active.simN > 0 && ` Also seen in ${active.simN.toLocaleString()} practice trades.`}
                  </p>
                  {margin === 'all' && active.arms.length > 1 && (
                    <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-mute">
                      {active.arms.map((a) => (
                        <span key={a.key} className="num" title={`Started at ${pct(a.prior, 1)} before any results`}>
                          {marginWord(a.dims.margin)}: <span className="font-medium text-slate-200">{pct(a.p_win, 0)}</span>
                          <span className="text-dim"> · {a.n} {a.n === 1 ? 'trade' : 'trades'}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </motion.div>
              ) : (
                <motion.p key="hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="hint flex min-h-[48px] items-center">
                  Point at a box to see its record and what it has returned.
                </motion.p>
              )}
            </AnimatePresence>
          </div>
        </Card>
      )}
    </section>
  )
}

function FragmentRow({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}

/* ───────────────────────── How quickly it sells ───────────────────────── */

function ExitStyles({ arms }: { arms: ExitArm[] }) {
  return (
    <section>
      <h3 className="h-section">How quickly it sells</h3>
      <p className="hint mt-1">
        Each trade gets one of three selling styles. Once the game ends, every early sale is compared with what holding would
        have paid, and the styles that do better get used more.
      </p>
      <Card className="mt-3 px-5">
        {arms.length === 0 ? (
          <Empty icon={<LogOut size={18} />} title="No early sales to judge yet" className="!py-8" />
        ) : (
          arms.map((a) => (
            <div key={a.key} className="flex items-start gap-4 border-b border-hair py-4 last:border-b-0">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-white">{a.label}</div>
                <div className="hint mt-0.5">{a.description}</div>
                <div className="mt-1.5 text-xs text-dim">
                  <span className="text-mint">{a.saved} helped</span> · <span className="text-gold">{a.shaken_out} hurt</span> · used
                  for {pct(a.share)} of new trades
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div className={clsx('num text-base font-semibold', a.n ? pnlColor(a.mean_return) : 'text-dim')}>
                  {a.n ? signedPct(a.mean_return, 1) : '—'}
                </div>
                <div className="text-xs text-dim">
                  per dollar · {a.n} {a.n === 1 ? 'trade' : 'trades'}
                </div>
              </div>
            </div>
          ))
        )}
      </Card>
    </section>
  )
}

/* ───────────────────────── Is the model honest? ───────────────────────── */

function Calibration({ rows }: { rows: LearningState['calibration'] }) {
  const used = rows.filter((r) => r.n > 0)
  const lo = used.length ? Math.max(0, Math.floor((Math.min(...used.map((r) => Math.min(r.predicted, r.actual))) - 0.04) * 20) / 20) : 0
  const scale = (v: number) => Math.min(1, Math.max(0, (v - lo) / (1 - lo || 1)))
  return (
    <section>
      <h3 className="h-section">Is the model honest?</h3>
      <p className="hint mt-1">
        When it says a trade wins 95% of the time, does it? The bar is how often those trades really won; the white tick is
        what it predicted.
      </p>
      <Card className="mt-3 p-5">
        {used.length === 0 ? (
          <Empty icon={<Target size={18} />} title="Not enough finished trades yet" className="!py-6" />
        ) : (
          <div className="space-y-3.5">
            {used.map((r) => {
              const gap = r.actual - r.predicted
              const ok = gap >= -0.015
              return (
                <div key={r.bucket} className="grid grid-cols-[84px_1fr_auto] items-center gap-3">
                  <span className="num text-[13px] text-slate-200" title="What the model said the chance was">
                    said {r.bucket}
                  </span>
                  <Meter value={scale(r.actual)} marker={scale(r.predicted)} tone={ok ? GREEN : RED} height={8} />
                  <span className="num text-right text-[13px]">
                    <span className="font-semibold text-white">won {pct(r.actual, 0)}</span>
                    <span className="ml-1.5 text-dim">
                      of {r.n} {r.n === 1 ? 'trade' : 'trades'}
                    </span>
                  </span>
                </div>
              )
            })}
            <div className="num flex justify-between pl-[96px] pr-[150px] text-[11px] text-dim">
              <span>{pct(lo)}</span>
              <span>100%</span>
            </div>
          </div>
        )}
      </Card>
    </section>
  )
}

/* ───────────────────────── Practice gym ───────────────────────── */

function Gym({ onDone }: { onDone: () => void }) {
  const toast = useStore((s) => s.toast)
  const [episodes, setEpisodes] = useState(100)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<TrainResult | null>(null)

  const run = async () => {
    setBusy(true)
    try {
      const r = await api.train(episodes)
      setResult(r)
      onDone()
      toast({
        level: 'success',
        title: `Practice finished: ${r.episodes} games`,
        body: `${r.trades} practice trades, ${pct(r.win_rate, 1)} won, ${r.lessons} new ${r.lessons === 1 ? 'lesson' : 'lessons'}.`,
      })
    } catch (e) {
      toast({ level: 'error', title: 'Practice did not run', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <div className="flex items-center gap-2">
        <h3 className="h-section">Practice gym</h3>
        <Badge tone="gold">Practice</Badge>
      </div>
      <p className="hint mt-1 max-w-2xl">
        Plays made-up fourth quarters at full speed so the agent can rehearse your rules. It only shapes how it trades in
        practice mode; on real games it learns from real results alone.
      </p>
      <Card className="mt-3 p-5">
        <div className="flex flex-wrap items-end gap-5">
          <div className="min-w-[220px] flex-1">
            <div className="flex items-baseline justify-between">
              <span className="text-sm font-medium text-slate-200">Games to play</span>
              <span className="num text-sm font-semibold text-white">{episodes}</span>
            </div>
            <div className="mt-1.5">
              <Slider value={episodes} min={10} max={500} step={10} onChange={setEpisodes} tone="#f4f4f5" disabled={busy} ariaLabel="Games to play" />
            </div>
          </div>
          <Button variant="primary" size="md" onClick={run} loading={busy} className="shrink-0">
            {!busy && <Play size={15} />}
            {busy ? 'Playing…' : 'Run practice'}
          </Button>
        </div>
        {result && !busy && (
          <div className="mt-5 grid grid-cols-2 gap-4 border-t border-hair pt-4 sm:grid-cols-5">
            <Stat label="Games">{result.episodes.toLocaleString()}</Stat>
            <Stat label="Trades">{result.trades.toLocaleString()}</Stat>
            <Stat label="Won">{result.trades ? pct(result.win_rate, 1) : '—'}</Stat>
            <Stat label="Practice result">
              <span className={pnlColor(result.pnl)}>{money(result.pnl, { sign: true, decimals: 0 })}</span>
            </Stat>
            <Stat label="New lessons">{result.lessons}</Stat>
          </div>
        )}
      </Card>
    </section>
  )
}

/* ───────────────────────── Tab ───────────────────────── */

export default function LearningTab() {
  const tradeTick = useStore((s) => s.tradeTick)
  const connected = useStore((s) => s.connected)
  const [state, setState] = useState<LearningState | null>(null)
  const [failed, setFailed] = useState(false)

  const load = useCallback(() => {
    api
      .learning()
      .then((l) => {
        if (l && Array.isArray(l.arms)) setState(l)
        setFailed(false)
      })
      .catch(() => setFailed(true))
  }, [])

  useEffect(() => {
    load()
  }, [load, tradeTick, connected])

  if (!state) {
    return failed ? (
      <Card className="py-12">
        <Empty icon={<Grid3x3 size={18} />} title="Learning is unavailable" body="The server did not answer. This fills in once it is running." />
      </Card>
    ) : (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[104px] w-full !rounded-xl2" />
          ))}
        </div>
        <Skeleton className="h-[320px] w-full !rounded-xl2" />
      </div>
    )
  }

  return (
    <div className="space-y-10">
      <Totals t={state.totals} />
      <Heatmap arms={state.arms} />
      <div className="grid items-start gap-8 lg:grid-cols-2">
        <ExitStyles arms={state.exit_arms} />
        <Calibration rows={state.calibration} />
      </div>
      <Gym onDone={load} />
      <QuarterBook data={state.quarters} />
    </div>
  )
}
