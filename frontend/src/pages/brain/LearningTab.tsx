import { AnimatePresence, motion } from 'framer-motion'
import clsx from 'clsx'
import { Dumbbell, FlaskConical, Grid3x3, LogOut, Play, Target } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../../api'
import { Badge, Button, Card, Empty, Meter, SectionTitle, Segmented, Skeleton, Slider } from '../../components/ui'
import { money, pct, pnlColor, signedPct } from '../../format'
import { useStore } from '../../store'
import type { Arm, ExitArm, LearningState, TrainResult } from '../../types'

/* ───────────────────────── Totals ───────────────────────── */

function Totals({ t }: { t: LearningState['totals'] }) {
  const items: { label: string; value: React.ReactNode; sub: string }[] = [
    { label: 'Trades learned from', value: t.trades.toLocaleString(), sub: `${t.sim_episodes.toLocaleString()} simulated games` },
    { label: 'Win rate', value: t.trades ? pct(t.win_rate, 1) : '—', sub: 'of closed trades' },
    {
      label: 'Avg win / avg loss',
      value: (
        <span>
          <span className="text-mint">{money(t.avg_win, { sign: true })}</span>
          <span className="mx-1 text-dim">/</span>
          <span className="text-coral">{money(-Math.abs(t.avg_loss), { sign: true })}</span>
        </span>
      ),
      sub: 'per trade',
    },
    {
      label: 'Expectancy',
      value: <span className={pnlColor(t.expectancy)}>{money(t.expectancy, { sign: true })}</span>,
      sub: 'average result per trade',
    },
    {
      label: 'Early exits',
      value: (
        <span>
          <span className="text-mint">{t.exits_saved}</span>
          <span className="mx-1 text-dim">saved ·</span>
          <span className="text-gold">{t.exits_shaken}</span>
          <span className="ml-1 text-dim">shaken</span>
        </span>
      ),
      sub: 'selling vs holding to the end',
    },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      {items.map((it) => (
        <Card key={it.label} className="p-4">
          <div className="label">{it.label}</div>
          <div className="num mt-2 text-lg font-bold leading-none text-slate-50">{it.value}</div>
          <div className="mt-2 text-[11px] text-dim">{it.sub}</div>
        </Card>
      ))}
    </div>
  )
}

