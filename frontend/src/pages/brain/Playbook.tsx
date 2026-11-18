import { motion } from 'framer-motion'
import clsx from 'clsx'
import { BookOpen, Check, CircleAlert, LogIn, LogOut, Quote, Scale } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { Card, Empty, Skeleton, Slider, Spinner, Toggle } from '../../components/ui'
import { clamp, fmtUnit, money, pct, pnlColor } from '../../format'
import { useStore } from '../../store'
import type { ParamSpec, Strategy } from '../../types'

type Values = Record<string, number>

function find(params: ParamSpec[], values: Values, ...needles: string[]) {
  for (const n of needles) {
    const p = params.find((x) => x.key === n) ?? params.find((x) => x.key.includes(n))
    if (p) return { spec: p, value: values[p.key] ?? p.value }
  }
  return null
}

const asPct = (v: number, unit: string) => (unit === '%' || v > 1 ? v : v * 100)
const trim = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))

/** One plain-English sentence describing what the strategy will do with these settings. */
function summarize(s: Strategy, values: Values): string {
  const P = s.params
  const period = find(P, values, 'min_period', 'period')
  const maxMin = find(P, values, 'max_minutes_left', 'max_minutes')
  const minMin = find(P, values, 'min_minutes_left', 'min_minutes')
  const bufLo = find(P, values, 'buffer_min', 'min_buffer')
  const bufHi = find(P, values, 'buffer_max', 'max_buffer')
  const pxLo = find(P, values, 'min_price')
  const pxHi = find(P, values, 'max_price')
  const stake = find(P, values, 'stake')
  const minEdge = find(P, values, 'min_edge')
  const minP = find(P, values, 'min_p_win', 'p_win')
  const stop = find(P, values, 'stop_loss')
  const closeMargin = find(P, values, 'close_game_margin', 'close_margin')
  const closeMin = find(P, values, 'close_game_minutes', 'close_minutes')
  const take = find(P, values, 'take_profit')

  const found = [maxMin, bufLo, pxLo, stake, minP, stop].filter(Boolean).length
  if (found < 3) {
    // Unknown strategy shape: fall back to listing its settings by group.
    const part = (g: ParamSpec['group']) =>
      P.filter((p) => p.group === g)
        .map((p) => `${p.label.toLowerCase()} ${fmtUnit(values[p.key] ?? p.value, p.unit, p.step)}`)
        .join(', ')
    return [part('entry') && `Enter when ${part('entry')}`, part('sizing') && `size ${part('sizing')}`, part('exit') && `exit on ${part('exit')}`]
      .filter(Boolean)
      .join('; ')
      .concat('.')
  }

  const when: string[] = []
  when.push(period ? `In Q${trim(period.value)}` : 'Late in the game')
  if (maxMin && minMin) when.push(`with ${trim(minMin.value)}–${trim(maxMin.value)} min left`)
  else if (maxMin) when.push(`with ≤${trim(maxMin.value)}:00 left`)

  let buy = 'buy the under'
  if (bufLo && bufHi) buy += ` ${trim(bufLo.value)}–${trim(bufHi.value)} pts above the FanDuel line`
  else if (bufLo) buy += ` at least ${trim(bufLo.value)} pts above the FanDuel line`
  if (pxLo && pxHi) buy += ` at ${trim(pxLo.value)}–${trim(pxHi.value)}¢`
  else if (pxHi) buy += ` up to ${trim(pxHi.value)}¢`
  if (stake) buy += `, $${Math.round(stake.value).toLocaleString()} a trade`
  if (minEdge && minEdge.value > 0)
    buy += ` when the model sees at least ${trim(asPct(minEdge.value, minEdge.spec.unit))}${minEdge.spec.unit === '¢' ? '¢' : '%'} of edge`

  const exits: string[] = []
  if (minP) exits.push(`win chance drops under ${trim(asPct(minP.value, minP.spec.unit))}%`)
  if (stop) exits.push(`the price falls ${trim(stop.value)}¢ from entry`)
  if (closeMargin && closeMin)
    exits.push(`it is a ${trim(closeMargin.value)}-point game inside the last ${trim(closeMin.value)} min`)
  let tail = exits.length ? `; bail if ${exits.join(', or ')}` : ''
  if (take && take.value > 0 && take.value < 100) tail += `${tail ? '. ' : '; '}Take profit at ${trim(take.value)}¢`

  return `${when.join(' ')}, ${buy}${tail}.`
}

const groupMeta: Record<ParamSpec['group'], { label: string; icon: React.ReactNode; tone: string }> = {
  entry: { label: 'When to buy', icon: <LogIn size={13} />, tone: '#3ddc97' },
  sizing: { label: 'How much', icon: <Scale size={13} />, tone: '#8b9cff' },
  exit: { label: 'When to sell', icon: <LogOut size={13} />, tone: '#ff6b6b' },
}

