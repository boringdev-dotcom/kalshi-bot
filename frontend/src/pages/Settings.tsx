import clsx from 'clsx'
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Database,
  FlaskConical,
  KeyRound,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import { Page } from '../components/Layout'
import { Badge, Button, Card, Dialog, LiveDot, SectionTitle, Skeleton, Slider, Toggle } from '../components/ui'
import { money, relTime } from '../format'
import { useStore } from '../store'
import type { FeedStatus, Settings as SettingsT } from '../types'

type NumKey = 'max_stake_per_trade' | 'max_open_positions' | 'max_daily_loss' | 'max_total_exposure' | 'sim_speed'

const LIMITS: { key: NumKey; label: string; help: string; min: number; max: number; step: number; unit: '$' | '' }[] = [
  { key: 'max_stake_per_trade', label: 'Max stake per trade', help: 'The most the agent (or a ticket) can put into one position.', min: 10, max: 1000, step: 10, unit: '$' },
  { key: 'max_total_exposure', label: 'Max total exposure', help: 'Cap on money at risk across all open positions.', min: 50, max: 5000, step: 50, unit: '$' },
  { key: 'max_daily_loss', label: 'Max daily loss', help: 'The agent stops opening trades for the day once it is down this much.', min: 10, max: 2000, step: 10, unit: '$' },
  { key: 'max_open_positions', label: 'Max open positions', help: 'How many positions can be open at once.', min: 1, max: 20, step: 1, unit: '' },
]

function OptionCard({
  active,
  onClick,
  icon,
  title,
  body,
  tone,
  disabled,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  title: string
  body: string
  tone: string
  disabled?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'relative flex-1 rounded-xl border p-4 text-left transition-all duration-150 disabled:opacity-50',
        active ? 'bg-white/[0.04]' : 'border-hair bg-ink-950/40 hover:border-white/[0.14] hover:bg-white/[0.02]',
      )}
      style={active ? { borderColor: `${tone}80`, boxShadow: `0 0 0 1px ${tone}40, 0 10px 40px -14px ${tone}55` } : undefined}
    >
      <div className="flex items-center gap-2">
        <span style={{ color: active ? tone : '#8d96a8' }}>{icon}</span>
        <span className="text-sm font-semibold text-slate-50">{title}</span>
        {active && (
          <span className="ml-auto rounded-md px-1.5 py-[1px] text-[10px] font-bold uppercase tracking-wider" style={{ color: tone, background: `${tone}22` }}>
            Active
          </span>
        )}
      </div>
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-mute">{body}</p>
    </button>
  )
}

function FeedRow({ name, feed }: { name: string; feed: FeedStatus }) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <LiveDot color={feed.ok ? '#3ddc97' : '#ff6b6b'} pulse={!feed.ok} />
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium text-slate-100">{name}</div>
        <div className="truncate text-[11px] text-dim" title={feed.detail}>
          {feed.detail || (feed.ok ? 'Healthy' : 'Not responding')}
        </div>
      </div>
      <span className="num shrink-0 text-[10.5px] text-dim">{feed.updated_at ? relTime(feed.updated_at) : 'never'}</span>
    </div>
  )
}

function KeyRow({ name, ok, detail }: { name: string; ok: boolean; detail: string }) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      {ok ? <CheckCircle2 size={15} className="shrink-0 text-mint" /> : <XCircle size={15} className="shrink-0 text-dim" />}
      <div className="min-w-0 flex-1">
        <div className="text-xs font-medium text-slate-100">{name}</div>
        <div className="text-[11px] text-dim">{detail}</div>
      </div>
      <Badge tone={ok ? 'mint' : 'slate'}>{ok ? 'Found' : 'Missing'}</Badge>
    </div>
  )
}

