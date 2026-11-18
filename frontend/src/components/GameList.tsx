import { motion } from 'framer-motion'
import clsx from 'clsx'
import { CalendarClock } from 'lucide-react'
import { fixed, gameClock, teamColor } from '../format'
import { useStore } from '../store'
import type { Game } from '../types'
import { Empty, LiveDot, RiskDot, SimTag, Skeleton, Ticker } from './ui'

function TeamRow({ abbr, score, color, leading, showScore }: { abbr: string; score: number; color: string; leading: boolean; showScore: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className="h-3.5 w-[3px] rounded-full" style={{ background: teamColor(color) }} />
        <span className="text-[13px] font-bold tracking-wide" style={{ color: teamColor(color) }}>
          {abbr}
        </span>
      </div>
      {showScore ? (
        <Ticker
          value={score}
          className={clsx('text-[15px] font-semibold', leading ? 'text-slate-50' : 'text-mute')}
        />
      ) : (
        <span className="num text-[13px] text-dim">–</span>
      )}
    </div>
  )
}

function GameCard({ game, selected, held }: { game: Game; selected: boolean; held: number }) {
  const select = useStore((s) => s.selectGame)
  const live = game.state === 'live'
  const started = game.state !== 'pre'
  return (
    <motion.button
      layout="position"
      onClick={() => select(game.id)}
      whileHover={{ y: -1 }}
      transition={{ type: 'spring', stiffness: 420, damping: 30 }}
      className={clsx(
        'relative w-full rounded-xl border p-3 text-left transition-colors',
        selected
          ? 'border-peri/40 bg-ink-800 shadow-glow'
          : 'border-hair bg-ink-900/80 hover:border-white/[0.12] hover:bg-ink-800/80',
        game.state === 'final' && !selected && 'opacity-70',
      )}
    >
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          {live ? (
            <>
              <LiveDot color="#ff6b6b" size={6} />
              <span className="num text-[11px] font-semibold text-slate-100">{gameClock(game)}</span>
            </>
          ) : (
            <span className={clsx('num text-[11px] font-medium', game.state === 'final' ? 'text-dim' : 'text-mute')}>
              {gameClock(game)}
            </span>
          )}
          {game.simulated && <SimTag />}
        </div>
        <div className="flex items-center gap-1.5">
          {held > 0 && (
            <span className="num rounded bg-peri/15 px-1 text-[10px] font-semibold text-peri" title="Open positions in this game">
              {held} pos
            </span>
          )}
          {live && <RiskDot level={game.risk.level} flags={game.risk.flags} />}
        </div>
      </div>

      <div className="space-y-1">
        <TeamRow
          abbr={game.away.abbr}
          score={game.away.score}
          color={game.away.color}
          leading={game.away.score >= game.home.score}
          showScore={started}
        />
        <TeamRow
          abbr={game.home.abbr}
          score={game.home.score}
          color={game.home.color}
          leading={game.home.score >= game.away.score}
          showScore={started}
        />
      </div>

      <div className="mt-2.5 grid grid-cols-3 gap-1 border-t border-hair pt-2">
        <div>
          <div className="text-[9.5px] uppercase tracking-wider text-dim">Total</div>
          {started ? (
            <Ticker value={game.total} className="text-xs font-semibold text-slate-100" />
          ) : (
            <span className="num text-xs text-dim">—</span>
          )}
        </div>
        <div>
          <div className="text-[9.5px] uppercase tracking-wider text-dim">
            {game.fanduel?.source === 'espn' ? 'Line' : 'FanDuel'}
          </div>
          <span className="num text-xs font-semibold text-gold">
            {fixed(game.fanduel?.total_line ?? game.pregame_total, 1)}
          </span>
        </div>
        <div>
          <div className="text-[9.5px] uppercase tracking-wider text-dim">Proj</div>
          {game.projection ? (
            <Ticker
              value={game.projection.mean}
              format={(n) => n.toFixed(1)}
              flash={false}
              className="text-xs font-semibold text-peri"
            />
          ) : (
            <span className="num text-xs text-dim">—</span>
          )}
        </div>
      </div>
    </motion.button>
  )
}

export default function GameList() {
  const games = useStore((s) => s.games)
  const loaded = useStore((s) => s.gamesLoaded)
  const selectedId = useStore((s) => s.selectedGameId)
  const positions = useStore((s) => s.positions)

  const heldBy = (id: string) => positions.filter((p) => p.game_id === id).length
  const groups: { key: Game['state']; label: string }[] = [
    { key: 'live', label: 'Live' },
    { key: 'pre', label: 'Upcoming' },
    { key: 'final', label: 'Final' },
  ]

  if (!loaded) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-[128px] w-full !rounded-xl" />
        ))}
      </div>
    )
  }
  if (games.length === 0) {
    return (
      <Empty
        icon={<CalendarClock size={18} />}
        title="No games on the board"
        body="When NBA games are scheduled or a simulated slate is running, they show up here."
      />
    )
  }

  return (
    <div className="space-y-4 p-3">
      {groups.map(({ key, label }) => {
        const list = games.filter((g) => g.state === key)
        if (list.length === 0) return null
        return (
          <section key={key}>
            <div className="mb-2 flex items-center justify-between px-1">
              <span className="label">{label}</span>
              <span className="num text-[10px] text-dim">{list.length}</span>
            </div>
            <div className="space-y-2">
              {list.map((g) => (
                <GameCard key={g.id} game={g} selected={g.id === selectedId} held={heldBy(g.id)} />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
