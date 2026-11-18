import { AnimatePresence, animate, motion } from 'framer-motion'
import clsx from 'clsx'
import { X } from 'lucide-react'
import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type HTMLAttributes,
  type ReactNode,
} from 'react'
import { riskTone } from '../format'
import type { RiskLevel } from '../types'

/* ───────────────────────── Surfaces ───────────────────────── */

export function Card({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { children?: ReactNode }) {
  return (
    <div className={clsx('surface', className)} {...rest}>
      {children}
    </div>
  )
}

export function SectionTitle({
  children,
  right,
  className,
}: {
  children: ReactNode
  right?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('flex items-center justify-between gap-3', className)}>
      <h3 className="label">{children}</h3>
      {right}
    </div>
  )
}

/* ───────────────────────── Badges ───────────────────────── */

export type Tone = 'mint' | 'coral' | 'gold' | 'peri' | 'slate'

const toneClass: Record<Tone, string> = {
  mint: 'bg-mint/10 text-mint border-mint/20',
  coral: 'bg-coral/10 text-coral border-coral/20',
  gold: 'bg-gold/10 text-gold border-gold/20',
  peri: 'bg-peri/10 text-peri border-peri/20',
  slate: 'bg-white/[0.04] text-mute border-hair',
}

export function Badge({
  tone = 'slate',
  children,
  className,
  title,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={clsx(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-[1px] text-[10px] font-semibold uppercase tracking-wider',
        toneClass[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function SimTag({ className }: { className?: string }) {
  return (
    <Badge tone="gold" className={className} title="Simulated data — not a real game or market">
      Sim
    </Badge>
  )
}

export function LiveDot({ color = '#3ddc97', size = 7, pulse = true }: { color?: string; size?: number; pulse?: boolean }) {
  return (
    <span className="relative inline-flex shrink-0" style={{ width: size, height: size }}>
      {pulse && (
        <span className="absolute inset-0 animate-ping2 rounded-full" style={{ background: color }} />
      )}
      <span className="relative inline-block rounded-full" style={{ width: size, height: size, background: color }} />
    </span>
  )
}

export function RiskDot({ level, flags = [] }: { level: RiskLevel; flags?: string[] }) {
  const t = riskTone[level]
  return (
    <span title={[t.label, ...flags].join(' · ')} className="inline-flex items-center">
      <LiveDot color={t.dot} pulse={level === 'high'} />
    </span>
  )
}

/* ───────────────────────── Buttons ───────────────────────── */

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'ghost' | 'outline' | 'mint' | 'coral' | 'peri'
  size?: 'xs' | 'sm' | 'md'
  loading?: boolean
}

const variantClass: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary: 'bg-slate-100 text-ink-950 hover:bg-white',
  ghost: 'text-mute hover:text-slate-100 hover:bg-white/[0.05]',
  outline: 'border border-hair2 text-slate-200 hover:border-white/20 hover:bg-white/[0.04]',
  mint: 'bg-mint text-ink-950 hover:brightness-110',
  coral: 'bg-coral text-ink-950 hover:brightness-110',
  peri: 'bg-peri text-ink-950 hover:brightness-110',
}

const sizeClass = {
  xs: 'h-6 px-2 text-[11px] rounded-md gap-1',
  sm: 'h-8 px-3 text-xs rounded-lg gap-1.5',
  md: 'h-10 px-4 text-sm rounded-xl gap-2',
}

export function Button({
  variant = 'outline',
  size = 'sm',
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={clsx(
        'inline-flex select-none items-center justify-center font-semibold transition-all duration-150 active:scale-[0.97] disabled:pointer-events-none disabled:opacity-40',
        variantClass[variant],
        sizeClass[size],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Spinner size={size === 'md' ? 14 : 12} />}
      {children}
    </button>
  )
}

export function Spinner({ size = 14, className }: { size?: number; className?: string }) {
  return (
    <svg className={clsx('animate-spin', className)} width={size} height={size} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

/* ───────────────────────── Inputs ───────────────────────── */

export function Toggle({
  checked,
  onChange,
  tone = '#8b9cff',
  disabled,
  label,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  tone?: string
  disabled?: boolean
  label?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="relative h-[22px] w-[40px] shrink-0 rounded-full transition-colors duration-200 disabled:opacity-40"
      style={{ background: checked ? tone : 'rgba(255,255,255,0.1)' }}
    >
      <motion.span
        layout
        transition={{ type: 'spring', stiffness: 600, damping: 34 }}
        className="absolute top-[3px] h-4 w-4 rounded-full bg-white shadow"
        style={{ left: checked ? 21 : 3 }}
      />
    </button>
  )
}

export function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  tone = '#8b9cff',
  disabled,
  ariaLabel,
}: {
  value: number
  min: number
  max: number
  step?: number
  onChange: (v: number) => void
  tone?: string
  disabled?: boolean
  ariaLabel?: string
}) {
  const span = max - min || 1
  const pct = Math.min(100, Math.max(0, ((value - min) / span) * 100))
  return (
    <input
      type="range"
      className="range"
      aria-label={ariaLabel}
      min={min}
      max={max}
      step={step}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(Number(e.target.value))}
      style={{ '--pct': `${pct}%`, '--tone': tone } as CSSProperties}
    />
  )
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  id,
  size = 'sm',
}: {
  options: { value: T; label: ReactNode; tone?: string }[]
  value: T
  onChange: (v: T) => void
  id: string
  size?: 'sm' | 'md'
}) {
  return (
    <div className="inline-flex rounded-lg border border-hair bg-ink-950/60 p-0.5">
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={clsx(
              'relative rounded-md font-semibold transition-colors',
              size === 'sm' ? 'px-2.5 py-1 text-[11px]' : 'px-4 py-1.5 text-xs',
              active ? 'text-slate-50' : 'text-dim hover:text-slate-300',
            )}
          >
            {active && (
              <motion.span
                layoutId={`seg-${id}`}
                className="absolute inset-0 rounded-md bg-white/[0.09]"
                style={o.tone ? { background: `${o.tone}26`, boxShadow: `inset 0 0 0 1px ${o.tone}55` } : undefined}
                transition={{ type: 'spring', stiffness: 500, damping: 36 }}
              />
            )}
            <span className="relative">{o.label}</span>
          </button>
        )
      })}
    </div>
  )
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  id,
  className,
}: {
  tabs: { value: T; label: ReactNode; count?: number }[]
  value: T
  onChange: (v: T) => void
  id: string
  className?: string
}) {
  return (
    <div className={clsx('flex items-center gap-1 border-b border-hair', className)}>
      {tabs.map((t) => {
        const active = t.value === value
        return (
          <button
            key={t.value}
            type="button"
            onClick={() => onChange(t.value)}
            className={clsx(
              'relative flex items-center gap-1.5 px-3 py-2.5 text-xs font-semibold transition-colors',
              active ? 'text-slate-50' : 'text-dim hover:text-slate-300',
            )}
          >
            {t.label}
            {t.count != null && t.count > 0 && (
              <span className="num rounded bg-white/[0.06] px-1 text-[10px] text-mute">{t.count}</span>
            )}
            {active && (
              <motion.span
                layoutId={`tab-${id}`}
                className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-peri"
                transition={{ type: 'spring', stiffness: 500, damping: 38 }}
              />
            )}
          </button>
        )
      })}
    </div>
  )
}

