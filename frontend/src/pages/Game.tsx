import clsx from 'clsx'
import { ArrowLeft, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { ActivityFeed } from '../components/Activity'
import LineBar from '../components/game/LineBar'
import MarketList from '../components/game/MarketList'
import OrderPanel from '../components/game/OrderPanel'
import Scoreboard from '../components/game/Scoreboard'
import TotalChart from '../components/TotalChart'
import { Button, Dialog, Empty, LiveDot, Segmented, Skeleton } from '../components/ui'
import { cents, mmss, money, pct, periodLabel, pnlColor, tradeLabel } from '../format'
import { bidOf, fee, gameLine, impliedLine, quarterNumber, useGameDetail, type Pick } from '../lib'
import { useStore } from '../store'
import type { Game, LadderRung, Position, QuarterSummary, Segment } from '../types'

const SEGMENTS: Segment[] = ['game', 'q1', 'q2', 'q3', 'q4']

/** The other games on tonight, one tap away. */
function GameSwitcher({ games, current }: { games: Game[]; current: string }) {
  const others = games.filter((g) => g.state !== 'final' || g.id === current)
  if (others.length < 2) return null
  return (
    <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      {others.map((g) => (
        <Link
          key={g.id}
          to={`/game/${g.id}`}
          className={clsx(
            'flex shrink-0 items-center gap-2 rounded-full px-3.5 py-2 text-[13px] transition-colors',
            g.id === current ? 'bg-white/[0.12] text-white' : 'bg-ink-900 text-mute hover:text-white',
          )}
        >
          {g.state === 'live' && <LiveDot size={6} pulse={false} />}
          <span className="num font-medium">
            {g.away.abbr} {g.state !== 'pre' ? g.away.score : ''} · {g.home.abbr} {g.state !== 'pre' ? g.home.score : ''}
          </span>
          <span className="text-dim">{g.state === 'live' ? `${periodLabel(g.period)} ${g.clock}` : g.state === 'final' ? 'Final' : 'Soon'}</span>
        </Link>
      ))}
    </div>
  )
}

/** One or two plain sentences saying where this market stands right now. */
function story(game: Game, segment: Segment, kind: 'total' | 'spread', line: number | null, q: QuarterSummary | undefined): string {
  if (segment === 'game') {
    const proj = game.projection?.mean
    if (game.state === 'pre') return line != null ? `The line is ${line}: the total points both teams are expected to score. Bet under if you think it will be a lower-scoring game, over if higher.` : 'Waiting for a line on this game.'
    if (game.state === 'final') return `It finished with ${game.total} points${line != null ? `. The line was ${line}.` : '.'}`
    const pace = proj != null && line != null ? (proj > line + 1.5 ? `, a little over the line of ${line}` : proj < line - 1.5 ? `, a little under the line of ${line}` : `, right around the line of ${line}`) : ''
    const when = game.period > 4 ? 'in overtime' : `with ${game.clock} left in ${periodLabel(game.period)}`
    return `${game.total} points so far ${when}.${proj != null ? ` It is heading for about ${proj.toFixed(0)}${pace}.` : ''}`
  }
  if (!q) return ''
  const name = segment.toUpperCase()
  const pts = q.home_points + q.away_points
  if (q.status === 'upcoming') {
    return kind === 'total'
      ? `${name} has not started. ${q.projection ? `The model expects about ${q.projection.total_mean.toFixed(0)} points in it.` : ''}${segment === 'q4' ? ' Overtime does not count.' : ''}`
      : `${name} has not started. Pick a team to win this quarter by a margin${segment === 'q4' ? ' (overtime does not count)' : ''}.`
  }
  if (q.status === 'final') {
    return kind === 'total' ? `${name} is over: ${pts} points were scored.` : `${name} is over: ${game.away.abbr} ${q.away_points}, ${game.home.abbr} ${q.home_points}.`
  }
  if (kind === 'total') {
    return `${pts} points in ${name} so far, ${mmss(q.seconds_remaining)} left.${q.projection ? ` It is heading for about ${q.projection.total_mean.toFixed(0)}.` : ''}`
  }
  const m = q.projection?.margin_mean
  const lead = m == null ? '' : Math.abs(m) < 0.75 ? ' It looks even from here.' : ` The model has ${m > 0 ? game.home.abbr : game.away.abbr} winning it by about ${Math.abs(m).toFixed(0)}.`
  return `${name} so far: ${game.away.abbr} ${q.away_points}, ${game.home.abbr} ${q.home_points}, with ${mmss(q.seconds_remaining)} left.${lead}`
}

function Holdings({ positions, rungs }: { positions: Position[]; rungs: LadderRung[] }) {
  const addTrade = useStore((s) => s.addTrade)
  const toast = useStore((s) => s.toast)
  const [selling, setSelling] = useState<Position | null>(null)
  const [busy, setBusy] = useState(false)
  if (positions.length === 0) return null

  const bid = selling ? (() => {
    const r = rungs.find((x) => x.ticker === selling.ticker)
    return r ? bidOf(r, selling.side) : null
  })() : null
  const proceeds = selling && bid != null ? (selling.contracts * bid) / 100 - fee(selling.contracts, bid) : null

  const sell = async () => {
    if (!selling) return
    setBusy(true)
    try {
      const trade = await api.closePosition(selling.id)
      addTrade(trade, selling.id)
      toast({ level: trade.pnl >= 0 ? 'success' : 'warn', title: `Sold ${tradeLabel(selling)}`, body: `${money(trade.pnl, { sign: true })} on the trade.` })
      setSelling(null)
    } catch (e) {
      toast({ level: 'error', title: 'Could not sell', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="surface mt-4 px-6 py-5">
      <div className="h-section">Your positions in this game</div>
      <div className="mt-2">
        {positions.map((p) => (
          <div key={p.id} className="row !px-0">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-white">{tradeLabel(p)}</div>
              <div className="num mt-0.5 text-xs text-dim">
                {p.contracts} at {cents(p.entry_price)} · {pct(p.p_win)} chance now · {p.opened_by === 'agent' ? 'Agent' : 'You'}
              </div>
            </div>
            <div className="text-right">
              <div className={clsx('num text-sm font-semibold', pnlColor(p.pnl))}>{money(p.pnl, { sign: true })}</div>
              <div className="num text-xs text-dim">worth {money(p.value)}</div>
            </div>
            <Button size="xs" variant="outline" onClick={() => setSelling(p)}>
              Sell
            </Button>
          </div>
        ))}
      </div>

      <Dialog open={!!selling} onClose={() => setSelling(null)} title={selling ? `Sell ${tradeLabel(selling)}?` : ''} subtitle={selling?.game_label}>
        {selling && (
          <div>
            <p className="hint">
              You hold {selling.contracts} contracts bought at {cents(selling.entry_price)} for {money(selling.cost)}.
            </p>
            <div className="mt-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-mute">Sell now{bid != null ? ` at ${cents(bid)}` : ''}</span>
                <span className="num font-semibold text-white">{proceeds != null ? `${money(proceeds)}  (${money(proceeds - selling.cost, { sign: true })})` : 'No buyer right now'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">Keep it and win</span>
                <span className="num font-semibold text-mint">{money(selling.contracts)}  ({money(selling.max_profit, { sign: true })})</span>
              </div>
              <div className="flex justify-between">
                <span className="text-mute">Keep it and lose</span>
                <span className="num font-semibold text-coral">{money(0)}  ({money(-selling.cost, { sign: true })})</span>
              </div>
            </div>
            <div className="mt-6 flex gap-2">
              <Button variant="outline" size="md" className="flex-1" onClick={() => setSelling(null)}>
                Keep it
              </Button>
              <Button variant="primary" size="md" className="flex-1" loading={busy} disabled={bid == null} onClick={sell}>
                Sell now
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  )
}

export default function GamePage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const games = useStore((s) => s.games)
  const loaded = useStore((s) => s.gamesLoaded)
  const allPositions = useStore((s) => s.positions)
  const game = useMemo(() => games.find((g) => g.id === id) ?? null, [games, id])
  const { detail } = useGameDetail(game ? id : null)

  const [segment, setSegment] = useState<Segment>('game')
  const [kind, setKind] = useState<'total' | 'spread'>('total')
  const [pick, setPick] = useState<Pick | null>(null)
  const [showChart, setShowChart] = useState(true)

  useEffect(() => {
    setSegment('game')
    setKind('total')
    setPick(null)
  }, [id])

  const positions = useMemo(() => allPositions.filter((p) => p.game_id === id), [allPositions, id])
  const quarterMarkets = detail?.quarter_markets ?? null
  const allRungs = useMemo<LadderRung[]>(
    () => [...(game?.ladder ?? []), ...(quarterMarkets ?? []).flatMap((m) => [...(m.totals ?? []), ...(m.spreads ?? [])])],
    [game?.ladder, quarterMarkets],
  )

  if (!game) {
    if (!loaded) return <div className="page"><Skeleton className="h-64 w-full" /></div>
    return (
      <div className="page">
        <Empty title="That game is no longer on the board" body="It may have finished and been cleared." action={<Button onClick={() => navigate('/')}>Back to markets</Button>} />
      </div>
    )
  }

  const q = segment === 'game' ? undefined : game.quarters?.[quarterNumber(segment) - 1]
  const market = segment === 'game' ? null : quarterMarkets?.find((m) => m.segment === segment)
  const rungs: LadderRung[] | null = segment === 'game' ? game.ladder : market ? (kind === 'total' ? market.totals : market.spreads) : null
  const showKind = segment === 'game' ? 'total' : kind

  const gl = gameLine(game)
  const line = segment === 'game' ? gl.value : showKind === 'total' && market ? impliedLine(market.totals ?? []) : null
  const lineSource = segment === 'game' ? gl.source : 'the point where Kalshi prices over and under at 50/50'

  const closedSegments = new Set<string>()
  if (game.state === 'final') SEGMENTS.forEach((s) => closedSegments.add(s))
  game.quarters?.forEach((x) => x.status === 'final' && closedSegments.add(x.segment))

  const pickedRung = pick ? allRungs.find((r) => r.ticker === pick.ticker) : null
  const pickOnBar = pickedRung && (pickedRung.segment ?? 'game') === segment && (pickedRung.kind ?? 'total') === 'total' && showKind === 'total' ? pickedRung : null
  const heldStrikes = positions.filter((p) => (p.segment ?? 'game') === segment && (p.kind ?? 'total') === 'total').map((p) => p.strike)

  const now = segment === 'game' ? (game.state === 'pre' ? null : game.total) : q && q.status !== 'upcoming' ? q.home_points + q.away_points : null
  const projected = segment === 'game' ? (game.projection?.mean ?? (game.state === 'final' ? null : line)) : (q?.projection?.total_mean ?? null)
  const spread = segment === 'game' ? game.projection?.sd : q?.projection?.total_sd
  const risky = game.state === 'live' && game.risk.level !== 'low' && game.risk.flags.length > 0

  const segOptions = SEGMENTS.map((s) => {
    const qs = s === 'game' ? null : game.quarters?.[quarterNumber(s) - 1]
    return {
      value: s,
      label: (
        <span className="flex items-center gap-1.5">
          {qs?.status === 'live' && <LiveDot size={6} pulse={false} />}
          <span className={clsx(qs?.status === 'final' && 'opacity-50')}>{s === 'game' ? 'Full game' : s.toUpperCase()}</span>
        </span>
      ),
    }
  })

  return (
    <div className="page">
      <div className="mb-5 flex items-center gap-4">
        <Link to="/" className="flex shrink-0 items-center gap-1.5 text-sm text-mute hover:text-white">
          <ArrowLeft size={15} /> Markets
        </Link>
        <GameSwitcher games={games} current={game.id} />
      </div>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0">
          <Scoreboard game={game} />

          {risky &&
            (game.risk.level === 'high' ? (
              <div className="mt-5 flex items-start gap-2.5 rounded-2xl bg-coral/[0.1] px-4 py-3 text-[13px] leading-relaxed text-coral">
                <TriangleAlert size={15} className="mt-0.5 shrink-0" />
                <span>Risky for unders right now: {game.risk.flags.join('. ')}.</span>
              </div>
            ) : (
              <p className="mt-4 text-[13px] text-gold">Worth knowing: {game.risk.flags.join('. ')}.</p>
            ))}

          {/* which market */}
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Segmented id="segment" size="md" options={segOptions} value={segment} onChange={(s) => { setSegment(s); if (s === 'game') setKind('total') }} />
            {segment !== 'game' && (
              <Segmented id="kind" size="md" options={[{ value: 'total', label: 'Total points' }, { value: 'spread', label: 'Spread' }]} value={kind} onChange={setKind} />
            )}
          </div>

          <h2 className="mt-6 text-xl font-semibold text-white">
            {segment === 'game' ? 'Total points in the game' : showKind === 'total' ? `Total points in ${segment.toUpperCase()}` : `Who wins ${segment.toUpperCase()}, and by how much`}
          </h2>
          <p className="mt-1.5 max-w-2xl text-[15px] leading-relaxed text-slate-300">{story(game, segment, showKind, line, q)}</p>

          {showKind === 'total' && (line != null || projected != null) && (
            <div className="mt-2">
              <LineBar now={now} line={line} projected={projected} spread={spread} pick={pickOnBar?.strike ?? null} pickLabel={pickOnBar && pick ? (pick.side === 'under' ? 'Your under' : 'Your over') : undefined} held={heldStrikes} />
              {line != null && (
                <p className="-mt-1 text-xs text-dim">
                  The line is {lineSource}. The shaded band is where the model thinks it will most likely finish.
                </p>
              )}
            </div>
          )}

          <div className="mt-8">
            <div className="flex items-end justify-between gap-4 border-b border-hair pb-2">
              <div className="h-section">{showKind === 'total' ? 'Pick a number' : 'Pick a margin'}</div>
              <div className="hidden text-xs text-dim sm:block">Prices are per contract. Each contract pays $1 if you are right.</div>
            </div>
            <MarketList
              game={game}
              rungs={rungs}
              kind={showKind}
              line={line}
              pick={pick}
              onPick={setPick}
              owned={new Set(positions.map((p) => p.ticker))}
              closed={closedSegments.has(segment)}
              loading={segment !== 'game' && !detail}
              emptyText={segment === 'game' ? 'Kalshi has not opened total-points markets for this game yet.' : `Kalshi has no ${segment.toUpperCase()} ${showKind === 'total' ? 'total' : 'spread'} market for this game yet.`}
            />
            {closedSegments.has(segment) && <p className="mt-3 text-[13px] text-mute">This market has finished, so it can no longer be traded.</p>}
          </div>

          {segment === 'game' && game.state !== 'pre' && (
            <div className="mt-10">
              <button onClick={() => setShowChart((v) => !v)} className="text-[13px] font-medium text-mute hover:text-white">
                {showChart ? 'Hide chart' : 'Show chart'}
              </button>
              {showChart && (
                <div className="mt-2">
                  <TotalChart game={game} timeline={detail ? detail.timeline : null} positions={positions} loading={!detail} />
                </div>
              )}
            </div>
          )}

          <div className="mt-12">
            <div className="h-section">What the agent did in this game</div>
            <p className="hint mt-1">{segment === 'game' ? 'The agent trades the full-game total on its own.' : 'The agent only watches quarter markets. Anything you buy here is yours to manage.'}</p>
            <div className="mt-3">
              <ActivityFeed gameId={game.id} limit={6} compact />
            </div>
          </div>
        </div>

        <aside className="lg:sticky lg:top-24 lg:self-start">
          <OrderPanel game={game} rungs={allRungs} pick={pick} onPick={setPick} closedSegments={closedSegments} />
          <Holdings positions={positions} rungs={allRungs} />
        </aside>
      </div>
    </div>
  )
}