/* ───────────────────────── Heatmap ───────────────────────── */

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
  const fade = evidence <= 0 ? 0.35 : Math.min(1, 0.45 + evidence / 30)
  const alpha = (0.1 + strength * 0.5) * fade
  const rgb = delta >= 0 ? '61,220,151' : '255,107,107'
  return {
    background: `rgba(${rgb},${alpha.toFixed(3)})`,
    borderColor: `rgba(${rgb},${Math.min(0.6, alpha + 0.12).toFixed(3)})`,
  }
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

  if (arms.length === 0)
    return (
      <Card className="py-10">
        <Empty
          icon={<Grid3x3 size={18} />}
          title="Nothing learned yet"
          body="Each cell is a situation: how far the strike sits above the line, and how much time is left. Run the training gym below or let the agent trade to fill it in."
        />
      </Card>
    )

  return (
    <Card className="p-4">
      <SectionTitle
        right={
          margins.length > 1 ? (
            <Segmented
              id="heat-margin"
              value={margin}
              onChange={setMargin}
              options={[{ value: 'all', label: 'All margins' }, ...margins.map((m) => ({ value: m, label: m }))]}
            />
          ) : undefined
        }
      >
        Where the strategy pays
      </SectionTitle>
      <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-dim">
        Each cell is the agent’s current belief about win rate in that situation, set against the break-even rate at typical prices.
        Green means it believes the trade clears break-even; red means it does not. Faded cells have little evidence.
      </p>

      <div className="mt-4 overflow-x-auto">
        <div
          className="grid min-w-[520px] gap-1.5"
          style={{ gridTemplateColumns: `110px repeat(${times.length}, minmax(84px, 1fr))` }}
        >
          <div className="flex items-end pb-1 text-[9.5px] font-semibold uppercase tracking-wider text-dim">
            Buffer ↓ · Time →
          </div>
          {times.map((t) => (
            <div key={t} className="num pb-1 text-center text-[10.5px] font-semibold text-mute">
              {t}
            </div>
          ))}
          {buffers.map((b) => (
            <FragmentRow key={b}>
              <div className="num flex items-center text-[11px] font-semibold text-slate-300">{b}</div>
              {times.map((t) => {
                const key = `${b}|${t}`
                const c = cells.get(key)
                if (!c) return <div key={key} className="h-[62px] rounded-lg border border-dashed border-hair" />
                const delta = c.pWin - c.breakeven
                const isActive = activeKey === key
                return (
                  <motion.button
                    key={key}
                    onMouseEnter={() => setHover(key)}
                    onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(key)}
                    onBlur={() => setHover(null)}
                    onClick={() => setPicked((p) => (p === key ? null : key))}
                    whileHover={{ scale: 1.04 }}
                    transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                    className={clsx(
                      'relative flex h-[62px] flex-col items-center justify-center rounded-lg border transition-shadow',
                      isActive && 'z-10 shadow-lift ring-1 ring-white/40',
                    )}
                    style={cellStyle(c)}
                  >
                    <span className="num text-[15px] font-bold leading-none text-slate-50">{pct(c.pWin, 1)}</span>
                    <span className={clsx('num mt-1 text-[10px] font-medium', delta >= 0 ? 'text-mint' : 'text-coral')}>
                      {signedPct(delta, 1)} vs b/e
                    </span>
                    <span className="num absolute right-1.5 top-1 text-[9px] text-white/50">n={c.n}</span>
                  </motion.button>
                )
              })}
            </FragmentRow>
          ))}
        </div>
      </div>

      <div className="mt-4 min-h-[76px] rounded-xl border border-hair bg-ink-950/50 px-4 py-3">
        <AnimatePresence mode="wait" initial={false}>
          {active ? (
            <motion.div key={activeKey} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }}>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[11.5px]">
                <span className="font-semibold text-slate-100">
                  {active.buffer} · {active.time}
                  {margin !== 'all' && ` · ${margin}`}
                </span>
                <span className="num text-mute">
                  record {active.wins}–{active.n - active.wins}
                </span>
                <span className="num text-mute">+{active.simN} simulated</span>
                <span className="num text-mute">break-even {pct(active.breakeven, 1)}</span>
                <span className={clsx('num font-semibold', pnlColor(active.meanReturn))}>
                  {signedPct(active.meanReturn, 2)} per $ risked
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {active.arms.map((a) => (
                  <span
                    key={a.key}
                    className="num inline-flex items-center gap-1.5 rounded-md border border-hair bg-white/[0.03] px-2 py-1 text-[10.5px] text-mute"
                    title={`${a.label} — prior ${pct(a.prior, 1)}, now ${pct(a.p_win, 1)}`}
                  >
                    <span className="font-sans text-slate-300">{a.dims.margin}</span>
                    {pct(a.prior, 1)} → <span className="font-semibold text-slate-100">{pct(a.p_win, 1)}</span>
                    <span className="text-dim">n={a.n}</span>
                  </span>
                ))}
              </div>
            </motion.div>
          ) : (
            <motion.div key="hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex h-[50px] items-center text-[11.5px] text-dim">
              Hover a cell to see its record, how far the belief has moved from the model’s starting point, and what it has returned.
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </Card>
  )
}