/* ───────────────────────── Numbers ───────────────────────── */

/** Animates between numeric values and flashes green/red on change. */
export function Ticker({
  value,
  format = (n: number) => Math.round(n).toString(),
  className,
  flash = true,
  duration = 0.45,
}: {
  value: number
  format?: (n: number) => string
  className?: string
  flash?: boolean
  duration?: number
}) {
  const [display, setDisplay] = useState(value)
  const [dir, setDir] = useState<'up' | 'down' | null>(null)
  const prev = useRef(value)

  useEffect(() => {
    const from = prev.current
    if (from === value || Number.isNaN(value)) {
      setDisplay(value)
      return
    }
    prev.current = value
    setDir(value > from ? 'up' : 'down')
    const controls = animate(from, value, {
      duration,
      ease: 'easeOut',
      onUpdate: (v) => setDisplay(v),
    })
    const t = window.setTimeout(() => setDir(null), 900)
    return () => {
      controls.stop()
      window.clearTimeout(t)
      setDisplay(value)
    }
  }, [value, duration])

  const color = flash && dir ? (dir === 'up' ? '#3ddc97' : '#ff6b6b') : undefined
  return (
    <span className={clsx('num', className)} style={{ color, transition: 'color 600ms ease' }}>
      {format(display)}
    </span>
  )
}

