import clsx from 'clsx'
import { useMemo, useState } from 'react'
import { cents, noLabel, teamColor, yesLabel } from '../../format'
import { type Pick } from '../../lib'
import type { Game, LadderRung, Side } from '../../types'
import { Badge, Empty, Skeleton } from '../ui'

const GOOD_EDGE = 0.02 // the model has to like a price by two points before we say so

/** One side's buy button: the name of the bet and what it costs. */
function PriceButton({
  label,
  price,
  selected,
  disabled,
  onClick,
  wide,
}: {
  label: string
  price: number | null
  selected: boolean
  disabled: boolean
  onClick: () => void
  /** Spread names ("CHA +11.5") need more room than "Under". */
  wide?: boolean
}) {
  const off = disabled || price == null
  return (
    <button
      onClick={onClick}
      disabled={off}
      title={off ? 'No one is selling this right now' : `Buy ${label} at ${cents(price)}`}
      className={clsx(
        // Phones: a stacked tile (name over price) so two fit beside the line.
        // Wider screens: one pill with the name and price side by side.
        'flex shrink-0 flex-col items-center justify-center rounded-2xl font-medium transition-colors',
        'h-[52px] sm:h-11 sm:flex-row sm:justify-between sm:gap-2 sm:rounded-full',
        wide ? 'w-[92px] px-1.5 sm:w-[142px] sm:px-3.5' : 'w-[78px] px-1.5 sm:w-[124px] sm:px-4',
        selected ? 'bg-white text-ink-950' : 'bg-ink-800 text-slate-200 active:bg-ink-700 sm:hover:bg-ink-700',
        off && 'cursor-not-allowed opacity-35 hover:bg-ink-800',
      )}
    >
      <span className={clsx('max-w-full truncate text-[11px] leading-tight sm:text-[13px]', !selected && 'text-mute sm:text-slate-200')}>{label}</span>
      <span className="num text-[15px] font-semibold leading-tight sm:text-[13px]">{price == null ? '–' : cents(price)}</span>
    </button>
  )
}

/** A thin bar for "how likely", so the eye can compare rows without reading numbers. */
function ChanceBar({ value }: { value: number | null }) {
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-ink-800">
      <div className="h-full rounded-full bg-white/50 transition-all duration-500" style={{ width: `${Math.round((value ?? 0) * 100)}%` }} />
    </div>
  )
}

function Row({
  title,
  sub,
  chance,
  chanceText,
  tag,
  owned,
  left,
  right,
}: {
  title: React.ReactNode
  sub: string
  chance: number | null
  chanceText: string
  tag?: string | null
  owned: boolean
  left: React.ReactNode
  right: React.ReactNode
}) {
  return (
    <div className="row !gap-3 !py-3 sm:!gap-5 sm:!py-3.5">
      <div className="min-w-0 flex-1 sm:w-[136px] sm:flex-none sm:shrink-0">
        <div className="num whitespace-nowrap text-[17px] font-semibold leading-tight text-white">{title}</div>
        <div className="mt-0.5 text-xs text-dim">
          {sub}
          {owned && <span className="text-mint xl:hidden"> · yours</span>}
        </div>
      </div>
      <div className="hidden min-w-0 flex-1 xl:block">
        <div className="mb-1.5 flex items-center gap-2 text-[13px] text-mute">
          <span className="truncate">{chanceText}</span>
          {tag && <Badge tone="mint">{tag}</Badge>}
          {owned && <Badge tone="slate">You own this</Badge>}
        </div>
        <ChanceBar value={chance} />
      </div>
      <div className="ml-auto flex shrink-0 gap-1.5 sm:gap-2">
        {left}
        {right}
      </div>
    </div>
  )
}

