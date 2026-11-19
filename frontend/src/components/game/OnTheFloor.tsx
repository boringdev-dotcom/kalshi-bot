import clsx from 'clsx'
import { ArrowDownRight, ArrowUpRight, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { periodLabel, teamColor } from '../../format'
import type { Game, PatternNote, PlayerLine, TeamFloor, TeamSide } from '../../types'

/**
 * What is happening on the floor, for the person trading: the patterns in plain sentences,
 * team fouls and the bonus, who is playing, and the full box score one tap away.
 */
export default function OnTheFloor({ game, players }: { game: Game; players: PlayerLine[] | null }) {
  const [showAllNotes, setShowAllNotes] = useState(false)
  const [showBox, setShowBox] = useState(false)
  const pat = game.patterns
  if (!pat) return null
  const live = game.state === 'live'
  const notes = pat.notes ?? []
  const hasFloor = live && (players?.length ?? 0) > 0
  if (!notes.length && !hasFloor && !pat.out.length) return null

  const byAbbr = (abbr: string): TeamSide => (game.home.abbr === abbr ? game.home : game.away)
  const away = pat.teams.find((t) => t.side === 'away')
  const home = pat.teams.find((t) => t.side === 'home')
  const shown = showAllNotes ? notes : notes.slice(0, 3)

  return (
    <section className="mt-8">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="h-section">What's happening</h2>
        <span className="text-xs text-dim">{pat.source === 'practice' ? 'Practice game: made-up players' : 'From ESPN play-by-play'}</span>
      </div>

      {notes.length > 0 ? (
        <ul className="mt-2">
          {shown.map((n, i) => (
            <Note key={`${n.key}-${i}`} note={n} />
          ))}
        </ul>
      ) : (
        live && <p className="mt-2 text-sm text-mute">Nothing stands out right now: no bonus, no foul trouble, no big run.</p>
      )}
      {notes.length > 3 && (
        <button onClick={() => setShowAllNotes((v) => !v)} className="mt-1 text-[13px] font-medium text-mute hover:text-white">
          {showAllNotes ? 'Show fewer' : `Show all ${notes.length}`}
        </button>
      )}

      {live && away && home && (
        <div className="mt-4 grid grid-cols-2 gap-2.5">
          <Fouls team={away} side={byAbbr(away.abbr)} other={byAbbr(home.abbr)} period={game.period} />
          <Fouls team={home} side={byAbbr(home.abbr)} other={byAbbr(away.abbr)} period={game.period} />
        </div>
      )}

      {hasFloor && away && home && players && (
        <div className="mt-4">
          <div className="text-xs font-medium text-mute">On the floor</div>
          <div className="mt-1.5 grid grid-cols-2 gap-x-5">
            {[away, home].map((t) => (
              <Lineup key={t.abbr} team={byAbbr(t.abbr)} floor={t} players={players} period={game.period} />
            ))}
          </div>
          <button
            onClick={() => setShowBox((v) => !v)}
            className="mt-3 flex items-center gap-1 text-[13px] font-medium text-mute hover:text-white"
            aria-expanded={showBox}
          >
            {showBox ? 'Hide box score' : 'Full box score'}
            <ChevronDown size={14} className={clsx('transition-transform', showBox && 'rotate-180')} />
          </button>
          {showBox && <BoxScore game={game} players={players} />}
        </div>
      )}

      {pat.out.length > 0 && (
        <p className="mt-3 text-xs leading-relaxed text-dim">
          Out tonight:{' '}
          {pat.out.map((o, i) => (
            <span key={o.team}>
              {i > 0 && ' · '}
              <span className="text-mute">{o.team}</span> {o.names.join(', ')}
            </span>
          ))}
        </p>
      )}
    </section>
  )
}

function Note({ note }: { note: PatternNote }) {
  return (
    <li className="flex items-start gap-3 border-b border-hair py-2.5 last:border-b-0">
      <span className="mt-[3px] flex h-4 w-4 shrink-0 items-center justify-center">
        {note.lean === 'up' ? (
          <ArrowUpRight size={16} className="text-gold" />
        ) : note.lean === 'down' ? (
          <ArrowDownRight size={16} className="text-slate-300" />
        ) : (
          <span className="h-1.5 w-1.5 rounded-full bg-white/40" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <span className="text-[14px] leading-snug text-slate-200">{note.text}</span>
        {note.lean && (
          <span className={clsx('ml-2 whitespace-nowrap text-xs', note.lean === 'up' ? 'text-gold' : 'text-mute')}>
            {note.lean === 'up' ? 'More points likely' : 'Fewer points likely'}
          </span>
        )}
      </div>
    </li>
  )
}

function Fouls({ team, side, other, period }: { team: TeamFloor; side: TeamSide; other: TeamSide; period: number }) {
  const limit = period <= 4 ? 4 : 3
  const left = Math.max(0, limit - team.fouls)
  return (
    <div className={clsx('rounded-xl px-3 py-2.5', team.penalty ? 'bg-gold/[0.1]' : 'bg-ink-800')}>
      <div className="flex items-center gap-1.5 text-xs text-mute">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: teamColor(side.color) }} />
        {side.abbr} fouls in {periodLabel(period)}
      </div>
      <div className="mt-0.5 flex items-baseline gap-2">
        <span className="num text-lg font-semibold text-white">{team.fouls}</span>
        <span className={clsx('min-w-0 text-xs leading-tight', team.penalty ? 'text-gold' : 'text-dim')}>
          {team.penalty ? `${other.abbr} shoots on every foul` : `${left} more until ${other.abbr} is in the bonus`}
        </span>
      </div>
    </div>
  )
}

function Lineup({ team, floor, players, period }: { team: TeamSide; floor: TeamFloor; players: PlayerLine[]; period: number }) {
  const on = floor.on_court
    .map((id) => players.find((p) => p.id === id))
    .filter((p): p is PlayerLine => !!p)
    .sort((a, b) => b.points - a.points)
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 border-b border-hair pb-1 text-xs text-dim">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: teamColor(team.color) }} />
        {team.abbr}
        {floor.starters_on <= 1 && <span className="text-mute">· bench in</span>}
      </div>
      {on.map((p) => (
        <div key={p.id} className="flex items-baseline justify-between gap-2 py-1 text-[13px]">
          <span className={clsx('min-w-0 truncate', p.starter ? 'text-slate-200' : 'text-mute')} title={p.name}>
            {p.short}
          </span>
          <span className="num shrink-0 text-right">
            <span className="text-white">{p.points}</span>
            <span className={clsx('ml-2', foulTrouble(p, period) ? 'font-semibold text-gold' : 'text-dim')}>{p.fouls}f</span>
          </span>
        </div>
      ))}
    </div>
  )
}

