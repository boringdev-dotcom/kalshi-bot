import clsx from 'clsx'
import { ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Empty, LiveDot, Segmented, Skeleton } from '../../components/ui'
import { cents, money, pct, pnlColor, teamColor } from '../../format'
import { dayLabel, matchStatus, soccerApi, usePoll, type SMatch, type SPosition, type STeam } from '../../soccer'

export function Crest({ team, size = 22 }: { team: STeam; size?: number }) {
  const [broken, setBroken] = useState(false)
  if (!team.logo || broken) {
    return <span className="shrink-0 rounded-full" style={{ width: size * 0.45, height: size * 0.45, background: teamColor(team.color) }} />
  }
  return <img src={team.logo} alt="" width={size} height={size} className="shrink-0 object-contain" loading="lazy" onError={() => setBroken(true)} />
}

function TeamLine({ team, show, lead }: { team: STeam; show: boolean; lead: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex w-6 justify-center">
        <Crest team={team} />
      </span>
      <span className={clsx('min-w-0 flex-1 break-words text-[15px] font-semibold', lead || !show ? 'text-white' : 'text-mute')}>{team.short}</span>
      {team.red_cards > 0 && <span className="h-3.5 w-2.5 shrink-0 rounded-[2px] bg-coral" title={`${team.red_cards} red card${team.red_cards > 1 ? 's' : ''}`} />}
      {show && <span className={clsx('num w-6 text-right text-xl font-semibold', lead ? 'text-white' : 'text-mute')}>{team.score}</span>}
    </div>
  )
}

/** Home / draw / away: Kalshi's price for each, and the model's chance under it. */
function ResultPrices({ m }: { m: SMatch }) {
  const proj = m.projection?.match
  const cells = [
    { key: 'home' as const, label: m.home.abbr, p: proj?.p_home },
    { key: 'tie' as const, label: 'Draw', p: proj?.p_draw },
    { key: 'away' as const, label: m.away.abbr, p: proj?.p_away },
  ]
  return (
    <div className="grid grid-cols-3 gap-1.5">
      {cells.map((c) => {
        const mk = m.winner?.[c.key]
        return (
          <div key={c.key} className="rounded-xl bg-ink-800 px-2.5 py-2 text-center">
            <div className="break-words text-[11px] text-dim">{c.label}</div>
            <div className="num text-[15px] font-semibold text-white">{cents(mk?.yes_ask)}</div>
            <div className="num text-[11px] text-dim">model {c.p != null ? pct(c.p) : '—'}</div>
          </div>
        )
      })}
    </div>
  )
}

function MatchCard({ m, mine }: { m: SMatch; mine: SPosition[] }) {
  const started = m.state !== 'pre'
  const pnl = mine.reduce((s, p) => s + p.pnl, 0)
  return (
    <Link to={`/soccer/${m.id}`} className="surface group block min-w-0 p-4 transition-colors hover:border-hair2 hover:bg-ink-800/60">
      <div className="mb-3 flex items-center gap-2 text-[13px]">
        {m.state === 'live' && <LiveDot size={7} />}
        <span className={clsx('font-medium', m.state === 'live' ? 'text-mint' : 'text-mute')}>{matchStatus(m)}</span>
        <span className="break-words text-dim">· {m.league_name}</span>
        <ChevronRight size={16} className="ml-auto shrink-0 text-dim transition-transform group-hover:translate-x-0.5 group-hover:text-white" />
      </div>
      <div className="space-y-1.5">
        <TeamLine team={m.home} show={started} lead={m.home.score >= m.away.score} />
        <TeamLine team={m.away} show={started} lead={m.away.score >= m.home.score} />
      </div>
      <div className="mt-3.5">
        {m.has_markets && m.state !== 'final' ? (
          <ResultPrices m={m} />
        ) : (
          <p className="text-[13px] text-dim">{m.state === 'final' ? 'Finished.' : 'No Kalshi markets for this match yet.'}</p>
        )}
      </div>
      <div className="mt-3 flex items-center gap-4 text-[13px]">
        {m.total_line != null && m.state !== 'final' && (
          <span className="text-mute">
            Goal line <span className="num font-medium text-white">{m.total_line.toFixed(1)}</span>
          </span>
        )}
        {m.projection && m.state !== 'final' && (
          <span className="text-mute">
            Model <span className="num font-medium text-white">{m.projection.match.total.toFixed(1)}</span> goals
          </span>
        )}
        {mine.length > 0 && (
          <span className={clsx('num ml-auto font-semibold', pnlColor(pnl))}>
            {mine.length === 1 ? mine[0].label : `${mine.length} positions`} {money(pnl, { sign: true })}
          </span>
        )}
      </div>
      {m.state === 'live' && m.last_goal && (
        <p className="mt-2 break-words text-xs text-dim">
          Last goal {m.last_goal.minute}: {m.last_goal.text.replace(/^Goal!\s*/, '')}
        </p>
      )}
    </Link>
  )
}