function ParamRow({
  spec,
  value,
  tone,
  disabled,
  onChange,
}: {
  spec: ParamSpec
  value: number
  tone: string
  disabled: boolean
  onChange: (v: number) => void
}) {
  const [text, setText] = useState<string | null>(null)
  const changed = Math.abs(value - spec.value) > 1e-9
  const commit = () => {
    if (text == null) return
    const n = Number(text)
    if (!Number.isNaN(n)) {
      const snapped = Math.round(clamp(n, spec.min, spec.max) / spec.step) * spec.step
      onChange(Number(snapped.toFixed(6)))
    }
    setText(null)
  }
  return (
    <div className="group py-2">
      <div className="flex items-baseline justify-between gap-3">
        <label className="text-xs font-medium text-slate-200" title={spec.help}>
          {spec.label}
        </label>
        <div className="flex items-center gap-1.5">
          {changed && <span className="h-1 w-1 rounded-full bg-gold" title="Edited — saving" />}
          {text == null ? (
            <button
              disabled={disabled}
              onClick={() => setText(String(value))}
              className="num rounded-md px-1.5 py-0.5 text-xs font-semibold text-slate-50 transition-colors hover:bg-white/[0.07]"
              title="Click to type a value"
            >
              {fmtUnit(value, spec.unit, spec.step)}
            </button>
          ) : (
            <input
              autoFocus
              type="number"
              value={text}
              min={spec.min}
              max={spec.max}
              step={spec.step}
              onChange={(e) => setText(e.target.value)}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit()
                if (e.key === 'Escape') setText(null)
              }}
              className="num w-20 rounded-md border border-peri/50 bg-ink-950 px-1.5 py-0.5 text-right text-xs font-semibold text-slate-50 outline-none"
            />
          )}
        </div>
      </div>
      <div className="mt-1">
        <Slider value={value} min={spec.min} max={spec.max} step={spec.step} onChange={onChange} tone={tone} disabled={disabled} ariaLabel={spec.label} />
      </div>
      <div className="flex items-start justify-between gap-3">
        <p className="text-[10.5px] leading-snug text-dim">{spec.help}</p>
        <span className="num shrink-0 text-[9.5px] text-ink-600">
          {fmtUnit(spec.min, spec.unit, spec.step)} – {fmtUnit(spec.max, spec.unit, spec.step)}
        </span>
      </div>
    </div>
  )
}

