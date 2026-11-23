import clsx from 'clsx'
import { ArrowLeft, ChevronDown } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import GameAnalysis from '../../components/game/GameAnalysis'
import SoccerOrderPanel, { type SPick } from '../../components/soccer/SoccerOrderPanel'
import { Button, Empty, LiveDot, Segmented, Skeleton } from '../../components/ui'
import { cents, money, pct, pnlColor, teamColor } from '../../format'
import { useMediaQuery } from '../../lib'
import { matchStatus, soccerApi, usePoll, type SDetail, type SEvent, type SMarket, type SMatch, type SPosition, type SSegment, type SSide } from '../../soccer'
import { useStore } from '../../store'
import { OrderSheet } from '../Game'
import { Crest } from './SoccerBoard'

function Scoreboard({ m }: { m: SMatch }) {
  const started = m.state !== 'pre'
  return (
    <div className="surface px-4 py-5 sm:px-6">
      <div className="flex items-center justify-center gap-2 text-[13px]">
        {m.state === 'live' && <LiveDot size={7} />}
        <span className={clsx('font-medium', m.state === 'live' ? 'text-mint' : 'text-mute')}>{matchStatus(m)}</span>
        <span className="text-dim">· {m.league_name}</span>
      </div>
      <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
        {[m.home, m.away].map((t, i) => (
          <div key={t.abbr} className={clsx('flex min-w-0 flex-col items-center gap-2 text-center', i === 1 && 'order-3')}>
            <Crest team={t} size={44} />
            <div className="w-full break-words text-[15px] font-semibold text-white">{t.short}</div>
            <div className="text-xs text-dim">
              {i === 0 ? 'Home' : 'Away'}
              {t.red_cards > 0 && <span className="ml-1.5 text-coral">· {t.red_cards} red</span>}
            </div>
          </div>
        ))}
        <div className="order-2 text-center">
          <div className="num text-4xl font-semibold text-white sm:text-5xl">{started ? `${m.home.score} – ${m.away.score}` : 'vs'}</div>
          {m.home.half_score != null && m.away.half_score != null && m.period >= 2 && (
            <div className="num mt-1 text-xs text-dim">
              Half time {m.home.half_score}–{m.away.half_score}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** The model's read: who wins and how many goals, next to Kalshi's line. */
function ModelLine({ d, segment }: { d: SDetail; segment: SSegment }) {
  const m = d.match
  const proj = m.projection?.[segment]
  if (!proj || m.state === 'final') return null
  const line = segment === 'match' ? m.total_line : d.first_half_line
  const cells = [
    { label: `${m.home.short} win`, value: pct(proj.p_home) },
    { label: 'Draw', value: pct(proj.p_draw) },
    { label: `${m.away.short} win`, value: pct(proj.p_away) },
    { label: 'Model goals', value: proj.total.toFixed(1) },
    { label: 'Kalshi line', value: line != null ? line.toFixed(1) : '—' },
  ]
  return (
    <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-5">
      {cells.map((c) => (
        <div key={c.label} className="rounded-xl bg-ink-800 px-3 py-2.5">
          <div className="break-words text-[11px] text-dim">{c.label}</div>
          <div className="num mt-0.5 text-[15px] font-semibold text-white">{c.value}</div>
        </div>
      ))}
    </div>
  )
}

function PriceButton({ m, side, pick, onPick, disabled }: { m: SMarket; side: SSide; pick: SPick | null; onPick: (p: SPick) => void; disabled: boolean }) {
  const ask = side === 'yes' ? m.yes_ask : m.no_ask
  const active = pick?.ticker === m.ticker && pick.side === side
  return (
    <button
      onClick={() => onPick({ ticker: m.ticker, side })}
      disabled={disabled || ask == null}
      className={clsx(
        'flex h-10 w-[84px] items-center justify-between rounded-full px-3 text-[13px] font-medium transition-colors disabled:opacity-30 sm:w-[92px]',
        active ? 'bg-white text-ink-950' : side === 'yes' ? 'bg-mint/[0.12] text-mint hover:bg-mint/20' : 'bg-coral/[0.12] text-coral hover:bg-coral/20',
      )}
    >
      <span>{side === 'yes' ? 'Yes' : 'No'}</span>
      <span className="num font-semibold">{cents(ask)}</span>
    </button>
  )
}

function MarketRow({ m, pick, onPick, closed }: { m: SMarket; pick: SPick | null; onPick: (p: SPick) => void; closed: boolean }) {
  const edge = m.edge_yes != null && m.edge_yes >= 0.03 ? 'yes' : m.edge_no != null && m.edge_no >= 0.03 ? 'no' : null
  return (
    <div className="flex items-center gap-3 border-b border-hair py-2.5 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="break-words text-[14px] font-medium text-white">{m.yes_label.replace(/^1st half: /, '')}</div>
        <div className="num text-xs text-dim">
          Model {m.p_yes != null ? pct(m.p_yes) : '—'}
          {edge && !closed && <span className="ml-1.5 text-gold">· {edge === 'yes' ? 'Yes' : 'No'} looks cheap</span>}
          {closed && m.p_yes != null && <span className="ml-1.5">· {m.p_yes >= 0.5 ? 'Yes won' : 'No won'}</span>}
        </div>
      </div>
      <PriceButton m={m} side="yes" pick={pick} onPick={onPick} disabled={closed} />
      <PriceButton m={m} side="no" pick={pick} onPick={onPick} disabled={closed} />
    </div>
  )
}

function MarketGroup({ title, hint, markets, pick, onPick, closed }: { title: string; hint?: string; markets: SMarket[]; pick: SPick | null; onPick: (p: SPick) => void; closed: boolean }) {
  if (!markets.length) return null
  return (
    <div className="mt-6">
      <div className="flex items-baseline gap-2">
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        {hint && <span className="text-xs text-dim">{hint}</span>}
      </div>
      <div className="mt-1">
        {markets.map((m) => (
          <MarketRow key={m.ticker} m={m} pick={pick} onPick={onPick} closed={closed} />
        ))}
      </div>
    </div>
  )
}

function StatBars({ d }: { d: SDetail }) {
  const order = ['Possession %', 'Shots', 'On target', 'Corners', 'Fouls', 'Yellow cards', 'Red cards', 'Saves', 'Offsides']
  const rows = order.filter((k) => d.stats[k])
  if (!rows.length) return null
  const { home, away } = d.match
  return (
    <div className="mt-4 space-y-2.5">
      <div className="flex justify-between text-xs text-dim">
        <span>{home.short}</span>
        <span>{away.short}</span>
      </div>
      {rows.map((k) => {
        const h = d.stats[k].home ?? 0
        const a = d.stats[k].away ?? 0
        const share = h + a > 0 ? h / (h + a) : 0.5
        return (
          <div key={k}>
            <div className="flex items-baseline justify-between text-[13px]">
              <span className="num font-semibold text-white">{k === 'Possession %' ? `${h.toFixed(0)}%` : h}</span>
              <span className="text-xs text-mute">{k.replace(' %', '')}</span>
              <span className="num font-semibold text-white">{k === 'Possession %' ? `${a.toFixed(0)}%` : a}</span>
            </div>
            <div className="mt-1 flex h-1.5 gap-0.5 overflow-hidden rounded-full">
              <span style={{ width: `${share * 100}%`, background: teamColor(home.color) }} />
              <span className="flex-1" style={{ background: teamColor(away.color) }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

const eventIcon = (e: SEvent) => {
  const t = e.type.toLowerCase()
  if (e.goal) return <span className="text-[13px]">⚽</span>
  if (t.includes('red')) return <span className="inline-block h-3.5 w-2.5 rounded-[2px] bg-coral" />
  if (t.includes('yellow')) return <span className="inline-block h-3.5 w-2.5 rounded-[2px] bg-gold" />
  if (t.includes('substitution')) return <span className="text-xs text-mute">⇄</span>
  return <span className="h-1.5 w-1.5 rounded-full bg-white/40" />
}

function Events({ d }: { d: SDetail }) {
  const [all, setAll] = useState(false)
  const shown = d.events.filter((e) => all || e.goal || /card|halftime|kickoff|end/i.test(e.type))
  if (!d.events.length) return null
  return (
    <div className="mt-5">
      <div className="flex items-baseline justify-between">
        <div className="text-xs font-medium text-mute">Goals, cards{all ? ' and changes' : ''}</div>
        <button onClick={() => setAll((v) => !v)} className="text-xs text-dim hover:text-white">
          {all ? 'Hide substitutions' : 'Show substitutions'}
        </button>
      </div>
      <ul className="mt-1.5">
        {shown.map((e, i) => (
          <li key={i} className={clsx('flex items-start gap-3 py-1.5 text-[13px]', e.team === 'away' && 'flex-row')}>
            <span className="num w-12 shrink-0 text-right text-dim">{e.minute}</span>
            <span className="flex w-4 shrink-0 justify-center pt-0.5">{eventIcon(e)}</span>
            <span className={clsx('min-w-0 flex-1 leading-snug', e.goal ? 'font-medium text-white' : 'text-slate-300')}>{e.text}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Commentary({ d }: { d: SDetail }) {
  const [open, setOpen] = useState(false)
  if (!d.commentary.length) return null
  const lines = [...d.commentary].reverse()
  const shown = open ? lines : lines.slice(0, 6)
  return (
    <div className="mt-5">
      <div className="text-xs font-medium text-mute">Commentary, latest first</div>
      <ul className="mt-1.5">
        {shown.map((c, i) => (
          <li key={i} className="flex gap-3 border-b border-hair py-1.5 text-[13px] last:border-b-0">
            <span className="num w-10 shrink-0 text-right text-dim">{c.minute || '–'}</span>
            <span className="min-w-0 flex-1 leading-snug text-slate-300">{c.text}</span>
          </li>
        ))}
      </ul>
      {lines.length > 6 && (
        <button onClick={() => setOpen((v) => !v)} className="mt-1 flex items-center gap-1 text-[13px] font-medium text-mute hover:text-white">
          {open ? 'Show less' : `Show all ${lines.length}`}
          <ChevronDown size={14} className={clsx('transition-transform', open && 'rotate-180')} />
        </button>
      )}
    </div>
  )
}

function Positions({ positions, reload }: { positions: SPosition[]; reload: () => void }) {
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (!positions.length) return null
  const sell = async (id: number) => {
    setBusy(id)
    setError(null)
    try {
      await soccerApi.close(id)
      reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not sell')
    } finally {
      setBusy(null)
    }
  }
  return (
    <section className="mt-8">
      <h2 className="h-section">Your positions here</h2>
      <div className="mt-2">
        {positions.map((p) => (
          <div key={p.id} className="flex items-center gap-3 border-b border-hair py-3 last:border-b-0">
            <div className="min-w-0 flex-1">
              <div className="break-words text-[14px] font-medium text-white">{p.label}</div>
              <div className="num text-xs text-dim">
                {p.contracts} at {cents(p.entry_price)} · now {cents(p.mark_price)} · model {p.p_win != null ? pct(p.p_win) : '—'}
              </div>
            </div>
            <div className={clsx('num text-sm font-semibold', pnlColor(p.pnl))}>{money(p.pnl, { sign: true })}</div>
            <Button variant="outline" disabled={!p.can_sell} loading={busy === p.id} onClick={() => sell(p.id)}>
              Sell
            </Button>
          </div>
        ))}
      </div>
      {error && <p className="mt-2 text-[13px] text-coral">{error}</p>}
    </section>
  )
}

export default function SoccerMatch() {
  const { id = '' } = useParams()
  const { data: d, error, reload } = usePoll(() => soccerApi.match(id), 3000, id)
  const live = useStore((s) => s.app?.settings.trading_mode === 'live')
  const desktop = useMediaQuery('(min-width: 1024px)')
  const [segment, setSegment] = useState<SSegment>('match')
  const [pick, setPick] = useState<SPick | null>(null)

  const markets = useMemo(() => (d?.markets ?? []).filter((m) => m.segment === segment), [d, segment])
  if (!d) {
    return (
      <div className="page">
        {error ? (
          <Empty title="Match not found" body={error} action={<Link to="/soccer" className="text-sm text-mute underline">Back to soccer</Link>} />
        ) : (
          <Skeleton className="h-[220px] w-full !rounded-xl2" />
        )}
      </div>
    )
  }
  const m = d.match
  const decided = (x: SMarket) => m.state === 'final' || (x.segment === '1h' && (m.period >= 2 || m.halftime))
  const segClosed = segment === '1h' ? m.state === 'final' || m.period >= 2 || m.halftime : m.state === 'final'
  const panel = (
    <SoccerOrderPanel
      label={m.label}
      markets={d.markets}
      pick={pick}
      onPick={setPick}
      account={d.account}
      live={live}
      closed={decided}
      onPlaced={reload}
      bare={!desktop}
    />
  )

  return (
    <div className="page">
      <Link to="/soccer" className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-mute hover:text-white">
        <ArrowLeft size={15} /> Soccer
      </Link>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0">
          <Scoreboard m={m} />

          {m.state !== 'final' && (
            <GameAnalysis
              game={{ id: m.id, label: m.label, state: m.state }}
              noun="match"
              onPickFav={(ticker, side) => setPick({ ticker, side: side as SSide })}
            />
          )}

          <section className="mt-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="h-section">Markets</h2>
              <Segmented
                id="soccer-seg"
                value={segment}
                onChange={(v) => {
                  setSegment(v)
                  setPick(null)
                }}
                options={[
                  { value: 'match', label: 'Full match' },
                  { value: '1h', label: '1st half' },
                ]}
              />
            </div>
            <ModelLine d={d} segment={segment} />
            {markets.length === 0 ? (
              <p className="mt-4 text-sm text-mute">No Kalshi markets for {segment === '1h' ? 'the first half' : 'this match'} right now.</p>
            ) : (
              <>
                <MarketGroup title="Who wins" hint={segment === '1h' ? 'at half time' : 'after 90 minutes and stoppage time'} markets={markets.filter((x) => x.kind === 'winner')} pick={pick} onPick={setPick} closed={segClosed} />
                <MarketGroup title="Total goals" markets={markets.filter((x) => x.kind === 'total')} pick={pick} onPick={setPick} closed={segClosed} />
                <MarketGroup title="Winning margin" markets={markets.filter((x) => x.kind === 'spread')} pick={pick} onPick={setPick} closed={segClosed} />
              </>
            )}
            <p className="mt-4 text-xs leading-relaxed text-dim">
              Model: {d.prior.home_goals?.toFixed(2)}–{d.prior.away_goals?.toFixed(2)} goals expected before kickoff ({d.prior.source}), then the score, the minute and red cards.
            </p>
          </section>

          <Positions positions={d.positions} reload={reload} />

          {(d.events.length > 0 || Object.keys(d.stats).length > 0 || d.commentary.length > 0) && (
            <section className="mt-8">
              <h2 className="h-section">What's happening</h2>
              <StatBars d={d} />
              <Events d={d} />
              <Commentary d={d} />
            </section>
          )}
        </div>

        {desktop && <aside className="lg:sticky lg:top-24 lg:self-start">{panel}</aside>}
      </div>
      {!desktop && (
        <OrderSheet open={!!pick} onClose={() => setPick(null)}>
          {panel}
        </OrderSheet>
      )}
    </div>
  )
}
