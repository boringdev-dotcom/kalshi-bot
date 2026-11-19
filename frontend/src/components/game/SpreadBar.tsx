import { teamColor } from '../../format'
import { marginText } from '../../lib'
import type { TeamSide } from '../../types'
import { Marker } from './LineBar'

/**
 * The spread version of the line bar. One axis for the margin, with a tie in the middle:
 * the away team winning to the left, the home team winning to the right. It shows where the
 * margin is now, where the market's line sits, where the model thinks it ends, and the part
 * of the axis where the picked bet pays.
 *
 * Every value is a home margin (home points minus away points).
 */
export default function SpreadBar({
  home,
  away,
  now,
  line,
  projected,
  spread,
  pick,
  held = [],
}: {
  home: TeamSide
  away: TeamSide
  now: number | null
  line: number | null
  projected: number | null
  /** How far either side of the projection the margin could reasonably end. */
  spread?: number | null
  /** The bet in the order panel: where it starts winning, which way, and its name. */
  pick?: { threshold: number; dir: 'left' | 'right'; label: string } | null
  /** Where bets you already hold start winning. */
  held?: number[]
}) {
  if (line == null && projected == null && now == null) return null

  const reach = Math.max(
    8,
    ...[now, line, pick?.threshold ?? null, ...held].filter((v): v is number => v != null).map(Math.abs),
    projected != null ? Math.abs(projected) + (spread ?? 0) : 0,
  )
  const R = Math.ceil(reach + 2)
  const x = (v: number) => ((Math.max(-R, Math.min(R, v)) + R) / (2 * R)) * 100

  // Same label rules as the totals bar: keep end labels on screen, push close neighbours apart.
  // `first` breaks ties: when two labels share a row and land on the same spot, the first
  // one hangs left and the other hangs right, so they never print on top of each other.
  const anchor = (self: number | null, other: number | null, first = false): 'center' | 'left' | 'right' => {
    if (self == null) return 'center'
    if (x(self) < 12) return 'left'
    if (x(self) > 88) return 'right'
    if (other == null || Math.abs(x(self) - x(other)) > 18) return 'center'
    if (Math.abs(x(self) - x(other)) < 0.5) return first ? 'right' : 'left'
    return self < other ? 'right' : 'left'
  }

  const say = (m: number, round = false) => marginText(m, home.abbr, away.abbr, round)

  return (
    <div className="select-none">
      <div className="pb-12 pt-11">
        <div className="relative h-2 rounded-full bg-ink-800">
          {/* where the picked bet pays */}
          {pick && (
            <div
              className="absolute -bottom-[3px] -top-[3px] rounded-sm bg-mint/20 transition-all duration-300"
              style={
                pick.dir === 'right'
                  ? { left: `${x(pick.threshold)}%`, right: 0 }
                  : { left: 0, width: `${x(pick.threshold)}%` }
              }
            />
          )}
          {/* likely finishing range */}
          {projected != null && spread != null && spread > 0.5 && (
            <div
              className="absolute inset-y-0 rounded-full bg-white/[0.13] transition-all duration-500"
              style={{ left: `${x(projected - spread)}%`, width: `${x(projected + spread) - x(projected - spread)}%` }}
            />
          )}
          {/* the tie */}
          <span className="absolute left-1/2 top-1/2 h-4 w-px -translate-x-1/2 -translate-y-1/2 bg-white/25" />

          {held.map((h) => (
            <span
              key={h}
              className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-mint bg-ink-950"
              style={{ left: `${x(h)}%` }}
              title="One of your bets turns at this margin"
            />
          ))}

          {now != null && (
            <Marker x={x(now)} place="above" anchor={anchor(now, projected, true)} dot="bg-white" label="Now" value={say(now)} />
          )}
          {projected != null && (
            <Marker x={x(projected)} place="above" anchor={anchor(projected, now)} dot="bg-white/50" label="Heading for" value={say(projected, true)} dim />
          )}
          {line != null && (
            <Marker x={x(line)} place="below" anchor={anchor(line, pick?.threshold ?? null, true)} tick="bg-white" label="The line" value={say(line)} />
          )}
          {pick && (
            <Marker
              x={x(pick.threshold)}
              place="below"
              anchor={anchor(pick.threshold, line)}
              tick="bg-mint"
              label="Your pick"
              value={pick.label}
              tone="text-mint"
            />
          )}
        </div>
      </div>

      {/* which side is which */}
      <div className="flex items-center justify-between text-xs text-dim">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: teamColor(away.color) }} />← {away.abbr} winning
        </span>
        <span>Tied</span>
        <span className="flex items-center gap-1.5">
          {home.abbr} winning →<span className="h-2 w-2 rounded-full" style={{ background: teamColor(home.color) }} />
        </span>
      </div>
    </div>
  )
}