function StrategyCard({ strategy, onUpdate }: { strategy: Strategy; onUpdate: (s: Strategy) => void }) {
  const toast = useStore((s) => s.toast)
  const [values, setValues] = useState<Values>(() => Object.fromEntries(strategy.params.map((p) => [p.key, p.value])))
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [enabled, setEnabled] = useState(strategy.enabled)
  const pending = useRef<Values>({})
  const timer = useRef<number | null>(null)

  useEffect(() => setEnabled(strategy.enabled), [strategy.enabled])

  const flush = useCallback(async () => {
    const params = pending.current
    pending.current = {}
    if (Object.keys(params).length === 0) return
    setStatus('saving')
    try {
      const next = await api.updateStrategy(strategy.id, { params })
      onUpdate(next)
      setStatus(Object.keys(pending.current).length ? 'saving' : 'saved')
    } catch (e) {
      setStatus('error')
      toast({ level: 'error', title: 'Could not save the playbook', body: e instanceof ApiError ? e.message : '' })
    }
  }, [strategy.id, onUpdate, toast])

  useEffect(
    () => () => {
      if (timer.current) {
        window.clearTimeout(timer.current)
        void flush()
      }
    },
    [flush],
  )

  const change = (key: string, v: number) => {
    setValues((prev) => ({ ...prev, [key]: v }))
    pending.current[key] = v
    setStatus('saving')
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      timer.current = null
      void flush()
    }, 450)
  }

  const toggle = async (v: boolean) => {
    setEnabled(v)
    try {
      onUpdate(await api.updateStrategy(strategy.id, { enabled: v }))
    } catch (e) {
      setEnabled(!v)
      toast({ level: 'error', title: 'Could not update the strategy', body: e instanceof ApiError ? e.message : '' })
    }
  }

  const summary = useMemo(() => summarize(strategy, values), [strategy, values])
  const groups = (['entry', 'sizing', 'exit'] as const).filter((g) => strategy.params.some((p) => p.group === g))

  return (
    <Card className={clsx('overflow-hidden transition-opacity', !enabled && 'opacity-80')}>
      <div className="flex flex-wrap items-start justify-between gap-4 px-5 pt-5">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5">
            <h3 className="text-[15px] font-semibold text-slate-50">{strategy.name}</h3>
            <span
              className={clsx(
                'rounded-md px-1.5 py-[1px] text-[10px] font-bold uppercase tracking-wider',
                enabled ? 'bg-mint/15 text-mint' : 'bg-white/[0.06] text-dim',
              )}
            >
              {enabled ? 'Active' : 'Off'}
            </span>
          </div>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-mute">{strategy.description}</p>
        </div>
        <div className="flex items-center gap-5">
          <div className="flex items-center gap-4 text-right">
            <div>
              <div className="label !text-[9px]">Trades</div>
              <div className="num text-sm font-semibold text-slate-100">{strategy.stats.trades}</div>
            </div>
            <div>
              <div className="label !text-[9px]">Win rate</div>
              <div className="num text-sm font-semibold text-slate-100">
                {strategy.stats.trades ? pct(strategy.stats.win_rate) : '—'}
              </div>
            </div>
            <div>
              <div className="label !text-[9px]">P&L</div>
              <div className={clsx('num text-sm font-semibold', pnlColor(strategy.stats.pnl))}>
                {money(strategy.stats.pnl, { sign: true })}
              </div>
            </div>
          </div>
          <Toggle checked={enabled} onChange={toggle} tone="#3ddc97" label={`Enable ${strategy.name}`} />
        </div>
      </div>

      <div className="mx-5 mt-4 flex items-start gap-3 rounded-xl border border-peri/20 bg-peri/[0.06] px-4 py-3">
        <Quote size={15} className="mt-0.5 shrink-0 text-peri" />
        <motion.p key={summary} initial={{ opacity: 0.4 }} animate={{ opacity: 1 }} className="flex-1 text-[13px] leading-relaxed text-slate-100">
          {summary}
        </motion.p>
        <span className="flex shrink-0 items-center gap-1 pt-0.5 text-[10.5px] text-dim">
          {status === 'saving' && (
            <>
              <Spinner size={10} /> Saving
            </>
          )}
          {status === 'saved' && (
            <>
              <Check size={11} className="text-mint" /> Saved
            </>
          )}
          {status === 'error' && (
            <>
              <CircleAlert size={11} className="text-coral" /> Not saved
            </>
          )}
        </span>
      </div>

      <div className={clsx('grid gap-x-8 gap-y-2 px-5 pb-5 pt-4', groups.length >= 3 ? 'lg:grid-cols-3' : 'lg:grid-cols-2')}>
        {groups.map((g) => {
          const meta = groupMeta[g]
          return (
            <div key={g}>
              <div className="mb-1 flex items-center gap-1.5 border-b border-hair pb-2 text-[11px] font-semibold uppercase tracking-wider" style={{ color: meta.tone }}>
                {meta.icon}
                {meta.label}
              </div>
              <div className="divide-y divide-hair">
                {strategy.params
                  .filter((p) => p.group === g)
                  .map((p) => (
                    <ParamRow
                      key={p.key}
                      spec={p}
                      value={values[p.key] ?? p.value}
                      tone={meta.tone}
                      disabled={false}
                      onChange={(v) => change(p.key, v)}
                    />
                  ))}
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

export default function Playbook() {
  const [strategies, setStrategies] = useState<Strategy[] | null>(null)
  const [failed, setFailed] = useState(false)
  const connected = useStore((s) => s.connected)

  useEffect(() => {
    let alive = true
    api
      .playbook()
      .then((p) => {
        if (!alive) return
        if (Array.isArray(p)) setStrategies(p)
        setFailed(false)
      })
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [connected])

  const onUpdate = useCallback(
    (next: Strategy) => setStrategies((list) => (list ? list.map((s) => (s.id === next.id ? next : s)) : list)),
    [],
  )

  if (!strategies) {
    if (failed)
      return (
        <Card className="py-12">
          <Empty icon={<BookOpen size={18} />} title="Playbook unavailable" body="The backend did not answer. Your strategies will load here once it is running." />
        </Card>
      )
    return (
      <div className="space-y-3">
        <Skeleton className="h-[420px] w-full !rounded-xl2" />
      </div>
    )
  }
  if (strategies.length === 0)
    return (
      <Card className="py-12">
        <Empty icon={<BookOpen size={18} />} title="No strategies yet" body="Strategies the agent can run will appear here with their settings." />
      </Card>
    )

  return (
    <div className="space-y-3">
      <p className="max-w-3xl text-xs leading-relaxed text-mute">
        These are your rules. The agent only enters trades that fit an active strategy, then learns which situations inside those
        rules pay and which do not. Changes save as you drag.
      </p>
      {strategies.map((s) => (
        <StrategyCard key={s.id} strategy={s} onUpdate={onUpdate} />
      ))}
    </div>
  )
}
