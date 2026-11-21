import { AnimatePresence, motion } from 'framer-motion'
import clsx from 'clsx'
import { AlertTriangle, Bot, CheckCircle2, Goal, Info, LayoutGrid, Settings2, Wallet, X, XCircle } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { money, pnlColor } from '../format'
import { useStore, type Toast } from '../store'
import type { AgentStatus } from '../types'
import { LiveDot, Spinner, Ticker } from './ui'

const NAV = [
  { to: '/', label: 'NBA', key: 'm', icon: LayoutGrid },
  { to: '/soccer', label: 'Soccer', key: 'f', icon: Goal },
  { to: '/portfolio', label: 'Portfolio', key: 'p', icon: Wallet },
  { to: '/agent', label: 'Agent', key: 'a', icon: Bot },
  { to: '/settings', label: 'Settings', key: 's', icon: Settings2 },
]

const isActive = (to: string, pathname: string) =>
  to === '/' ? pathname === '/' || pathname.startsWith('/game') : pathname.startsWith(to)

/** How the agent's state is shown wherever it appears. */
export const agentTone: Record<AgentStatus['state'], { color: string; label: string }> = {
  paused: { color: '#6f7179', label: 'Paused' },
  idle: { color: '#8fa3ff', label: 'Waiting' },
  watching: { color: '#8fa3ff', label: 'Watching' },
  acting: { color: '#19c37d', label: 'Trading' },
}

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label="Courtside home">
      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white">
        <span className="h-2.5 w-2.5 rounded-full bg-ink-950" />
      </span>
      <span className="text-[17px] font-semibold tracking-tight text-white">Courtside</span>
    </Link>
  )
}

/** Paper or live, and whether the games are practice games. The two facts a user must never be unsure of. */
function ModeBadges() {
  const settings = useStore((s) => s.app?.settings)
  if (!settings) return null
  const live = settings.trading_mode === 'live'
  return (
    <div className="flex items-center gap-1.5">
      <Link
        to="/settings"
        title={live ? 'Orders go to your real Kalshi account' : 'Pretend money: no real orders are sent'}
        className={clsx(
          'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium',
          live ? 'bg-coral/15 text-coral' : 'bg-white/[0.07] text-slate-200',
        )}
      >
        {live && <LiveDot color="#f2594b" size={6} />}
        {live ? 'Live money' : 'Paper'}
      </Link>
      {settings.data_source === 'sim' && (
        <Link
          to="/settings"
          title="These are practice games with made-up scores and prices"
          className="hidden whitespace-nowrap rounded-full bg-gold/[0.13] px-2.5 py-1 text-xs font-medium text-gold lg:inline-flex"
        >
          Practice games
        </Link>
      )}
    </div>
  )
}

/** Phone navigation: a tab bar along the bottom, where a thumb can reach it. */
function TabBar() {
  const { pathname } = useLocation()
  return (
    <nav className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-hair bg-ink-950/95 backdrop-blur md:hidden">
      <div className="grid h-16 grid-cols-5">
        {NAV.map((n) => {
          const active = isActive(n.to, pathname)
          const Icon = n.icon
          return (
            <NavLink
              key={n.to}
              to={n.to}
              className={clsx('flex flex-col items-center justify-center gap-1 text-[11px] font-medium', active ? 'text-white' : 'text-dim')}
            >
              <Icon size={21} strokeWidth={active ? 2.2 : 1.8} />
              {n.label}
            </NavLink>
          )
        })}
      </div>
    </nav>
  )
}

