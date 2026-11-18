import { motion } from 'framer-motion'
import clsx from 'clsx'
import { AlertTriangle, ShieldCheck } from 'lucide-react'
import { american, clockSeconds, fixed, pct, periodLabel, riskTone, spread, startTime, teamColor } from '../format'
import type { Game, TeamSide } from '../types'
import { Badge, Card, SimTag, Ticker } from './ui'

function ClockRing({ game }: { game: Game }) {
  const size = 92
  const r = 40
  const c = 2 * Math.PI * r
  const periodLen = game.period > 4 ? 300 : 720
  const left = game.state === 'live' ? clockSeconds(game.clock) : game.state === 'final' ? 0 : periodLen
  const frac = Math.min(1, Math.max(0, left / periodLen))
  const tone = riskTone[game.risk.level].dot
  const live = game.state === 'live'
  const color = live ? (game.period >= 4 ? tone : '#8b9cff') : '#5d6577'

  return (
    <div className="relative flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="4" />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={c}
          initial={false}
          animate={{ strokeDashoffset: c * (1 - frac) }}
          transition={{ type: 'spring', stiffness: 60, damping: 20 }}
          style={{ filter: live ? `drop-shadow(0 0 6px ${color}88)` : undefined }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        {game.state === 'pre' ? (
          <>
            <span className="text-[10px] font-semibold uppercase tracking-widest text-dim">Tip</span>
            <span className="num mt-0.5 px-2 text-center text-[11px] font-semibold leading-tight text-slate-200">
              {startTime(game.start_time)}
            </span>
          </>
        ) : game.state === 'final' ? (
          <>
            <span className="text-[13px] font-bold uppercase tracking-widest text-slate-200">Final</span>
            {game.period > 4 && <span className="num text-[10px] text-dim">{periodLabel(game.period)}</span>}
          </>
        ) : (
          <>
            <span className="text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color }}>
              {periodLabel(game.period)}
            </span>
            <span className="num text-[19px] font-bold leading-tight text-slate-50">{game.clock}</span>
          </>
        )}
      </div>
    </div>
  )
}

function Team({ team, align, leading, started }: { team: TeamSide; align: 'left' | 'right'; leading: boolean; started: boolean }) {
  const color = teamColor(team.color)
  return (
    <div className={clsx('flex min-w-0 flex-1 items-center gap-4', align === 'right' && 'flex-row-reverse text-right')}>
      <div className="min-w-0">
        <div className="text-[26px] font-extrabold leading-none tracking-tight" style={{ color }}>
          {team.abbr}
        </div>
        <div className="mt-1 truncate text-[11px] text-dim">{team.name}</div>
      </div>
      <div className={clsx('flex-1', align === 'left' ? 'text-right' : 'text-left')}>
        {started ? (
          <Ticker
            value={team.score}
            className={clsx(
              'text-[44px] font-bold leading-none tracking-tight',
              leading ? 'text-slate-50' : 'text-slate-500',
            )}
          />
        ) : (
          <span className="num text-[44px] font-bold leading-none text-ink-600">–</span>
        )}
      </div>
    </div>
  )
}

/** Quarter-by-quarter points for both teams, current period highlighted. */
function Linescore({ game }: { game: Game }) {
  const away = game.away.quarters ?? []
  const home = game.home.quarters ?? []
  const periods = Math.max(4, away.length, home.length)
  if (game.state === 'pre' || (away.length === 0 && home.length === 0)) return null
  const cols = Array.from({ length: periods }, (_, i) => i)
  const current = game.state === 'live' ? game.period - 1 : -1
  const head = (i: number) => (i < 4 ? `Q${i + 1}` : i === 4 ? 'OT' : `${i - 3}OT`)
  const row = (team: TeamSide, pts: number[]) => (
    <tr>
      <td className="pr-3 text-left text-[10.5px] font-bold tracking-wide" style={{ color: teamColor(team.color) }}>
        {team.abbr}
      </td>
      {cols.map((i) => (
        <td
          key={i}
          className={clsx(
            'num w-9 px-1 text-center text-[11.5px]',
            i === current ? 'font-bold text-slate-50' : pts[i] == null ? 'text-ink-600' : 'text-slate-300',
          )}
        >
          {pts[i] == null ? '–' : pts[i]}
        </td>
      ))}
      <td className="num w-10 pl-2 text-right text-[11.5px] font-bold text-slate-100">{team.score}</td>
    </tr>
  )
  return (
    <div className="mt-4 flex justify-center">
      <table className="border-separate border-spacing-y-0.5">
        <thead>
          <tr>
            <th />
            {cols.map((i) => (
              <th
                key={i}
                className={clsx(
                  'w-9 px-1 text-center text-[9px] font-semibold uppercase tracking-wider',
                  i === current ? 'text-peri' : 'text-dim',
                )}
              >
                {head(i)}
              </th>
            ))}
            <th className="w-10 pl-2 text-right text-[9px] font-semibold uppercase tracking-wider text-dim">T</th>
          </tr>
        </thead>
        <tbody>
          {row(game.away, away)}
          {row(game.home, home)}
        </tbody>
      </table>
    </div>
  )
}

function Cell({ label, children, sub }: { label: string; children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <div className="label !text-[9.5px]">{label}</div>
      <div className="num mt-1 text-[15px] font-semibold text-slate-100">{children}</div>
      {sub && <div className="mt-0.5 truncate text-[10.5px] text-dim">{sub}</div>}
    </div>
  )
}

const tint = (hex: string) => teamColor(hex).replace('rgb(', 'rgba(').replace(')', ', 0.10)')

const sourceLabel = { fanduel: 'FanDuel', sim: 'Simulated book', espn: 'ESPN consensus' } as const

export default function Scorebug({ game }: { game: Game }) {
  const started = game.state !== 'pre'
  const fd = game.fanduel
  const proj = game.projection
  const line = fd?.total_line ?? game.pregame_total
  const diff = proj && line != null ? proj.mean - line : null
  const risk = riskTone[game.risk.level]

  return (
    <Card className="overflow-hidden">
      <div
        className="relative px-6 pb-5 pt-5"
        style={{
          background: `linear-gradient(90deg, ${tint(game.away.color)} 0%, transparent 38%, transparent 62%, ${tint(game.home.color)} 100%)`,
        }}
      >
        <div className="absolute left-4 top-3 flex items-center gap-1.5">
          {game.simulated && <SimTag />}
          {game.event_ticker && <span className="num text-[10px] text-dim">{game.event_ticker}</span>}
        </div>
        <div className="flex items-center gap-6 pt-3">
          <Team team={game.away} align="left" leading={game.away.score >= game.home.score} started={started} />
          <ClockRing game={game} />
          <Team team={game.home} align="right" leading={game.home.score >= game.away.score} started={started} />
        </div>
        <Linescore game={game} />
      </div>

      <div className="grid grid-cols-2 divide-x divide-hair border-t border-hair md:grid-cols-5 [&>*]:border-hair">
        <Cell label="Total" sub={started ? `Margin ${Math.abs(game.margin)}` : 'Not started'}>
          {started ? <Ticker value={game.total} className="text-slate-50" /> : '—'}
        </Cell>
        <Cell
          label="Projected final"
          sub={proj ? `± ${fixed(proj.sd, 1)} pts · pace ${fixed(proj.pace, 0)}` : 'Waiting for tip-off'}
        >
          {proj ? (
            <span className="text-peri">
              <Ticker value={proj.mean} format={(n) => n.toFixed(1)} flash={false} />
            </span>
          ) : (
            '—'
          )}
        </Cell>
        <Cell
          label={fd ? `${sourceLabel[fd.source]} total` : 'Book total'}
          sub={
            fd ? (
              <span>
                O {american(fd.over_price)} · U {american(fd.under_price)}
                <span className={clsx('ml-1.5', fd.live ? 'text-mint' : 'text-dim')}>{fd.live ? 'in-play' : 'pregame'}</span>
              </span>
            ) : game.pregame_total != null ? (
              'Pregame close'
            ) : (
              'No line yet'
            )
          }
        >
          <span className="text-gold">{fixed(line, 1)}</span>
          {diff != null && (
            <span className={clsx('ml-2 text-[11px] font-medium', diff > 0 ? 'text-coral' : 'text-mint')} title="Projection minus book line">
              {diff > 0 ? '+' : '−'}
              {Math.abs(diff).toFixed(1)}
            </span>
          )}
        </Cell>
        <Cell
          label="Spread / ML"
          sub={fd ? `${game.away.abbr} ${american(fd.away_ml)} · ${game.home.abbr} ${american(fd.home_ml)}` : '—'}
        >
          {fd?.spread != null ? `${game.home.abbr} ${spread(fd.spread)}` : '—'}
        </Cell>
        <Cell label="Overtime chance" sub={proj ? 'adds ~20 pts if it happens' : '—'}>
          {proj ? (
            <span className={proj.p_ot > 0.12 ? 'text-coral' : proj.p_ot > 0.05 ? 'text-gold' : 'text-slate-100'}>
              {pct(proj.p_ot, 1)}
            </span>
          ) : (
            '—'
          )}
        </Cell>
      </div>

      {game.state === 'live' && (
        <div className={clsx('flex flex-wrap items-center gap-2 border-t border-hair px-4 py-2.5', risk.bg)}>
          <span className={clsx('flex items-center gap-1.5 text-[11px] font-semibold', risk.text)}>
            {game.risk.level === 'low' ? <ShieldCheck size={13} /> : <AlertTriangle size={13} />}
            {risk.label}
          </span>
          {game.risk.flags.length === 0 ? (
            <span className="text-[11px] text-mute">Nothing unusual in this game right now.</span>
          ) : (
            game.risk.flags.map((f) => (
              <Badge key={f} tone={game.risk.level === 'high' ? 'coral' : game.risk.level === 'medium' ? 'gold' : 'slate'} className="!normal-case !tracking-normal">
                {f}
              </Badge>
            ))
          )}
        </div>
      )}
    </Card>
  )
}