function Grid({ matches, positions }: { matches: SMatch[]; positions: SPosition[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {matches.map((m) => (
        <MatchCard key={m.id} m={m} mine={positions.filter((p) => p.match_id === m.id)} />
      ))}
    </div>
  )
}

function Account({ positions, account }: { positions: SPosition[]; account: import('../../soccer').SAccount }) {
  return (
    <div className="surface mb-8 p-4 sm:p-5">
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
        <div>
          <div className="text-xs text-dim">{account.mode === 'live' ? 'Kalshi cash' : 'Soccer paper cash'}</div>
          <div className="num mt-0.5 text-xl font-semibold text-white">{money(account.cash)}</div>
        </div>
        <div>
          <div className="text-xs text-dim">Open positions</div>
          <div className="num mt-0.5 text-sm font-medium text-white">
            {account.open_positions} · {money(account.exposure)} at risk
          </div>
        </div>
        <div>
          <div className="text-xs text-dim">Open P&L</div>
          <div className={clsx('num mt-0.5 text-sm font-semibold', pnlColor(account.pnl_open))}>{money(account.pnl_open, { sign: true })}</div>
        </div>
        <div>
          <div className="text-xs text-dim">Settled</div>
          <div className={clsx('num mt-0.5 text-sm font-semibold', pnlColor(account.pnl_total))}>
            {money(account.pnl_total, { sign: true })}
            <span className="ml-1.5 font-normal text-dim">
              {account.wins}W {account.losses}L
            </span>
          </div>
        </div>
      </div>
      {positions.length > 0 && (
        <div className="mt-4 border-t border-hair pt-2">
          {positions.map((p) => (
            <Link key={p.id} to={`/soccer/${p.match_id}`} className="flex items-baseline justify-between gap-3 py-1.5 text-[13px] hover:text-white">
              <span className="min-w-0 break-words text-slate-200">
                {p.label} <span className="text-dim">· {p.match_label}</span>
              </span>
              <span className={clsx('num shrink-0 font-semibold', pnlColor(p.pnl))}>{money(p.pnl, { sign: true })}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

export default function SoccerBoard() {
  const { data, error } = usePoll(soccerApi.board, 5000, 'board')
  const [league, setLeague] = useState('all')

  const matches = useMemo(() => (data?.matches ?? []).filter((m) => league === 'all' || m.league === league), [data, league])
  const live = matches.filter((m) => m.state === 'live')
  const finished = matches.filter((m) => m.state === 'final')
  const days = useMemo(() => {
    const out: { day: string; matches: SMatch[] }[] = []
    for (const m of matches.filter((x) => x.state === 'pre')) {
      const day = dayLabel(m.start_time)
      const last = out[out.length - 1]
      if (last && last.day === day) last.matches.push(m)
      else out.push({ day, matches: [m] })
    }
    return out
  }, [matches])

  return (
    <div className="page">
      <h1 className="h-page">Soccer</h1>
      <p className="hint mb-6 mt-1">Europe's top five leagues, the Champions League and the Europa League on Kalshi: who wins, how many goals, by how much, and the first half. Separate from the NBA desk, with its own positions and P&L.</p>

      {data && <Account positions={data.positions} account={data.account} />}

      <div className="no-scrollbar -mx-4 mb-6 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <Segmented
          id="soccer-league"
          value={league}
          onChange={setLeague}
          options={[{ value: 'all', label: 'All' }, ...(data?.leagues ?? []).map((l) => ({ value: l.key, label: l.name }))]}
        />
      </div>

      {!data ? (
        error ? (
          <Empty title="Could not load soccer" body={error} />
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-[200px] w-full !rounded-xl2" />
            ))}
          </div>
        )
      ) : matches.length === 0 ? (
        <Empty title="No matches on the board" body="Fixtures for the coming week show up here as soon as ESPN lists them." />
      ) : (
        <div className="space-y-10">
          {live.length > 0 && (
            <section>
              <div className="mb-3 flex items-baseline gap-3">
                <h2 className="h-section">Live now</h2>
                <span className="text-[13px] text-dim">{live.length} {live.length === 1 ? 'match' : 'matches'}</span>
              </div>
              <Grid matches={live} positions={data.positions} />
            </section>
          )}
          {days.map((d) => (
            <section key={d.day}>
              <h2 className="h-section mb-3">{d.day}</h2>
              <Grid matches={d.matches} positions={data.positions} />
            </section>
          ))}
          {finished.length > 0 && (
            <section>
              <h2 className="h-section mb-3">Finished</h2>
              <Grid matches={finished} positions={data.positions} />
            </section>
          )}
        </div>
      )}
      {data && Object.values(data.feeds).some((f) => !f.ok) && (
        <p className="mt-8 text-xs text-gold">{Object.values(data.feeds).find((f) => !f.ok)?.detail}</p>
      )}
    </div>
  )
}
