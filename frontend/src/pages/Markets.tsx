import clsx from 'clsx'
import { ChevronRight, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { agentTone } from '../components/Layout'
import { gameStatus } from '../components/game/Scoreboard'
import { Badge, Empty, LiveDot, SimTag, Skeleton } from '../components/ui'
import { money, pnlColor, relTime, teamColor, tradeLabel } from '../format'
import { gameLine } from '../lib'
import { useStore } from '../store'
import type { Game, Position, TeamSide } from '../types'

function TeamRow({ team, show, lead }: { team: TeamSide; show: boolean; lead: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span className="h-6 w-1 shrink-0 rounded-full" style={{ background: teamColor(team.color) }} />
      <span className="w-12 text-[17px] font-semibold text-white">{team.abbr}</span>
      <span className="min-w-0 flex-1 truncate text-[13px] text-dim">{team.name}</span>
      {show && <span className={clsx('num text-2xl font-semibold', lead ? 'text-white' : 'text-mute')}>{team.score}</span>}
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-dim">{label}</div>
      <div className="num mt-0.5 text-sm font-medium text-white">{value}</div>
    </div>
  )
}

function GameCard({ game, mine }: { game: Game; mine: Position[] }) {
  const started = game.state !== 'pre'
  const line = gameLine(game).value
  const proj = game.projection?.mean
  const pnl = mine.reduce((sum, p) => sum + p.pnl, 0)
  return (
    <Link to={`/game/${game.id}`} className="surface group block p-5 transition-colors hover:border-hair2 hover:bg-ink-800/60">
      <div className="mb-4 flex items-center gap-2 text-[13px]">
        {game.state === 'live' && <LiveDot size={7} />}
        <span className={clsx('font-medium', game.state === 'live' ? 'text-mint' : 'text-mute')}>{gameStatus(game)}</span>
        {game.state === 'live' && game.risk.level === 'high' && <Badge tone="coral">Tight finish</Badge>}
        {game.simulated && <SimTag />}
        <ChevronRight size={16} className="ml-auto text-dim transition-transform group-hover:translate-x-0.5 group-hover:text-white" />
      </div>
      <div className="space-y-2">
        <TeamRow team={game.away} show={started} lead={game.away.score >= game.home.score} />
        <TeamRow team={game.home} show={started} lead={game.home.score >= game.away.score} />
      </div>
      <div className="mt-5 flex items-end gap-8 border-t border-hair pt-4">
        {started && <Fact label="Points so far" value={String(game.total)} />}
        <Fact label="The line" value={line != null ? String(line) : '—'} />
        {game.state !== 'final' && <Fact label={started ? 'Heading for' : 'Model expects'} value={proj != null ? proj.toFixed(0) : '—'} />}
        {mine.length > 0 && (
          <div className="ml-auto text-right">
            <div className="text-xs text-dim">{mine.length === 1 ? tradeLabel(mine[0]) : `${mine.length} positions`}</div>
            <div className={clsx('num mt-0.5 text-sm font-semibold', pnlColor(pnl))}>{money(pnl, { sign: true })}</div>
          </div>
        )}
      </div>
    </Link>
  )
}

function Section({ title, hint, games, positions }: { title: string; hint?: string; games: Game[]; positions: Position[] }) {
  if (games.length === 0) return null
  return (
    <section className="mt-10 first:mt-0">
      <div className="mb-3 flex items-baseline gap-3">
        <h2 className="h-section">{title}</h2>
        {hint && <span className="text-[13px] text-dim">{hint}</span>}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {games.map((g) => (
          <GameCard key={g.id} game={g} mine={positions.filter((p) => p.game_id === g.id)} />
        ))}
      </div>
    </section>
  )
}

/** What the agent is up to, in one line, with its last move. */
function AgentLine() {
  const agent = useStore((s) => s.app?.agent)
  const last = useStore((s) => s.decisions.find((d) => d.kind === 'enter' || d.kind === 'exit'))
  if (!agent) return null
  const tone = agentTone[agent.state]
  return (
    <Link to="/agent" className="surface group mb-8 flex items-center gap-4 px-5 py-4 transition-colors hover:border-hair2">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-peri/15">
        <LiveDot color={tone.color} size={9} pulse={agent.state === 'acting'} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-white">
          Agent: {agent.state === 'paused' ? 'paused' : agent.focus || tone.label}
        </div>
        <div className="mt-0.5 truncate text-[13px] text-mute">
          {last ? `Last move: ${last.headline} · ${relTime(last.ts)}` : 'No trades yet. It buys the under late in games when the price is right.'}
        </div>
      </div>
      <span className="hidden shrink-0 text-[13px] text-mute group-hover:text-white sm:block">See what it is doing</span>
      <ChevronRight size={16} className="shrink-0 text-dim group-hover:text-white" />
    </Link>
  )
}

const INTRO_KEY = 'courtside.intro.dismissed'

function Intro() {
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem(INTRO_KEY) === '1'
    } catch {
      return false
    }
  })
  if (hidden) return null
  const close = () => {
    setHidden(true)
    try {
      localStorage.setItem(INTRO_KEY, '1')
    } catch {
      /* private mode: just hide it for now */
    }
  }
  return (
    <div className="surface relative mb-8 px-6 py-5">
      <button onClick={close} className="absolute right-3 top-3 rounded-full p-2 text-dim hover:bg-white/[0.06] hover:text-white" aria-label="Dismiss">
        <X size={15} />
      </button>
      <div className="h-section">How this works</div>
      <div className="mt-3 grid gap-5 text-[13px] leading-relaxed text-slate-300 sm:grid-cols-3">
        <div>
          <div className="mb-1 font-medium text-white">1. Every game has a line</div>
          The line is the total points both teams are expected to score. You bet on the final total landing under or over a number.
        </div>
        <div>
          <div className="mb-1 font-medium text-white">2. The price is the chance</div>
          A contract pays $1 if you are right. If it costs 94¢, the market thinks it happens about 94 times in 100, and you make 6¢.
        </div>
        <div>
          <div className="mb-1 font-medium text-white">3. The agent can do it for you</div>
          It watches every game, buys the under late when the cushion is big, and sells if the game turns. You set its rules.
        </div>
      </div>
    </div>
  )
}

export default function Markets() {
  const games = useStore((s) => s.games)
  const loaded = useStore((s) => s.gamesLoaded)
  const positions = useStore((s) => s.positions)
  const practice = useStore((s) => s.app?.settings.data_source === 'sim')

  const live = games.filter((g) => g.state === 'live')
  const upcoming = games.filter((g) => g.state === 'pre')
  const finished = games.filter((g) => g.state === 'final')

  return (
    <div className="page">
      <h1 className="h-page">Markets</h1>
      <p className="hint mb-6 mt-1">
        {practice ? 'These are practice games with made-up scores and prices. Switch to real games in Settings.' : "Tonight's NBA games and their total-points markets on Kalshi."}
      </p>

      <Intro />
      <AgentLine />

      {!loaded ? (
        <div className="grid gap-4 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[190px] w-full !rounded-xl2" />
          ))}
        </div>
      ) : games.length === 0 ? (
        <Empty title="No games on the board" body="When games are scheduled they show up here. You can switch to practice games in Settings to try things out any time." />
      ) : (
        <>
          <Section title="Live now" hint={`${live.length} ${live.length === 1 ? 'game' : 'games'}`} games={live} positions={positions} />
          <Section title="Coming up" games={upcoming} positions={positions} />
          <Section title="Finished" games={finished} positions={positions} />
        </>
      )}
    </div>
  )
}