export default function MarketList({
  game,
  rungs,
  kind,
  line,
  spreadLine = null,
  pick,
  onPick,
  owned,
  closed,
  loading,
  emptyText,
}: {
  game: Game
  rungs: LadderRung[] | null
  kind: 'total' | 'spread'
  /** The betting line for this segment's total, used to say how far each strike sits from it. */
  line: number | null
  /** Spreads only: the margin Kalshi prices at 50/50, as home points minus away points. */
  spreadLine?: number | null
  pick: Pick | null
  onPick: (p: Pick) => void
  owned: Set<string>
  closed: boolean
  loading: boolean
  emptyText: string
}) {
  const [showAll, setShowAll] = useState(false)
  const is = (r: LadderRung, side: Side) => pick?.ticker === r.ticker && pick.side === side

  const sorted = useMemo(() => [...(rungs ?? [])].sort((a, b) => a.strike - b.strike), [rungs])
  // A full-game ladder has ~30 strikes. Start with the ones around the line and a little above it,
  // which is where nearly all the action is; the rest are one tap away.
  const windowed = useMemo(() => {
    if (kind !== 'total' || showAll || line == null || sorted.length <= 14) return sorted
    const near = sorted.filter((r) => r.strike >= line - 7 && r.strike <= line + 17)
    const keep = new Set(near.map((r) => r.ticker))
    sorted.forEach((r) => (owned.has(r.ticker) || r.ticker === pick?.ticker) && keep.add(r.ticker))
    return sorted.filter((r) => keep.has(r.ticker))
  }, [sorted, kind, showAll, line, owned, pick?.ticker])

  if (loading) {
    return (
      <div className="space-y-3 py-2">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    )
  }
  if (!rungs || rungs.length === 0) return <Empty title="Nothing to trade here yet" body={emptyText} />

  if (kind === 'spread') {
    const teams = [game.away, game.home]
    return (
      <div>
        {teams.map((team) => {
          const mine = sorted.filter((r) => r.team === team.abbr)
          if (mine.length === 0) return null
          const other = team.abbr === game.home.abbr ? game.away : game.home
          // The line in this team's terms. Only the favourite's list has rows on both sides of it.
          const lineHere = spreadLine == null ? null : team.abbr === game.home.abbr ? spreadLine : -spreadLine
          const showLine = !closed && lineHere != null && lineHere > 0.25
          const lineAt = showLine ? mine.findIndex((r) => r.strike > (lineHere as number)) : -1
          const divider = (
            <div className="flex items-center gap-3 py-2 text-xs font-medium text-mute">
              <span className="h-px flex-1 bg-white/20" />
              The line is {team.abbr} by {Math.round((lineHere ?? 0) * 2) / 2}
              <span className="h-px flex-1 bg-white/20" />
            </div>
          )
          return (
            <div key={team.abbr} className="mb-4 last:mb-0">
              <div className="flex items-center gap-2 pb-1 pt-3 text-[13px] font-medium text-slate-200">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: teamColor(team.color) }} />
                {team.abbr} to win it by…
              </div>
              {!closed && lineHere != null && lineHere < -0.25 && (
                <div className="pb-1 text-xs text-dim">The line has {other.abbr} winning this quarter, so each of these needs {team.abbr} to come out on top.</div>
              )}
              {mine.map((r, i) => {
                const by = Math.ceil(r.strike)
                const chance = r.yes_ask != null ? r.yes_ask / 100 : null
                return (
                  <div key={r.ticker}>
                    {showLine && i === lineAt && divider}
                    <Row
                    title={
                      <>
                        <span className="sm:hidden">{by}+ pts</span>
                        <span className="hidden sm:inline">{by} or more</span>
                      </>
                    }
                    sub={yesLabel(r)}
                    chance={chance}
                    chanceText={chance == null ? 'No price right now' : `${Math.round(chance * 100)}% chance ${team.abbr} win it by ${by}+`}
                    tag={(r.edge_over ?? 0) >= GOOD_EDGE ? `Model likes ${team.abbr}` : (r.edge_under ?? 0) >= GOOD_EDGE ? `Model likes ${other.abbr}` : null}
                    owned={owned.has(r.ticker)}
                    left={<PriceButton wide label={yesLabel(r)} price={r.yes_ask} selected={is(r, 'over')} disabled={closed} onClick={() => onPick({ ticker: r.ticker, side: 'over' })} />}
                    right={<PriceButton wide label={noLabel(r)} price={r.no_ask} selected={is(r, 'under')} disabled={closed} onClick={() => onPick({ ticker: r.ticker, side: 'under' })} />}
                  />
                  </div>
                )
              })}
              {showLine && lineAt === -1 && divider}
            </div>
          )
        })}
      </div>
    )
  }

  // Totals: strikes low to high, with a marker where the line falls between them.
  const lineIndex = line == null ? -1 : windowed.findIndex((r) => r.strike > line)
  return (
    <div>
      {windowed.map((r, i) => {
        const diff = line == null ? null : r.strike - line
        const sub = diff == null ? 'points' : Math.abs(diff) < 0.75 ? 'right at the line' : diff > 0 ? `${fmt(diff)} above the line` : `${fmt(-diff)} below the line`
        const chance = r.no_ask != null ? r.no_ask / 100 : r.yes_bid != null ? 1 - r.yes_bid / 100 : null
        return (
          <div key={r.ticker}>
            {i === lineIndex && line != null && (
              <div className="flex items-center gap-3 py-2 text-xs font-medium text-mute">
                <span className="h-px flex-1 bg-white/20" />
                The line is {line}
                <span className="h-px flex-1 bg-white/20" />
              </div>
            )}
            <Row
              title={String(r.strike)}
              sub={sub}
              chance={chance}
              chanceText={chance == null ? 'No price right now' : `${Math.round(chance * 100)}% chance it stays under`}
              tag={(r.edge_under ?? 0) >= GOOD_EDGE ? 'Model likes under' : (r.edge_over ?? 0) >= GOOD_EDGE ? 'Model likes over' : null}
              owned={owned.has(r.ticker)}
              left={<PriceButton label="Under" price={r.no_ask} selected={is(r, 'under')} disabled={closed} onClick={() => onPick({ ticker: r.ticker, side: 'under' })} />}
              right={<PriceButton label="Over" price={r.yes_ask} selected={is(r, 'over')} disabled={closed} onClick={() => onPick({ ticker: r.ticker, side: 'over' })} />}
            />
          </div>
        )
      })}
      {kind === 'total' && sorted.length > windowed.length && (
        <button onClick={() => setShowAll(true)} className="mt-3 w-full rounded-full py-2.5 text-[13px] font-medium text-mute transition-colors hover:bg-white/[0.04] hover:text-white">
          Show all {sorted.length} lines
        </button>
      )}
      {showAll && sorted.length > 14 && (
        <button onClick={() => setShowAll(false)} className="mt-3 w-full rounded-full py-2.5 text-[13px] font-medium text-mute transition-colors hover:bg-white/[0.04] hover:text-white">
          Show fewer
        </button>
      )}
    </div>
  )
}

const fmt = (n: number) => `${Number.isInteger(n) ? n : n.toFixed(1)}`
