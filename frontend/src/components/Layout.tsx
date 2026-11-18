import { AnimatePresence, motion } from 'framer-motion'
import clsx from 'clsx'
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Info,
  LayoutDashboard,
  Settings2,
  Wallet,
  X,
  XCircle,
} from 'lucide-react'
import { useEffect, useRef } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { money, pnlColor } from '../format'
import { useStore, type Toast } from '../store'
import type { AgentStatus } from '../types'
import { LiveDot, Spinner, Ticker } from './ui'

const NAV = [
  { to: '/', label: 'Desk', icon: LayoutDashboard, key: 'd' },
  { to: '/portfolio', label: 'Portfolio', icon: Wallet, key: 'p' },
  { to: '/brain', label: 'Brain', icon: BrainCircuit, key: 'b' },
  { to: '/settings', label: 'Settings', icon: Settings2, key: 's' },
]

export const agentTone: Record<AgentStatus['state'], { color: string; label: string }> = {
  paused: { color: '#5d6577', label: 'Paused' },
  idle: { color: '#8b9cff', label: 'Idle' },
  watching: { color: '#8b9cff', label: 'Watching' },
  acting: { color: '#3ddc97', label: 'Acting' },
}

function Logo() {
  return (
    <div className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-hair2 bg-ink-800">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="8.5" stroke="#8b9cff" strokeWidth="1.8" />
        <path d="M3.5 12h17" stroke="#3ddc97" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M12 3.5c3 2.6 3 14.4 0 17" stroke="#8b9cff" strokeWidth="1.4" strokeOpacity="0.55" />
        <path d="M12 3.5c-3 2.6-3 14.4 0 17" stroke="#8b9cff" strokeWidth="1.4" strokeOpacity="0.55" />
      </svg>
    </div>
  )
}

function Rail() {
  return (
    <nav className="z-20 flex w-[60px] shrink-0 flex-col items-center gap-1 border-r border-hair bg-ink-950/80 py-3 backdrop-blur">
      <Logo />
      <div className="mt-4 flex flex-col gap-1">
        {NAV.map(({ to, label, icon: Icon, key }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            title={`${label}  (g ${key})`}
            className={({ isActive }) =>
              clsx(
                'group relative flex h-10 w-10 items-center justify-center rounded-xl transition-colors',
                isActive ? 'text-slate-50' : 'text-dim hover:text-slate-200',
              )
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <motion.span
                    layoutId="rail-active"
                    className="absolute inset-0 rounded-xl border border-peri/30 bg-peri/10"
                    transition={{ type: 'spring', stiffness: 480, damping: 34 }}
                  />
                )}
                <Icon size={18} className="relative" strokeWidth={isActive ? 2.2 : 1.8} />
                <span className="pointer-events-none absolute left-[52px] z-30 whitespace-nowrap rounded-md border border-hair2 bg-ink-800 px-2 py-1 text-[11px] font-medium text-slate-200 opacity-0 shadow-lift transition-opacity group-hover:opacity-100">
                  {label}
                </span>
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}

function ModeBadge() {
  const settings = useStore((s) => s.app?.settings)
  if (!settings) return <div className="skeleton h-6 w-16" />
  const live = settings.trading_mode === 'live'
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={clsx(
          'relative inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.14em]',
          live ? 'border-coral/50 bg-coral/15 text-coral' : 'border-peri/30 bg-peri/10 text-peri',
        )}
        title={live ? 'Orders go to your real Kalshi account' : 'Orders are simulated — no real money'}
      >
        {live && <LiveDot color="#ff6b6b" size={6} />}
        {live ? 'Live' : 'Paper'}
        {live && (
          <span className="pointer-events-none absolute inset-0 animate-pulse rounded-lg ring-1 ring-coral/50" />
        )}
      </span>
      {settings.data_source === 'sim' && (
        <span
          className="rounded-lg border border-gold/30 bg-gold/10 px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.14em] text-gold"
          title="Games, odds and markets are simulated"
        >
          Sim data
        </span>
      )}
    </div>
  )
}

function TopBar() {
  const app = useStore((s) => s.app)
  const connected = useStore((s) => s.connected)
  const account = app?.account
  const agent = app?.agent
  const tone = agent ? agentTone[agent.state] : agentTone.paused

  return (
    <header className="z-10 flex h-[52px] shrink-0 items-center gap-4 border-b border-hair bg-ink-950/70 px-4 backdrop-blur">
      <div className="flex items-baseline gap-2">
        <span className="text-[15px] font-bold tracking-tight text-slate-50">Courtside</span>
        <span className="hidden text-[11px] text-dim xl:inline">Kalshi trading desk</span>
      </div>
      <ModeBadge />

      <div className="ml-auto flex items-center gap-5">
        <div className="hidden items-center gap-5 md:flex">
          <div className="text-right">
            <div className="label !text-[9.5px]">Equity</div>
            {account ? (
              <Ticker value={account.equity} format={(n) => money(n)} className="text-[13px] font-semibold text-slate-50" />
            ) : (
              <div className="skeleton mt-1 h-3.5 w-20" />
            )}
          </div>
          <div className="text-right">
            <div className="label !text-[9.5px]">Today</div>
            {account ? (
              <Ticker
                value={account.pnl_today}
                format={(n) => money(n, { sign: true })}
                flash={false}
                className={clsx('text-[13px] font-semibold', pnlColor(account.pnl_today))}
              />
            ) : (
              <div className="skeleton mt-1 h-3.5 w-14" />
            )}
          </div>
        </div>

        <div
          className="flex items-center gap-2 rounded-lg border border-hair bg-white/[0.03] px-2.5 py-1.5"
          title={agent?.focus || 'Agent status'}
        >
          <LiveDot color={tone.color} pulse={agent?.state === 'watching' || agent?.state === 'acting'} />
          <span className="text-[11px] font-semibold text-slate-200">Agent</span>
          <span className="text-[11px]" style={{ color: tone.color }}>
            {agent ? tone.label : '—'}
          </span>
        </div>

        <div className="flex items-center gap-1.5" title={connected ? 'Live connection' : 'Reconnecting…'}>
          <LiveDot color={connected ? '#3ddc97' : '#f5b74e'} pulse={!connected} size={6} />
          <span className="hidden text-[11px] text-dim lg:inline">{connected ? 'Connected' : 'Reconnecting'}</span>
        </div>
      </div>
    </header>
  )
}

const toastIcon = {
  info: <Info size={15} className="text-peri" />,
  success: <CheckCircle2 size={15} className="text-mint" />,
  warn: <AlertTriangle size={15} className="text-gold" />,
  error: <XCircle size={15} className="text-coral" />,
}
const toastBar = { info: '#8b9cff', success: '#3ddc97', warn: '#f5b74e', error: '#ff6b6b' }

function ToastItem({ t }: { t: Toast }) {
  const dismiss = useStore((s) => s.dismissToast)
  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 40, scale: 0.96 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 40, scale: 0.96 }}
      transition={{ type: 'spring', stiffness: 420, damping: 32 }}
      className="pointer-events-auto relative flex w-[340px] items-start gap-2.5 overflow-hidden rounded-xl border border-hair2 bg-ink-800/95 p-3 pl-4 shadow-lift backdrop-blur"
    >
      <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: toastBar[t.level] }} />
      <div className="mt-0.5">{toastIcon[t.level]}</div>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-semibold text-slate-100">{t.title}</div>
        {t.body && <div className="mt-0.5 text-[11.5px] leading-snug text-mute">{t.body}</div>}
      </div>
      <button onClick={() => dismiss(t.id)} className="text-dim hover:text-slate-200" aria-label="Dismiss">
        <X size={13} />
      </button>
    </motion.div>
  )
}