export default function Settings() {
  const app = useStore((s) => s.app)
  const setApp = useStore((s) => s.setApp)
  const toast = useStore((s) => s.toast)
  const hydrate = useStore((s) => s.hydrate)

  const [draft, setDraft] = useState<Partial<Record<NumKey, number>>>({})
  const pending = useRef<Partial<SettingsT>>({})
  const timer = useRef<number | null>(null)
  const [liveOpen, setLiveOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [liveError, setLiveError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const settings = app?.settings
  const health = app?.health

  const save = useCallback(
    async (patch: Partial<SettingsT>, tag?: string) => {
      if (tag) setBusy(tag)
      try {
        setApp(await api.updateSettings(patch))
        return true
      } catch (e) {
        toast({ level: 'error', title: 'Setting not saved', body: e instanceof ApiError ? e.message : '' })
        return false
      } finally {
        if (tag) setBusy(null)
      }
    },
    [setApp, toast],
  )

  const flush = useCallback(async () => {
    const patch = pending.current
    pending.current = {}
    if (Object.keys(patch).length === 0) return
    await save(patch)
    // Fall back to the server's value whether or not the save went through.
    setDraft((d) => {
      const next = { ...d }
      for (const k of Object.keys(patch)) if (!(k in pending.current)) delete next[k as NumKey]
      return next
    })
  }, [save])

  useEffect(
    () => () => {
      if (timer.current) {
        window.clearTimeout(timer.current)
        void flush()
      }
    },
    [flush],
  )

  const setNum = (key: NumKey, v: number) => {
    setDraft((d) => ({ ...d, [key]: v }))
    pending.current[key] = v
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      timer.current = null
      void flush()
    }, 450)
  }

  const goLive = async () => {
    setLiveError(null)
    setBusy('live')
    try {
      setApp(await api.updateSettings({ trading_mode: 'live' }))
      setLiveOpen(false)
      setTyped('')
      toast({ level: 'warn', title: 'Live trading is on', body: 'Orders now go to your real Kalshi account, inside your limits.' })
    } catch (e) {
      setLiveError(e instanceof ApiError ? e.message : 'Could not switch to live trading.')
    } finally {
      setBusy(null)
    }
  }

  const resetSim = async () => {
    setBusy('reset')
    try {
      setApp(await api.resetSim())
      await hydrate()
      toast({ level: 'info', title: 'New simulated slate', body: 'Fresh simulated games are tipping off.' })
    } catch (e) {
      toast({ level: 'error', title: 'Could not reset the simulation', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(null)
    }
  }

  if (!settings || !health) {
    return (
      <Page title="Settings" subtitle="Trading mode, data, limits and connections.">
        <div className="grid gap-3 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[220px] w-full !rounded-xl2" />
          ))}
        </div>
      </Page>
    )
  }

  const live = settings.trading_mode === 'live'
  const sim = settings.data_source === 'sim'
  const val = (k: NumKey) => draft[k] ?? settings[k]
  const liveBlockers: string[] = []
  if (!health.kalshi_keys) liveBlockers.push('Kalshi API keys are missing from .env')
  if (sim) liveBlockers.push('Data source is Simulation — switch to Live data first')

  return (
    <Page title="Settings" subtitle="Trading mode, data, limits and connections.">
      <div className="grid items-start gap-3 lg:grid-cols-2">
        {/* Trading mode */}
        <Card className="p-5">
          <SectionTitle right={<Badge tone={live ? 'coral' : 'peri'}>{live ? 'Real money' : 'No real money'}</Badge>}>Trading mode</SectionTitle>
          <div className="mt-3 flex gap-3">
            <OptionCard
              active={!live}
              onClick={() => live && void save({ trading_mode: 'paper' }, 'paper')}
              icon={<ShieldCheck size={16} />}
              title="Paper"
              body="Orders fill against real prices but no order reaches Kalshi. Safe for testing the agent."
              tone="#8b9cff"
              disabled={busy === 'paper'}
            />
            <OptionCard
              active={live}
              onClick={() => {
                if (live) return
                setTyped('')
                setLiveError(null)
                setLiveOpen(true)
              }}
              icon={<ShieldAlert size={16} />}
              title="Live"
              body={`Real orders on your Kalshi ${health.kalshi_env === 'demo' ? 'demo' : 'production'} account, capped by the limits on this page.`}
              tone="#ff6b6b"
            />
          </div>
          {!live && liveBlockers.length > 0 && (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-hair bg-white/[0.02] px-3 py-2 text-[11.5px] text-mute">
              <AlertTriangle size={13} className="mt-0.5 shrink-0 text-gold" />
              <span>Before going live: {liveBlockers.join('; ')}.</span>
            </div>
          )}
        </Card>

        {/* Data source */}
        <Card className="p-5">
          <SectionTitle right={sim ? <Badge tone="gold">Simulated</Badge> : <Badge tone="mint">Real feeds</Badge>}>Data source</SectionTitle>
          <div className="mt-3 flex gap-3">
            <OptionCard
              active={sim}
              onClick={() => !sim && void save({ data_source: 'sim' }, 'data')}
              icon={<FlaskConical size={16} />}
              title="Simulation"
              body="Made-up games, odds and Kalshi prices. Good for demos and for training the agent off-hours."
              tone="#f5b74e"
              disabled={busy === 'data' || live}
            />
            <OptionCard
              active={!sim}
              onClick={() => sim && void save({ data_source: 'live' }, 'data')}
              icon={<Database size={16} />}
              title="Live data"
              body="Real NBA scores, FanDuel lines and the Kalshi totals ladder."
              tone="#3ddc97"
              disabled={busy === 'data'}
            />
          </div>
          {sim && (
            <div className="mt-4 flex items-end gap-4">
              <div className="flex-1">
                <div className="mb-1 flex items-baseline justify-between">
                  <span className="text-xs text-slate-300">Simulation speed</span>
                  <span className="num text-xs font-semibold text-slate-50">{val('sim_speed')}×</span>
                </div>
                <Slider value={val('sim_speed')} min={1} max={60} step={1} onChange={(v) => setNum('sim_speed', v)} tone="#f5b74e" ariaLabel="Simulation speed" />
                <p className="mt-0.5 text-[10.5px] text-dim">How fast the simulated game clock runs compared with real time.</p>
              </div>
              <Button onClick={resetSim} loading={busy === 'reset'} className="mb-4 shrink-0">
                {busy !== 'reset' && <RefreshCw size={12} />} New slate
              </Button>
            </div>
          )}
          {live && sim === false && (
            <p className="mt-3 text-[11px] text-dim">Simulation is unavailable while live trading is on.</p>
          )}
        </Card>

        {/* Risk limits */}
        <Card className="p-5">
          <SectionTitle>Risk limits</SectionTitle>
          <p className="mt-1 text-[11px] leading-relaxed text-dim">
            Hard caps. The agent cannot exceed these in paper or live mode, whatever it has learned.
          </p>
          <div className="mt-3 divide-y divide-hair">
            {LIMITS.map((l) => {
              const v = val(l.key)
              return (
                <div key={l.key} className="py-3">
                  <div className="flex items-center justify-between gap-3">
                    <label className="text-xs font-medium text-slate-200">{l.label}</label>
                    <div className="flex items-center gap-1 rounded-md border border-hair2 bg-ink-950/60 px-2 py-1 focus-within:border-peri/60">
                      {l.unit === '$' && <span className="num text-[11px] text-dim">$</span>}
                      <input
                        type="number"
                        value={v}
                        min={l.step}
                        step={l.step}
                        onChange={(e) => {
                          const n = Number(e.target.value)
                          if (!Number.isNaN(n) && n > 0) setNum(l.key, n)
                        }}
                        className="num w-16 bg-transparent text-right text-xs font-semibold text-slate-50 outline-none"
                      />
                    </div>
                  </div>
                  <div className="mt-1.5">
                    <Slider value={Math.min(v, l.max)} min={l.min} max={l.max} step={l.step} onChange={(n) => setNum(l.key, n)} tone="#8b9cff" ariaLabel={l.label} />
                  </div>
                  <p className="text-[10.5px] text-dim">{l.help}</p>
                </div>
              )
            })}
          </div>
        </Card>

        <div className="space-y-3">
          {/* Agent */}
          <Card className="p-5">
            <SectionTitle>Agent</SectionTitle>
            <div className="mt-2 divide-y divide-hair">
              <div className="flex items-center gap-3 py-3">
                <Bot size={16} className="shrink-0 text-peri" />
                <div className="flex-1">
                  <div className="text-xs font-medium text-slate-100">Trade on its own</div>
                  <div className="text-[11px] leading-snug text-dim">
                    When on, the agent enters and exits by itself inside your limits. When off it only watches.
                  </div>
                </div>
                <Toggle
                  checked={settings.agent_enabled}
                  label="Agent enabled"
                  onChange={async (v) => {
                    try {
                      setApp(v ? await api.startAgent() : await api.pauseAgent())
                    } catch (e) {
                      toast({ level: 'error', title: 'Could not reach the agent', body: e instanceof ApiError ? e.message : '' })
                    }
                  }}
                />
              </div>
              <div className="flex items-center gap-3 py-3">
                <Sparkles size={16} className="shrink-0 text-gold" />
                <div className="flex-1">
                  <div className="text-xs font-medium text-slate-100">Claude reviews each entry</div>
                  <div className="text-[11px] leading-snug text-dim">
                    Before an order goes out, Claude checks it against your guidance and past lessons and can veto or resize it.
                    {!health.anthropic && <span className="text-gold"> Needs an Anthropic API key.</span>}
                  </div>
                </div>
                <Toggle checked={settings.claude_review} label="Claude review" tone="#f5b74e" onChange={(v) => void save({ claude_review: v })} />
              </div>
            </div>
          </Card>

          {/* Health */}
          <Card className="p-5">
            <SectionTitle right={<span className="flex items-center gap-1.5 text-[11px] text-dim"><Activity size={12} /> live status</span>}>
              Connections
            </SectionTitle>
            <div className="mt-2 grid gap-x-6 md:grid-cols-2">
              <div className="divide-y divide-hair">
                <div className="flex items-center gap-1.5 pb-1 pt-2 text-[10.5px] font-semibold uppercase tracking-wider text-dim">
                  <KeyRound size={11} /> Keys in .env
                </div>
                <KeyRow name="Kalshi API key" ok={health.kalshi_keys} detail={`Environment: ${health.kalshi_env === 'demo' ? 'demo' : 'production'}`} />
                <KeyRow name="Anthropic (Claude)" ok={health.anthropic} detail="Chat, entry review and reflection" />
                <KeyRow name="The Odds API" ok={health.odds_api} detail="FanDuel lines" />
              </div>
              <div className="divide-y divide-hair">
                <div className="flex items-center gap-1.5 pb-1 pt-2 text-[10.5px] font-semibold uppercase tracking-wider text-dim">
                  <Activity size={11} /> Feeds
                </div>
                <FeedRow name="Scores" feed={health.feeds.scores} />
                <FeedRow name="Kalshi markets" feed={health.feeds.kalshi} />
                <FeedRow name="FanDuel odds" feed={health.feeds.fanduel} />
              </div>
            </div>
          </Card>
        </div>
      </div>

      <Dialog
        open={liveOpen}
        onClose={() => busy !== 'live' && setLiveOpen(false)}
        title="Switch to live trading?"
        subtitle="Orders will be sent to your real Kalshi account."
        accent="#ff6b6b"
        width={440}
      >
        <div className="rounded-xl border border-coral/20 bg-coral/[0.07] px-3.5 py-3 text-[11.5px] leading-relaxed text-slate-300">
          The agent will be able to buy and sell with real money, up to{' '}
          <span className="num font-semibold text-slate-50">{money(settings.max_stake_per_trade, { decimals: 0 })}</span> a trade and{' '}
          <span className="num font-semibold text-slate-50">{money(settings.max_total_exposure, { decimals: 0 })}</span> in total, and it stops for the day at a{' '}
          <span className="num font-semibold text-slate-50">{money(settings.max_daily_loss, { decimals: 0 })}</span> loss. You can switch back to paper at any time.
        </div>
        <label className="mt-4 block text-xs text-mute">
          Type <span className="num font-semibold text-coral">LIVE</span> to confirm
        </label>
        <input
          autoFocus
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && typed.trim() === 'LIVE') void goLive()
          }}
          placeholder="LIVE"
          className="field num mt-1.5 !text-base tracking-[0.3em]"
        />
        {liveError && (
          <div className="mt-3 rounded-lg border border-coral/25 bg-coral/10 px-3 py-2 text-[11.5px] text-coral">{liveError}</div>
        )}
        <div className="mt-4 flex gap-2">
          <Button variant="ghost" size="md" className="flex-1" onClick={() => setLiveOpen(false)} disabled={busy === 'live'}>
            Stay on paper
          </Button>
          <Button variant="coral" size="md" className="flex-[2]" disabled={typed.trim() !== 'LIVE'} loading={busy === 'live'} onClick={goLive}>
            Turn on live trading
          </Button>
        </div>
      </Dialog>
    </Page>
  )
}
