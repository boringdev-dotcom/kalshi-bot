import clsx from 'clsx'
import { periodLabel, startTime, teamColor } from '../../format'
import type { Game, TeamSide } from '../../types'
import { LiveDot, SimTag } from '../ui'

export function gameStatus(game: Game) {
  if (game.state === 'final') return game.period > 4 ? 'Final (overtime)' : 'Final'
  if (game.state === 'pre') return `Tips off ${startTime(game.start_time)}`
  if (game.period > 4) return `${periodLabel(game.period)} · ${game.clock} left`
  return `${periodLabel(game.period)} · ${game.clock} left`
}

function TeamLine({ team, lead, big }: { team: TeamSide; lead: boolean; big: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span className="h-9 w-1.5 shrink-0 rounded-full" style={{ background: teamColor(team.color) }} />
      <div className="min-w-0 flex-1">
        <div className="text-xl font-semibold leading-tight text-white">{team.abbr}</div>
        <div className="truncate text-[13px] text-mute">{team.name}</div>
      </div>
      {big && (
        <div className={clsx('num text-[40px] font-semibold leading-none tracking-tight', lead ? 'text-white' : 'text-mute')}>{team.score}</div>
      )}
    </div>
  )
}

/** Who is playing, the score, and how much time is left. Nothing else. */
export default function Scoreboard({ game }: { game: Game }) {
  const started = game.state !== 'pre'
  const q = Math.max(game.home.quarters?.length ?? 0, game.away.quarters?.length ?? 0)
  const cols = Array.from({ length: Math.max(4, q) }, (_, i) => i)
  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm">
        {game.state === 'live' && <LiveDot size={8} />}
        <span className={clsx('font-medium', game.state === 'live' ? 'text-mint' : 'text-mute')}>
          {game.state === 'live' ? 'Live' : game.state === 'final' ? 'Finished' : 'Upcoming'}
        </span>
        <span className="text-mute">· {gameStatus(game)}</span>
        {game.simulated && <SimTag />}
      </div>

      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-10">
        <div className="space-y-3">
          <TeamLine team={game.away} lead={game.away.score >= game.home.score} big={started} />
          <TeamLine team={game.home} lead={game.home.score >= game.away.score} big={started} />
        </div>

        {started && q > 0 && (
          <table className="num text-right text-[13px]">
            <thead>
              <tr className="text-dim">
                <th className="pr-4 text-left font-normal" />
                {cols.map((i) => (
                  <th key={i} className="w-9 pb-1.5 font-normal">
                    {i < 4 ? `Q${i + 1}` : i === 4 ? 'OT' : `${i - 3}OT`}
                  </th>
                ))}
                <th className="w-12 pb-1.5 font-normal">Total</th>
              </tr>
            </thead>
            <tbody>
              {[game.away, game.home].map((t) => (
                <tr key={t.abbr}>
                  <td className="pr-4 text-left text-mute">{t.abbr}</td>
                  {cols.map((i) => {
                    const playing = game.state === 'live' && i === game.period - 1
                    const v = t.quarters?.[i]
                    return (
                      <td key={i} className={clsx('py-0.5', playing ? 'font-semibold text-white' : 'text-slate-300')}>
                        {v ?? (i < game.period ? 0 : '·')}
                      </td>
                    )
                  })}
                  <td className="py-0.5 font-semibold text-white">{t.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