function Toasts() {
  const toasts = useStore((s) => s.toasts)
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col items-end gap-2">
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <ToastItem key={t.id} t={t} />
        ))}
      </AnimatePresence>
    </div>
  )
}

function ConnectingBanner() {
  const app = useStore((s) => s.app)
  const backendUp = useStore((s) => s.backendUp)
  const show = !app && backendUp !== null
  return (
    <AnimatePresence>
      {(show || (!app && backendUp === null)) && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center bg-ink-950/55 backdrop-blur-[2px]"
        >
          <motion.div
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            className="pointer-events-auto flex max-w-sm flex-col items-center rounded-2xl border border-hair2 bg-ink-900 px-8 py-7 text-center shadow-lift"
          >
            <div className="relative mb-4 flex h-12 w-12 items-center justify-center">
              <span className="absolute inset-0 animate-ping2 rounded-full bg-peri/30" />
              <span className="flex h-12 w-12 items-center justify-center rounded-full border border-peri/30 bg-peri/10 text-peri">
                <Spinner size={18} />
              </span>
            </div>
            <div className="text-sm font-semibold text-slate-100">Connecting to the Courtside backend</div>
            <div className="mt-1.5 text-xs leading-relaxed text-mute">
              {backendUp === false
                ? 'No answer yet from localhost:8000. Start the backend and this page will pick it up on its own.'
                : 'Loading games, positions and the agent’s state…'}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** `g` then d/p/b/s jumps between pages. */
function useNavKeys() {
  const navigate = useNavigate()
  const armed = useRef(0)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const k = e.key.toLowerCase()
      if (k === 'g') {
        armed.current = Date.now()
        return
      }
      if (Date.now() - armed.current < 900) {
        const hit = NAV.find((n) => n.key === k)
        if (hit) navigate(hit.to)
        armed.current = 0
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])
}

export default function Layout() {
  useNavKeys()
  return (
    <div className="flex h-full overflow-hidden">
      <Rail />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="relative min-h-0 flex-1 overflow-hidden">
          <Outlet />
          <ConnectingBanner />
        </main>
      </div>
      <Toasts />
    </div>
  )
}

export function Page({
  title,
  subtitle,
  right,
  children,
}: {
  title: string
  subtitle?: string
  right?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1320px] px-6 pb-16 pt-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-50">{title}</h1>
            {subtitle && <p className="mt-1 text-xs text-mute">{subtitle}</p>}
          </div>
          {right}
        </div>
        {children}
      </div>
    </div>
  )
}