export function Meter({
  value,
  tone = '#8b9cff',
  height = 4,
  className,
  marker,
}: {
  /** 0-1 */
  value: number
  tone?: string
  height?: number
  className?: string
  /** Optional 0-1 tick drawn on the track (e.g. break-even). */
  marker?: number
}) {
  const v = Math.min(1, Math.max(0, value || 0))
  return (
    <div className={clsx('relative w-full overflow-hidden rounded-full bg-white/[0.07]', className)} style={{ height }}>
      <motion.div
        className="absolute inset-y-0 left-0 rounded-full"
        style={{ background: tone }}
        initial={false}
        animate={{ width: `${v * 100}%` }}
        transition={{ type: 'spring', stiffness: 160, damping: 26 }}
      />
      {marker != null && (
        <span
          className="absolute inset-y-0 w-[2px] bg-white/70"
          style={{ left: `${Math.min(1, Math.max(0, marker)) * 100}%` }}
        />
      )}
    </div>
  )
}

/* ───────────────────────── States ───────────────────────── */

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('skeleton', className)} />
}

export function Empty({
  icon,
  title,
  body,
  action,
  className,
}: {
  icon?: ReactNode
  title: string
  body?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('flex flex-col items-center justify-center px-6 py-10 text-center', className)}>
      {icon && (
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-2xl border border-hair bg-white/[0.03] text-dim">
          {icon}
        </div>
      )}
      <div className="text-sm font-semibold text-slate-200">{title}</div>
      {body && <div className="mt-1 max-w-sm text-xs leading-relaxed text-dim">{body}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

/* ───────────────────────── Dialog ───────────────────────── */

export function Dialog({
  open,
  onClose,
  title,
  subtitle,
  children,
  width = 440,
  accent,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  width?: number
  accent?: string
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
          <motion.div
            role="dialog"
            aria-modal="true"
            className="relative w-full overflow-hidden rounded-2xl border border-hair2 bg-ink-900 shadow-lift"
            style={{ maxWidth: width }}
            initial={{ opacity: 0, y: 16, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.98 }}
            transition={{ type: 'spring', stiffness: 420, damping: 32 }}
          >
            {accent && <div className="absolute inset-x-0 top-0 h-[2px]" style={{ background: accent }} />}
            <div className="flex items-start justify-between gap-4 px-5 pb-3 pt-5">
              <div className="min-w-0">
                <div className="text-[15px] font-semibold text-slate-50">{title}</div>
                {subtitle && <div className="mt-0.5 text-xs text-mute">{subtitle}</div>}
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                className="rounded-lg p-1.5 text-dim transition-colors hover:bg-white/[0.06] hover:text-slate-200"
              >
                <X size={16} />
              </button>
            </div>
            <div className="px-5 pb-5">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/* ───────────────────────── Misc ───────────────────────── */

export function Stat({
  label,
  children,
  sub,
  className,
}: {
  label: ReactNode
  children: ReactNode
  sub?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('min-w-0', className)}>
      <div className="label">{label}</div>
      <div className="num mt-1 truncate text-[15px] font-semibold text-slate-100">{children}</div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-dim">{sub}</div>}
    </div>
  )
}

export function Chip({ k, v }: { k: string; v: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-hair bg-white/[0.03] px-1.5 py-[2px] text-[10.5px]">
      <span className="text-dim">{k}</span>
      <span className="num font-medium text-slate-200">{v}</span>
    </span>
  )
}
