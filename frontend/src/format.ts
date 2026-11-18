import type { Game, RiskLevel } from './types'

export const cents = (n: number | null | undefined) => (n == null ? '—' : `${Math.round(n)}¢`)

export const american = (n: number | null | undefined) =>
  n == null ? '—' : n > 0 ? `+${Math.round(n)}` : `${Math.round(n)}`

export function money(n: number | null | undefined, opts: { sign?: boolean; decimals?: number } = {}) {
  if (n == null || Number.isNaN(n)) return '—'
  const decimals = opts.decimals ?? 2
  const abs = Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  if (opts.sign) {
    if (n > 0.004) return `+$${abs}`
    if (n < -0.004) return `−$${abs}`
    return `$${abs}`
  }
  return n < 0 ? `−$${abs}` : `$${abs}`
}

export const pct = (p: number | null | undefined, decimals = 0) =>
  p == null || Number.isNaN(p) ? '—' : `${(p * 100).toFixed(decimals)}%`

export const signedPct = (p: number | null | undefined, decimals = 1) =>
  p == null || Number.isNaN(p) ? '—' : `${p > 0 ? '+' : p < 0 ? '−' : ''}${Math.abs(p * 100).toFixed(decimals)}%`

export const fixed = (n: number | null | undefined, d = 1) => (n == null || Number.isNaN(n) ? '—' : n.toFixed(d))

export const spread = (n: number | null | undefined) => (n == null ? '—' : n > 0 ? `+${n}` : `${n}`)

export const pnlColor = (n: number | null | undefined) =>
  n == null || Math.abs(n) < 0.005 ? 'text-slate-300' : n > 0 ? 'text-mint' : 'text-coral'

export function periodLabel(period: number) {
  if (period <= 0) return 'Pre'
  if (period <= 4) return `Q${period}`
  return period === 5 ? 'OT' : `${period - 4}OT`
}

export function gameClock(g: Pick<Game, 'state' | 'period' | 'clock' | 'start_time'>) {
  if (g.state === 'final') return g.period > 4 ? `Final/${periodLabel(g.period)}` : 'Final'
  if (g.state === 'pre') return startTime(g.start_time)
  return `${periodLabel(g.period)} ${g.clock}`
}

export function startTime(iso: string) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'Scheduled'
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  return sameDay ? time : `${d.toLocaleDateString([], { weekday: 'short' })} ${time}`
}

/** "7:42" or "42.3" → seconds */
export function clockSeconds(clock: string) {
  if (!clock) return 0
  const parts = clock.split(':')
  if (parts.length === 2) return (parseInt(parts[0], 10) || 0) * 60 + (parseFloat(parts[1]) || 0)
  return parseFloat(clock) || 0
}

export function relTime(iso: string | null | undefined) {
  if (!iso) return 'never'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const s = Math.round((Date.now() - t) / 1000)
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.round(h / 24)
  return `${d}d ago`
}

export function clockTime(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })
}

export function shortDate(iso: string | null | undefined) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/** Team colors can be near-black; lift them so they read on a dark surface. */
export function teamColor(hex: string | undefined | null) {
  const clean = (hex || '8d96a8').replace('#', '')
  const full = clean.length === 3 ? clean.split('').map((c) => c + c).join('') : clean.padEnd(6, '0').slice(0, 6)
  let r = parseInt(full.slice(0, 2), 16) || 0
  let g = parseInt(full.slice(2, 4), 16) || 0
  let b = parseInt(full.slice(4, 6), 16) || 0
  const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
  if (lum < 0.32) {
    const k = lum < 0.12 ? 0.62 : 0.42
    r = Math.round(r + (255 - r) * k)
    g = Math.round(g + (255 - g) * k)
    b = Math.round(b + (255 - b) * k)
  }
  return `rgb(${r}, ${g}, ${b})`
}

export const riskTone: Record<RiskLevel, { text: string; bg: string; dot: string; label: string }> = {
  low: { text: 'text-mint', bg: 'bg-mint/10', dot: '#3ddc97', label: 'Low risk' },
  medium: { text: 'text-gold', bg: 'bg-gold/10', dot: '#f5b74e', label: 'Caution' },
  high: { text: 'text-coral', bg: 'bg-coral/10', dot: '#ff6b6b', label: 'High risk' },
}

export const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n))

export function fmtUnit(value: number, unit: string, step = 1) {
  const decimals = step < 1 ? Math.min(3, String(step).split('.')[1]?.length ?? 1) : 0
  const v = value.toFixed(decimals)
  switch (unit) {
    case '$':
      return `$${Number(v).toLocaleString('en-US')}`
    case '¢':
      return `${v}¢`
    case '%':
      return `${v}%`
    case 'pts':
      return `${v} pts`
    case 'min':
      return `${v} min`
    default:
      return unit ? `${v} ${unit}` : v
  }
}