const foulTrouble = (p: PlayerLine, period: number) => p.fouls >= 5 || (period <= 3 && p.fouls >= period + 1)

function BoxScore({ game, players }: { game: Game; players: PlayerLine[] }) {
  return (
    <div className="mt-3 space-y-5">
      {[game.away, game.home].map((team) => {
        const rows = players.filter((p) => p.team === team.abbr).sort((a, b) => Number(b.starter) - Number(a.starter) || b.minutes - a.minutes)
        return (
          <div key={team.abbr} className="no-scrollbar -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <table className="num w-full min-w-[520px] text-[13px]">
              <thead>
                <tr className="border-b border-hair text-xs text-dim">
                  <th className="py-1.5 pr-2 text-left font-medium">
                    <span className="flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full" style={{ background: teamColor(team.color) }} />
                      {team.abbr}
                    </span>
                  </th>
                  {['Min', 'Pts', 'FG', '3PT', 'FT', 'Fouls', '+/-'].map((h) => (
                    <th key={h} className="px-1.5 py-1.5 text-right font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id} className="border-b border-hair last:border-b-0">
                    <td className="max-w-[150px] truncate py-1.5 pr-2 text-left">
                      {p.on_court && <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-mint align-middle" title="On the floor" />}
                      <span className={p.starter ? 'text-slate-200' : 'text-mute'}>{p.name}</span>
                    </td>
                    <td className="px-1.5 text-right text-mute">{Math.round(p.minutes)}</td>
                    <td className="px-1.5 text-right font-semibold text-white">{p.points}</td>
                    <td className="px-1.5 text-right text-mute">{p.fgm}-{p.fga}</td>
                    <td className="px-1.5 text-right text-mute">{p.tpm}-{p.tpa}</td>
                    <td className="px-1.5 text-right text-mute">{p.ftm}-{p.fta}</td>
                    <td className={clsx('px-1.5 text-right', foulTrouble(p, game.period) ? 'font-semibold text-gold' : 'text-mute')}>{p.fouls}</td>
                    <td className="px-1.5 text-right text-mute">{p.plus_minus > 0 ? `+${p.plus_minus}` : p.plus_minus}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      })}
      <p className="text-xs text-dim">The green dot marks who is on the floor. Gold fouls mean foul trouble for this point in the game.</p>
    </div>
  )
}