function FragmentRow({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}

/* ───────────────────────── Exit profiles ───────────────────────── */

function ExitProfiles({ arms }: { arms: ExitArm[] }) {
  return (
    <Card className="p-4">
      <SectionTitle>How quickly it bails</SectionTitle>
      <p className="mt-1 text-[11px] leading-relaxed text-dim">
        Each entry is assigned an exit style. Once games finish, early exits are scored against what holding would have paid, and
        the styles that do better get used more.
      </p>
      {arms.length === 0 ? (
        <Empty icon={<LogOut size={18} />} title="No exit data yet" className="!py-8" />
      ) : (
        <div className="mt-3 space-y-2.5">
          {arms.map((a) => {
            const judged = a.saved + a.shaken_out
            return (
              <motion.div key={a.key} whileHover={{ x: 2 }} className="rounded-xl border border-hair bg-ink-800/60 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-slate-100">{a.label}</div>
                    <div className="mt-0.5 text-[11px] leading-snug text-dim">{a.description}</div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className={clsx('num text-sm font-semibold', pnlColor(a.mean_return))}>{signedPct(a.mean_return, 2)}</div>
                    <div className="num text-[10px] text-dim">per $ · n={a.n}</div>
                  </div>
                </div>
                <div className="mt-2.5 grid grid-cols-2 gap-4">
                  <div>
                    <div className="mb-1 flex justify-between text-[10px] text-dim">
                      <span>
                        <span className="text-mint">{a.saved} saved</span> · <span className="text-gold">{a.shaken_out} shaken out</span>
                      </span>
                    </div>
                    <div className="flex h-[5px] overflow-hidden rounded-full bg-white/[0.07]">
                      {judged > 0 && (
                        <>
                          <motion.div className="bg-mint" initial={false} animate={{ width: `${(a.saved / judged) * 100}%` }} />
                          <motion.div className="bg-gold" initial={false} animate={{ width: `${(a.shaken_out / judged) * 100}%` }} />
                        </>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="mb-1 flex justify-between text-[10px] text-dim">
                      <span>Share of new entries</span>
                      <span className="num text-slate-300">{pct(a.share)}</span>
                    </div>
                    <Meter value={a.share} tone="#8b9cff" height={5} />
                  </div>
                </div>
              </motion.div>
            )
          })}
        </div>
      )}
    </Card>
  )
}

/* ───────────────────────── Calibration ───────────────────────── */

function Calibration({ rows }: { rows: LearningState['calibration'] }) {
  const used = rows.filter((r) => r.n > 0)
  const lo = used.length ? Math.max(0, Math.floor((Math.min(...used.map((r) => Math.min(r.predicted, r.actual))) - 0.04) * 20) / 20) : 0
  const hi = 1
  const pos = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / (hi - lo || 1)) * 100))}%`
  return (
    <Card className="p-4">
      <SectionTitle>Is the model honest?</SectionTitle>
      <p className="mt-1 text-[11px] leading-relaxed text-dim">
        When it says a trade wins 95% of the time, does it? The tick is what it predicted; the bar is what actually happened.
      </p>
      {used.length === 0 ? (
        <Empty icon={<Target size={18} />} title="No calibration data yet" className="!py-8" />
      ) : (
        <div className="mt-4 space-y-3">
          {used.map((r) => {
            const gap = r.actual - r.predicted
            const ok = gap >= -0.015
            return (
              <div key={r.bucket} className="grid grid-cols-[72px_1fr_92px] items-center gap-3">
                <span className="num text-[11px] font-medium text-slate-300">{r.bucket}</span>
                <div className="relative h-[10px] rounded-full bg-white/[0.06]">
                  <motion.div
                    className="absolute inset-y-0 left-0 rounded-full"
                    style={{ background: ok ? '#3ddc97' : '#ff6b6b', opacity: 0.85 }}
                    initial={false}
                    animate={{ width: pos(r.actual) }}
                    transition={{ type: 'spring', stiffness: 140, damping: 24 }}
                  />
                  <span
                    className="absolute -inset-y-1 w-[2px] rounded bg-white"
                    style={{ left: pos(r.predicted) }}
                    title={`Predicted ${pct(r.predicted, 1)}`}
                  />
                </div>
                <span className="num text-right text-[11px]">
                  <span className="font-semibold text-slate-100">{pct(r.actual, 1)}</span>
                  <span className={clsx('ml-1.5', ok ? 'text-mint' : 'text-coral')}>{signedPct(gap, 1)}</span>
                  <span className="ml-1.5 text-dim">n={r.n}</span>
                </span>
              </div>
            )
          })}
          <div className="num flex justify-between pl-[84px] pr-[104px] text-[9.5px] text-dim">
            <span>{pct(lo)}</span>
            <span>100%</span>
          </div>
        </div>
      )}
    </Card>
  )
}

/* ───────────────────────── Training gym ───────────────────────── */

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
        title: `Training finished · ${r.episodes} simulated games`,
        body: `${r.trades} practice trades, ${pct(r.win_rate, 1)} won, ${r.lessons} new lesson${r.lessons === 1 ? '' : 's'}.`,
      })
    } catch (e) {
      toast({ level: 'error', title: 'Training did not run', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="relative overflow-hidden p-5">
      <div
        className="pointer-events-none absolute -left-20 -top-24 h-56 w-56 rounded-full blur-3xl"
        style={{ background: 'radial-gradient(circle, rgba(245,183,78,0.14), transparent 70%)' }}
      />
      <div className="relative grid gap-5 lg:grid-cols-[1fr_1.1fr] lg:items-center">
        <div>
          <div className="flex items-center gap-2">
            <Dumbbell size={16} className="text-gold" />
            <h3 className="text-[15px] font-semibold text-slate-50">Training gym</h3>
            <Badge tone="gold">Simulated</Badge>
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-mute">
            Plays simulated fourth quarters at full speed so the agent can practise your playbook: when to get in, when to bail.
            Practice only shapes how it trades in the simulator. On real markets it learns from real results alone.
          </p>
          <div className="mt-4 flex items-center gap-4">
            <div className="flex-1">
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-xs text-slate-300">Games to simulate</span>
                <span className="num text-sm font-semibold text-slate-50">{episodes}</span>
              </div>
              <Slider value={episodes} min={10} max={500} step={10} onChange={setEpisodes} tone="#f5b74e" disabled={busy} ariaLabel="Episodes" />
            </div>
            <Button variant="primary" size="md" onClick={run} loading={busy} className="shrink-0">
              {!busy && <Play size={14} />}
              {busy ? 'Training…' : 'Run'}
            </Button>
          </div>
        </div>

        <div className="rounded-xl border border-hair bg-ink-950/50 p-4">
          <AnimatePresence mode="wait" initial={false}>
            {busy ? (
              <motion.div key="busy" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex h-[76px] flex-col justify-center">
                <div className="text-xs text-mute">Running {episodes} simulated games…</div>
                <div className="relative mt-3 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                  <motion.div
                    className="absolute inset-y-0 w-1/3 rounded-full bg-gold"
                    animate={{ left: ['-35%', '100%'] }}
                    transition={{ duration: 1.3, repeat: Infinity, ease: 'easeInOut' }}
                  />
                </div>
              </motion.div>
            ) : result ? (
              <motion.div key="result" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="grid grid-cols-5 gap-3">
                {[
                  { l: 'Games', v: result.episodes.toLocaleString() },
                  { l: 'Trades', v: result.trades.toLocaleString() },
                  { l: 'Won', v: result.trades ? pct(result.win_rate, 1) : '—' },
                  { l: 'Sim P&L', v: <span className={pnlColor(result.pnl)}>{money(result.pnl, { sign: true, decimals: 0 })}</span> },
                  { l: 'Lessons', v: `+${result.lessons}` },
                ].map((x) => (
                  <div key={x.l} className="h-[76px]">
                    <div className="label !text-[9.5px]">{x.l}</div>
                    <div className="num mt-2 text-lg font-bold text-slate-50">{x.v}</div>
                  </div>
                ))}
              </motion.div>
            ) : (
              <motion.div key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex h-[76px] items-center gap-3 text-xs text-dim">
                <FlaskConical size={18} className="shrink-0" />
                Results of the last run show up here: games played, practice trades, win rate and any new lessons.
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </Card>
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
        <Empty icon={<Grid3x3 size={18} />} title="Learning data unavailable" body="The backend did not answer. This fills in once it is running." />
      </Card>
    ) : (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[92px] w-full !rounded-xl2" />
          ))}
        </div>
        <Skeleton className="h-[320px] w-full !rounded-xl2" />
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <Totals t={state.totals} />
      <Gym onDone={load} />
      <Heatmap arms={state.arms} />
      <div className="grid gap-3 lg:grid-cols-2">
        <ExitProfiles arms={state.exit_arms} />
        <Calibration rows={state.calibration} />
      </div>
    </div>
  )
}
