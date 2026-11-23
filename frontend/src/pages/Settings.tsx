import clsx from 'clsx'
import { AlertTriangle, Check, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import { Button, Card, Dialog, Skeleton, Slider, Toggle } from '../components/ui'
import { money, relTime } from '../format'
import { useStore } from '../store'
import type { FeedStatus, Settings as SettingsT } from '../types'

type NumKey = 'max_stake_per_trade' | 'max_open_positions' | 'max_daily_loss' | 'max_total_exposure' | 'sim_speed'

const LIMITS: { key: NumKey; label: string; help: string; min: number; max: number; step: number; unit: '$' | '' }[] = [
  { key: 'max_stake_per_trade', label: 'Most on one trade', help: 'The most that can go on a single trade, by the agent or by you.', min: 10, max: 1000, step: 10, unit: '$' },
  { key: 'max_total_exposure', label: 'Most at risk at once', help: 'The most that can be tied up across all open positions.', min: 50, max: 5000, step: 50, unit: '$' },
  { key: 'max_daily_loss', label: 'Stop for the day after losing', help: 'Once it is down this much today, the agent stops opening new trades.', min: 10, max: 2000, step: 10, unit: '$' },
  { key: 'max_open_positions', label: 'Open positions at once', help: 'How many trades can be open at the same time.', min: 1, max: 20, step: 1, unit: '' },
]

const GREEN = '#19c37d'
const RED = '#f2594b'

/** One big either/or choice, shown as a row with a radio mark. */
function Choice({
  active,
  onClick,
  title,
  body,
  disabled,
  danger,
}: {
  active: boolean
  onClick: () => void
  title: string
  body: string
  disabled?: boolean
  danger?: boolean
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'flex w-full items-start gap-3.5 rounded-2xl border px-4 py-3.5 text-left transition-colors disabled:opacity-50',
        active ? (danger ? 'border-coral/60 bg-coral/[0.07]' : 'border-white/40 bg-white/[0.04]') : 'border-hair hover:bg-white/[0.035]',
      )}
    >
      <span
        className={clsx(
          'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border',
          active ? (danger ? 'border-coral bg-coral text-white' : 'border-white bg-white text-ink-950') : 'border-hair2',
        )}
      >
        {active && <Check size={12} strokeWidth={3} />}
      </span>
      <span className="min-w-0">
        <span className="block text-[15px] font-semibold text-white">{title}</span>
        <span className="hint mt-0.5 block">{body}</span>
      </span>
    </button>
  )
}

function StatusRow({ ok, name, detail, right }: { ok: boolean; name: string; detail: string; right?: string }) {
  return (
    <div className="flex items-center gap-3 border-b border-hair py-3 last:border-b-0">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: ok ? GREEN : RED }} />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-white">{name}</div>
        <div className="break-words text-xs text-dim" title={detail}>
          {detail}
        </div>
      </div>
      {right && <span className="num shrink-0 text-xs text-dim">{right}</span>}
    </div>
  )
}

