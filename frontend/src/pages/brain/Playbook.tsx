import clsx from 'clsx'
import { BookOpen, Check, ChevronDown, CircleAlert } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { Card, Empty, Skeleton, Slider, Spinner, Toggle } from '../../components/ui'
import { clamp, fmtUnit, money, pct } from '../../format'
import { useStore } from '../../store'
import type { ParamSpec, Strategy } from '../../types'

type Values = Record<string, number>

/** Settings a beginner can leave alone. They live behind "Advanced". */
const ADVANCED = new Set(['min_edge', 'max_ot_risk', 'skip_close_margin', 'take_profit'])

const GROUP_TITLE: Record<ParamSpec['group'], string> = {
  entry: 'When to buy',
  sizing: 'How much',
  exit: 'When to sell',
}

const trim = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))

/** 2.5 → "2:30" */
function minutes(n: number) {
  const m = Math.floor(n)
  const s = Math.round((n - m) * 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

/** A couple of plain sentences describing what the agent will do with these settings. */
function summarize(s: Strategy, values: Values): string {
  const get = (key: string) => {
    const spec = s.params.find((p) => p.key === key)
    return spec ? (values[key] ?? spec.value) : null
  }
  const maxMin = get('max_minutes_left')
  const minMin = get('min_minutes_left')
  const bufLo = get('buffer_min')
  const bufHi = get('buffer_max')
  const pxLo = get('min_price')
  const pxHi = get('max_price')
  const stake = get('stake')
  const minP = get('min_p_win')
  const stop = get('stop_loss')
  const take = get('take_profit')

  const known = [maxMin, bufLo, pxLo, stake, minP, stop].filter((v) => v != null).length
  if (known < 3) {
    // A strategy this page does not know: list its settings by group instead of guessing.
    const part = (g: ParamSpec['group']) =>
      s.params
        .filter((p) => p.group === g)
        .map((p) => `${p.label.toLowerCase()} ${fmtUnit(values[p.key] ?? p.value, p.unit, p.step)}`)
        .join(', ')
    return [part('entry') && `Buys when ${part('entry')}`, part('sizing') && `puts on ${part('sizing')}`, part('exit') && `sells on ${part('exit')}`]
      .filter(Boolean)
      .join('; ')
      .concat('.')
  }

  let when: string
  if (maxMin != null && maxMin >= 12)
    when = minMin != null && minMin > 0 ? `From the end of Q3 until ${minutes(minMin)} is left` : 'From the end of Q3'
  else if (maxMin != null && minMin != null && minMin > 0)
    when = `In the 4th quarter, with between ${minutes(minMin)} and ${minutes(maxMin)} left`
  else if (maxMin != null) when = `In the 4th quarter, with ${minutes(maxMin)} or less left`
  else when = 'Late in the game'

  let buy = 'the agent buys the under'
  if (bufLo != null && bufHi != null) buy += ` ${trim(bufLo)} to ${trim(bufHi)} points above the line`
  else if (bufLo != null) buy += ` at least ${trim(bufLo)} points above the line`
  if (pxLo != null && pxHi != null) buy += `, paying ${trim(pxLo)}¢ to ${trim(pxHi)}¢`
  else if (pxHi != null) buy += `, paying up to ${trim(pxHi)}¢`
  if (stake != null) buy += `, $${Math.round(stake).toLocaleString()} a trade`

  const outs: string[] = []
  if (minP != null) outs.push(`its chance of winning drops below ${trim(minP)}%`)
  if (stop != null) outs.push(`the price falls ${trim(stop)}¢`)
  let sell = outs.length ? ` It sells if ${outs.join(' or ')}` : ''
  if (take != null && take > 0 && take < 100)
    sell += sell ? `, and takes the win early at ${trim(take)}¢` : ` It takes the win early at ${trim(take)}¢`

  return `${when}, ${buy}.${sell ? `${sell}.` : ''}`
}

function ParamRow({
  spec,
  value,
  onChange,
}: {
  spec: ParamSpec
  value: number
  onChange: (v: number) => void
}) {
  const [text, setText] = useState<string | null>(null)
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
    <div className="py-3.5">
      <div className="flex items-baseline justify-between gap-3">
        <label className="text-sm font-medium text-slate-200">{spec.label}</label>
        {text == null ? (
          <button
            type="button"
            onClick={() => setText(String(value))}
            className="num -mr-1.5 rounded-lg px-1.5 py-0.5 text-sm font-semibold text-white transition-colors hover:bg-white/[0.07]"
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
            className="num w-24 rounded-lg border border-white/40 bg-ink-800 px-2 py-0.5 text-right text-sm font-semibold text-white outline-none"
          />
        )}
      </div>
      <div className="mt-1.5">
        <Slider value={value} min={spec.min} max={spec.max} step={spec.step} onChange={onChange} tone="#f4f4f5" ariaLabel={spec.label} />
      </div>
      <p className="hint mt-0.5">{spec.help}</p>
    </div>
  )
}

function StrategyCard({ strategy, onUpdate }: { strategy: Strategy; onUpdate: (s: Strategy) => void }) {
  const toast = useStore((s) => s.toast)
  const [values, setValues] = useState<Values>(() => Object.fromEntries(strategy.params.map((p) => [p.key, p.value])))
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [enabled, setEnabled] = useState(strategy.enabled)
  const [advanced, setAdvanced] = useState(false)
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
      toast({ level: 'error', title: 'Could not save your rules', body: e instanceof ApiError ? e.message : '' })
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
      toast({ level: 'error', title: 'Could not switch that rule set', body: e instanceof ApiError ? e.message : '' })
    }
  }

  const summary = useMemo(() => summarize(strategy, values), [strategy, values])
  const basic = strategy.params.filter((p) => !ADVANCED.has(p.key))
  const extra = strategy.params.filter((p) => ADVANCED.has(p.key))
  const groups = (['entry', 'sizing', 'exit'] as const).filter((g) => basic.some((p) => p.group === g))
  const st = strategy.stats

  return (
    <Card className={clsx('p-4 transition-opacity sm:p-6', !enabled && 'opacity-70')}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="h-section">{strategy.name}</h3>
          <p className="mt-0.5 text-xs text-dim">
            {st.trades > 0
              ? `${st.trades} ${st.trades === 1 ? 'trade' : 'trades'} · ${pct(st.win_rate)} won · ${money(st.pnl, { sign: true })}`
              : 'No trades yet'}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2.5">
          <span className="text-[13px] text-mute">{enabled ? 'On' : 'Off'}</span>
          <Toggle checked={enabled} onChange={toggle} tone="#19c37d" label={`Turn ${strategy.name} ${enabled ? 'off' : 'on'}`} />
        </div>
      </div>

      <p className="mt-4 text-base leading-relaxed text-white sm:text-lg">{summary}</p>
      <div className="mt-1.5 flex h-4 items-center gap-1.5 text-xs text-dim">
        {status === 'saving' && (
          <>
            <Spinner size={10} /> Saving
          </>
        )}
        {status === 'saved' && (
          <>
            <Check size={12} className="text-mint" /> Saved
          </>
        )}
        {status === 'error' && (
          <>
            <CircleAlert size={12} className="text-coral" /> Not saved
          </>
        )}
        {status === 'idle' && <span>Drag a slider and this sentence updates. Changes save by themselves.</span>}
      </div>

      <div className={clsx('mt-5 grid gap-x-10 gap-y-6', groups.length >= 3 ? 'lg:grid-cols-3' : 'lg:grid-cols-2')}>
        {groups.map((g) => (
          <div key={g}>
            <h4 className="border-b border-hair pb-2 text-sm font-semibold text-white">{GROUP_TITLE[g]}</h4>
            <div className="divide-y divide-hair">
              {basic
                .filter((p) => p.group === g)
                .map((p) => (
                  <ParamRow key={p.key} spec={p} value={values[p.key] ?? p.value} onChange={(v) => change(p.key, v)} />
                ))}
            </div>
          </div>
        ))}
      </div>

      {extra.length > 0 && (
        <div className="mt-4 border-t border-hair pt-3">
          <button
            type="button"
            onClick={() => setAdvanced((v) => !v)}
            aria-expanded={advanced}
            className="flex items-center gap-1.5 text-[13px] font-medium text-mute hover:text-white"
          >
            Advanced
            <ChevronDown size={14} className={clsx('transition-transform', advanced && 'rotate-180')} />
          </button>
          {advanced && (
            <div className="mt-1 grid gap-x-10 lg:grid-cols-2">
              {extra.map((p) => (
                <ParamRow key={p.key} spec={p} value={values[p.key] ?? p.value} onChange={(v) => change(p.key, v)} />
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

/** The Rules tab: what the agent is allowed to buy, how much, and when it sells. */
export default function Rules() {
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
          <Empty icon={<BookOpen size={18} />} title="Rules unavailable" body="The server did not answer. Your rules will load here once it is running." />
        </Card>
      )
    return <Skeleton className="h-[420px] w-full !rounded-xl2" />
  }
  if (strategies.length === 0)
    return (
      <Card className="py-12">
        <Empty icon={<BookOpen size={18} />} title="No rules yet" body="Rule sets the agent can follow will appear here with their settings." />
      </Card>
    )

  return (
    <div className="space-y-4">
      <p className="hint max-w-2xl">
        These are your rules. The agent only buys what fits them, then learns which situations inside them pay and which do not.
      </p>
      {strategies.map((s) => (
        <StrategyCard key={s.id} strategy={s} onUpdate={onUpdate} />
      ))}
    </div>
  )
}
