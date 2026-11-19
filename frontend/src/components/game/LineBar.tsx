import clsx from 'clsx'

/**
 * The number line: where the score is now, where the betting line sits, where the game is
 * heading, and where the strike you picked is. The one picture that makes a total make sense.
 */
export default function LineBar({
  now,
  line,
  projected,
  spread,
  pick,
  pickLabel,
  held = [],
}: {
  /** Points scored so far (null before the start). */
  now: number | null
  line: number | null
  projected: number | null
  /** Roughly how far the finish could land either side of the projection. */
  spread?: number | null
  /** The strike currently selected in the order panel. */
  pick?: number | null
  pickLabel?: string
  /** Strikes the user already holds. */
  held?: number[]
}) {
  const anchors = [now, line, projected, pick ?? null, ...held].filter((v): v is number => v != null)
  if (line == null && projected == null) return null
  const lo = Math.floor(Math.min(...anchors) - 5)
  const hi = Math.ceil(Math.max(...anchors, (projected ?? line ?? 0) + (spread ?? 0)) + 5)
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100

  // Labels above the track: now and projected. Below: the line and your pick. When two on the
  // same row sit close, push them apart so they never print over each other.
  const anchor = (self: number | null, other: number | null): 'center' | 'left' | 'right' => {
    if (self == null) return 'center'
    // Near either end, hang the label inward so it never runs off a narrow screen.
    if (x(self) < 10) return 'left'
    if (x(self) > 90) return 'right'
    if (other == null || Math.abs(x(self) - x(other)) > 17) return 'center'
    return self <= other ? 'right' : 'left'
  }

  const cushion = pick != null && line != null ? pick - line : null

  return (
    <div className="select-none pb-11 pt-11">
      <div className="relative h-2 rounded-full bg-ink-800">
        {/* likely finishing range */}
        {projected != null && spread != null && spread > 0.5 && (
          <div
            className="absolute inset-y-0 rounded-full bg-white/[0.13] transition-all duration-500"
            style={{ left: `${Math.max(0, x(projected - spread))}%`, width: `${Math.min(100, x(projected + spread)) - Math.max(0, x(projected - spread))}%` }}
          />
        )}
        {/* points already scored */}
        {now != null && (
          <div className="absolute inset-y-0 left-0 rounded-full bg-white/45 transition-all duration-500" style={{ width: `${x(now)}%` }} />
        )}
        {/* cushion between the line and your pick */}
        {cushion != null && Math.abs(cushion) > 0.4 && (
          <div
            className={clsx('absolute -bottom-[3px] -top-[3px] rounded-sm', cushion > 0 ? 'bg-mint/25' : 'bg-gold/25')}
            style={{ left: `${Math.min(x(line as number), x(pick as number))}%`, width: `${Math.abs(x(pick as number) - x(line as number))}%` }}
          />
        )}

        {held.map((h) => (
          <span key={h} className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-mint bg-ink-950" style={{ left: `${x(h)}%` }} title={`You hold ${h}`} />
        ))}

        {now != null && (
          <Marker x={x(now)} place="above" anchor={anchor(now, projected)} dot="bg-white" label="Score now" value={String(now)} />
        )}
        {projected != null && (
          <Marker x={x(projected)} place="above" anchor={anchor(projected, now)} dot="bg-white/50" label="Heading for" value={projected.toFixed(0)} dim />
        )}
        {line != null && (
          <Marker x={x(line)} place="below" anchor={anchor(line, pick ?? null)} tick="bg-white" label="The line" value={String(line)} />
        )}
        {pick != null && (
          <Marker x={x(pick)} place="below" anchor={anchor(pick, line)} tick="bg-mint" label={pickLabel ?? 'Your pick'} value={String(pick)} tone="text-mint" />
        )}
      </div>
    </div>
  )
}

function Marker({
  x,
  place,
  anchor,
  label,
  value,
  dot,
  tick,
  dim,
  tone,
}: {
  x: number
  place: 'above' | 'below'
  anchor: 'center' | 'left' | 'right'
  label: string
  value: string
  dot?: string
  tick?: string
  dim?: boolean
  tone?: string
}) {
  const shift = anchor === 'center' ? '-translate-x-1/2 items-center text-center' : anchor === 'right' ? '-translate-x-full items-end pr-1 text-right' : 'items-start pl-1 text-left'
  return (
    <div className="absolute top-1/2 transition-[left] duration-500" style={{ left: `${Math.min(100, Math.max(0, x))}%` }}>
      {dot && <span className={clsx('absolute h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-4 ring-ink-900', dot)} />}
      {tick && <span className={clsx('absolute h-5 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full', tick)} />}
      <div className={clsx('absolute flex w-max flex-col leading-tight', shift, place === 'above' ? 'bottom-3.5' : 'top-3.5')}>
        <span className={clsx('text-xs', dim ? 'text-dim' : 'text-mute')}>{label}</span>
        <span className={clsx('num text-[15px] font-semibold', tone ?? (dim ? 'text-slate-300' : 'text-white'))}>{value}</span>
      </div>
    </div>
  )
}