function TopNav() {
  const app = useStore((s) => s.app)
  const account = app?.account
  const agent = app?.agent
  const tone = agent ? agentTone[agent.state] : agentTone.paused
  const { pathname } = useLocation()

  return (
    <header className="sticky top-0 z-40 border-b border-hair bg-ink-950/90 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1180px] items-center gap-3 px-4 sm:px-8 md:h-16 md:gap-6">
        <Logo />
        <nav className="hidden items-center gap-1 md:flex">
          {NAV.map((n) => {
            const active = isActive(n.to, pathname)
            return (
              <NavLink
                key={n.to}
                to={n.to}
                className={clsx(
                  'rounded-full px-2.5 py-2 text-sm font-medium transition-colors md:px-3.5',
                  active ? 'bg-white/[0.08] text-white' : 'text-mute hover:text-white',
                )}
              >
                {n.label}
              </NavLink>
            )
          })}
        </nav>

        <div className="ml-auto flex shrink-0 items-center gap-3 md:gap-4">
          <ModeBadges />
          <Link
            to="/agent"
            title={agent?.focus || 'Agent'}
            className="hidden items-center gap-2 whitespace-nowrap rounded-full px-2 py-1 text-xs text-mute transition-colors hover:text-white lg:flex"
          >
            <LiveDot color={tone.color} pulse={agent?.state === 'acting'} size={7} />
            Agent {agent ? tone.label.toLowerCase() : ''}
          </Link>
          <Link to="/portfolio" className="shrink-0 whitespace-nowrap text-right leading-tight" title="Your account">
            {account ? (
              <>
                <Ticker value={account.equity} format={(n) => money(n)} flash={false} className="block text-sm font-semibold text-white" />
                <span className={clsx('num block text-xs', pnlColor(account.pnl_today))}>
                  {money(account.pnl_today, { sign: true })} today
                </span>
              </>
            ) : (
              <div className="skeleton h-8 w-20" />
            )}
          </Link>
        </div>
      </div>
    </header>
  )
}

const toastIcon = {
  info: <Info size={16} className="text-slate-200" />,
  success: <CheckCircle2 size={16} className="text-mint" />,
  warn: <AlertTriangle size={16} className="text-gold" />,
  error: <XCircle size={16} className="text-coral" />,
}

function ToastItem({ t }: { t: Toast }) {
  const dismiss = useStore((s) => s.dismissToast)
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      transition={{ duration: 0.18 }}
      className="pointer-events-auto flex w-full items-start gap-3 rounded-2xl border border-hair bg-ink-800 p-3.5 shadow-lift md:w-[340px]"
    >
      <div className="mt-0.5">{toastIcon[t.level]}</div>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold text-white">{t.title}</div>
        {t.body && <div className="mt-0.5 text-[13px] leading-snug text-mute">{t.body}</div>}
      </div>
      <button onClick={() => dismiss(t.id)} className="text-dim hover:text-white" aria-label="Dismiss">
        <X size={14} />
      </button>
    </motion.div>
  )
}

function Toasts() {
  const toasts = useStore((s) => s.toasts)
  return (
    <div className="pointer-events-none fixed inset-x-3 bottom-[calc(80px+env(safe-area-inset-bottom))] z-[60] flex flex-col items-stretch gap-2 md:inset-x-auto md:bottom-5 md:right-5 md:items-end">
      <AnimatePresence initial={false}>
        {toasts.slice(-3).map((t) => (
          <ToastItem key={t.id} t={t} />
        ))}
      </AnimatePresence>
    </div>
  )
}

/** Shown until the first data arrives, and again if the connection drops for good. */
function ConnectionNotice() {
  const app = useStore((s) => s.app)
  const backendUp = useStore((s) => s.backendUp)
  const connected = useStore((s) => s.connected)
  if (app && connected) return null
  if (app && !connected) {
    return (
      <div className="border-b border-hair bg-gold/[0.08] py-2 text-center text-[13px] text-gold">
        Reconnecting… prices on screen may be a few seconds old.
      </div>
    )
  }
  return (
    <div className="flex items-center justify-center gap-2.5 py-24 text-sm text-mute">
      <Spinner size={16} />
      {backendUp === false ? 'Waiting for the Courtside server to answer…' : 'Loading your desk…'}
    </div>
  )
}

/** `g` then m/p/a/s jumps between pages. */
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
  const app = useStore((s) => s.app)
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo({ top: 0 }) // newer browsers return a promise here, so do not hand it back to React
  }, [pathname])
  return (
    <div className="min-h-full">
      <TopNav />
      <ConnectionNotice />
      <main className="pb-tabbar md:pb-0">{app ? <Outlet /> : null}</main>
      <TabBar />
      <Toasts />
    </div>
  )
}

/** Standard page frame: centred column, a title, and one line saying what the page is for. */
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
    <div className="page">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="h-page">{title}</h1>
          {subtitle && <p className="hint mt-1">{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </div>
  )
}