function feedDetail(feed: FeedStatus) {
  return feed.detail || (feed.ok ? 'Working' : 'Not responding')
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="h-section">{title}</h2>
      {hint && <p className="hint mt-1">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
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
      toast({ level: 'info', title: 'New practice games', body: 'A fresh set of practice games is tipping off.' })
    } catch (e) {
      toast({ level: 'error', title: 'Could not start new practice games', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(null)
    }
  }

  if (!settings || !health) {
    return (
      <div className="page">
        <div className="mx-auto max-w-[720px]">
          <h1 className="h-page">Settings</h1>
          <p className="hint mt-1">How you trade, what data you see, your safety limits and your connections.</p>
          <div className="mt-6 space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[150px] w-full !rounded-xl2" />
            ))}
          </div>
        </div>
      </div>
    )
  }

  const live = settings.trading_mode === 'live'
  const sim = settings.data_source === 'sim'
  const val = (k: NumKey) => draft[k] ?? settings[k]
  const account = health.kalshi_env === 'demo' ? 'demo' : 'real'
  const liveBlockers: string[] = []
  if (!health.kalshi_keys) liveBlockers.push('add your Kalshi API keys to the server')
  if (sim) liveBlockers.push('switch Data to Real games')

  return (
    <div className="page">
      <div className="mx-auto max-w-[720px]">
        <h1 className="h-page">Settings</h1>
        <p className="hint mt-1">How you trade, what data you see, your safety limits and your connections.</p>

        <div className="mt-8 space-y-10">
          <Section title="Trading mode" hint="Paper is for practice. Live sends real orders.">
            <div role="radiogroup" aria-label="Trading mode" className="space-y-2.5">
              <Choice
                active={!live}
                onClick={() => live && void save({ trading_mode: 'paper' }, 'paper')}
                title="Paper"
                body="Practice with pretend money. Nothing is sent to Kalshi."
                disabled={busy === 'paper'}
              />
              <Choice
                active={live}
                danger
                onClick={() => {
                  if (live) return
                  setTyped('')
                  setLiveError(null)
                  setLiveOpen(true)
                }}
                title="Live"
                body={`Real orders on your ${account} Kalshi account, kept inside the safety limits below.`}
              />
            </div>
            {!live && liveBlockers.length > 0 && (
              <div className="mt-3 flex items-start gap-2 text-[13px] text-mute">
                <AlertTriangle size={14} className="mt-0.5 shrink-0 text-gold" />
                <span>Before you can go live: {liveBlockers.join(', and ')}.</span>
              </div>
            )}
          </Section>

          <Section title="Data" hint="Which games the desk shows.">
            <div role="radiogroup" aria-label="Data" className="space-y-2.5">
              <Choice
                active={sim}
                onClick={() => !sim && void save({ data_source: 'sim' }, 'data')}
                title="Practice games"
                body="Made-up games and prices that run any time of day. Good for learning the desk and for letting the agent rehearse."
                disabled={busy === 'data' || live}
              />
              <Choice
                active={!sim}
                onClick={() => sim && void save({ data_source: 'live' }, 'data')}
                title="Real games"
                body="Real NBA scores, real FanDuel lines and real Kalshi prices."
                disabled={busy === 'data'}
              />
            </div>
            {live && <p className="hint mt-3">Practice games are unavailable while live trading is on.</p>}
            {sim && (
              <Card className="mt-3 px-5 py-4">
                <div className="flex flex-wrap items-end gap-5">
                  <div className="min-w-[200px] flex-1">
                    <div className="flex items-baseline justify-between">
                      <span className="text-sm font-medium text-slate-200">Practice speed</span>
                      <span className="num text-sm font-semibold text-white">{val('sim_speed')}×</span>
                    </div>
                    <div className="mt-1.5">
                      <Slider value={val('sim_speed')} min={1} max={60} step={1} onChange={(v) => setNum('sim_speed', v)} tone="#f4f4f5" ariaLabel="Practice speed" />
                    </div>
                    <p className="hint mt-0.5">How fast the practice game clock runs compared with real time.</p>
                  </div>
                  <Button onClick={resetSim} loading={busy === 'reset'} className="shrink-0">
                    {busy !== 'reset' && <RefreshCw size={13} />} New games
                  </Button>
                </div>
              </Card>
            )}
          </Section>

          <Section title="Agent">
            <Card className="px-5">
              <div className="flex items-center gap-4 border-b border-hair py-4">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-white">Trade on its own</div>
                  <div className="hint mt-0.5">When on, the agent buys and sells by itself inside your limits. When off, it only watches.</div>
                </div>
                <Toggle
                  checked={settings.agent_enabled}
                  label="Agent trades on its own"
                  tone={GREEN}
                  onChange={async (v) => {
                    try {
                      setApp(v ? await api.startAgent() : await api.pauseAgent())
                    } catch (e) {
                      toast({ level: 'error', title: 'Could not reach the agent', body: e instanceof ApiError ? e.message : '' })
                    }
                  }}
                />
              </div>
              <div className="flex items-center gap-4 py-4">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-white">Claude checks each buy</div>
                  <div className="hint mt-0.5">
                    Before a real-game order goes out, Claude checks it against your guidance and past lessons, and can stop it or
                    make it smaller.
                    {!health.anthropic && <span className="text-gold"> Needs Claude to be connected (see below).</span>}
                  </div>
                </div>
                <Toggle checked={settings.claude_review} label="Claude checks each buy" tone={GREEN} onChange={(v) => void save({ claude_review: v })} />
              </div>
            </Card>
          </Section>

          <Section title="Safety limits" hint="Hard caps. The agent cannot go past these in paper or live mode, whatever it has learned.">
            <Card className="px-5">
              {LIMITS.map((l) => {
                const v = val(l.key)
                return (
                  <div key={l.key} className="border-b border-hair py-4 last:border-b-0">
                    <div className="flex items-center justify-between gap-3">
                      <label className="text-sm font-medium text-slate-200">{l.label}</label>
                      <div className="flex items-center gap-1 rounded-lg bg-ink-800 px-2.5 py-1 focus-within:ring-1 focus-within:ring-white/40">
                        {l.unit === '$' && <span className="num text-[13px] text-dim">$</span>}
                        <input
                          type="number"
                          value={v}
                          min={l.step}
                          step={l.step}
                          aria-label={l.label}
                          onChange={(e) => {
                            const n = Number(e.target.value)
                            if (!Number.isNaN(n) && n > 0) setNum(l.key, n)
                          }}
                          className="num w-16 bg-transparent text-right text-sm font-semibold text-white outline-none"
                        />
                      </div>
                    </div>
                    <div className="mt-2">
                      <Slider value={Math.min(v, l.max)} min={l.min} max={l.max} step={l.step} onChange={(n) => setNum(l.key, n)} tone="#f4f4f5" ariaLabel={l.label} />
                    </div>
                    <p className="hint mt-0.5">{l.help}</p>
                  </div>
                )
              })}
            </Card>
          </Section>

          <Section title="Connections" hint="Keys are set on the server. A green dot means it is connected and working.">
            <Card className="px-5">
              <StatusRow
                ok={health.kalshi_keys}
                name="Kalshi account"
                detail={health.kalshi_keys ? `Keys found for your ${account} account` : 'No keys found. Needed for live trading only.'}
              />
              <StatusRow
                ok={health.anthropic}
                name="Claude"
                detail={health.anthropic ? 'Connected: chat, checking buys and writing lessons' : 'Not connected. Add ANTHROPIC_API_KEY to chat with the agent.'}
              />
              <StatusRow
                ok={health.odds_api}
                name="FanDuel lines"
                detail={health.odds_api ? 'Connected through The Odds API' : 'Not connected. Add ODDS_API_KEY to see FanDuel lines.'}
              />
              <StatusRow
                ok={health.feeds.scores.ok}
                name="Scores"
                detail={feedDetail(health.feeds.scores)}
                right={health.feeds.scores.updated_at ? relTime(health.feeds.scores.updated_at) : 'never'}
              />
              <StatusRow
                ok={health.feeds.kalshi.ok}
                name="Kalshi prices"
                detail={feedDetail(health.feeds.kalshi)}
                right={health.feeds.kalshi.updated_at ? relTime(health.feeds.kalshi.updated_at) : 'never'}
              />
              <StatusRow
                ok={health.feeds.fanduel.ok}
                name="FanDuel feed"
                detail={feedDetail(health.feeds.fanduel)}
                right={health.feeds.fanduel.updated_at ? relTime(health.feeds.fanduel.updated_at) : 'never'}
              />
            </Card>
          </Section>
        </div>
      </div>

      <Dialog
        open={liveOpen}
        onClose={() => busy !== 'live' && setLiveOpen(false)}
        title="Switch to live trading?"
        subtitle="Orders will be sent to your real Kalshi account."
        width={440}
      >
        <p className="rounded-2xl bg-coral/[0.1] px-4 py-3 text-[13px] leading-relaxed text-slate-200">
          The agent will be able to buy and sell with real money: up to{' '}
          <span className="num font-semibold text-white">{money(settings.max_stake_per_trade, { decimals: 0 })}</span> a trade and{' '}
          <span className="num font-semibold text-white">{money(settings.max_total_exposure, { decimals: 0 })}</span> in total, and it stops for the day after a{' '}
          <span className="num font-semibold text-white">{money(settings.max_daily_loss, { decimals: 0 })}</span> loss. You can switch back to paper at any time.
        </p>
        <label className="mt-4 block text-[13px] text-mute" htmlFor="live-confirm">
          Type <span className="font-semibold text-coral">LIVE</span> to confirm
        </label>
        <input
          id="live-confirm"
          autoFocus
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && typed.trim() === 'LIVE') void goLive()
          }}
          placeholder="LIVE"
          className="field num mt-1.5 !text-base tracking-[0.3em]"
        />
        {liveError && <div className="mt-3 rounded-2xl bg-coral/[0.12] px-4 py-2.5 text-[13px] text-coral">{liveError}</div>}
        <div className="mt-5 flex gap-2">
          <Button variant="ghost" size="md" className="flex-1" onClick={() => setLiveOpen(false)} disabled={busy === 'live'}>
            Stay on paper
          </Button>
          <Button variant="coral" size="md" className="flex-[2]" disabled={typed.trim() !== 'LIVE'} loading={busy === 'live'} onClick={goLive}>
            Turn on live trading
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
