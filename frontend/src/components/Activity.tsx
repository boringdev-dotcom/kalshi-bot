import { AnimatePresence, motion } from 'framer-motion'
import clsx from 'clsx'
import { ChevronDown } from 'lucide-react'
import { useMemo, useState } from 'react'
import { relTime } from '../format'
import { useStore } from '../store'
import type { Decision } from '../types'
import { Empty } from './ui'

const GREEN = '#19c37d'
const RED = '#f2594b'
const AMBER = '#e6a93c'
const GREY = '#6f7179'
const NEUTRAL = '#a1a3ab'

/** "+12.50", "−14.65", "$-3" → a number, or null when there is no result on the decision. */
function pnlOf(d: Decision): number | null {
  const raw = d.data?.pnl
  if (raw == null) return null
  if (typeof raw === 'number') return raw
  const n = parseFloat(String(raw).replace('−', '-').replace(/[^0-9.+-]/g, ''))
  return Number.isNaN(n) ? null : n
}

/** One colour per kind of thing the agent did: bought, sold (by result), passed, or just talking. */
function dotColor(d: Decision) {
  if (d.kind === 'enter') return GREEN
  if (d.kind === 'exit') {
    const pnl = pnlOf(d)
    return pnl == null ? AMBER : pnl >= 0 ? GREEN : RED
  }
  if (d.kind === 'skip') return GREY
  return NEUTRAL
}

const kindWord: Record<Decision['kind'], string> = {
  enter: 'Bought',
  exit: 'Sold',
  skip: 'Passed',
  hold: 'Holding',
  note: 'Note',
}

function prettyKey(k: string) {
  const s = k.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function prettyValue(v: number | string) {
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return v.toString()
    return Math.abs(v) < 1 ? v.toFixed(3).replace(/0+$/, '').replace(/\.$/, '') : v.toFixed(1)
  }
  // The backend writes prices as "94c".
  return v.replace(/(\d)c\b/g, '$1¢')
}

function Row({ d, compact }: { d: Decision; compact?: boolean }) {
  const [open, setOpen] = useState(false)
  const [details, setDetails] = useState(false)
  const facts = Object.entries(d.data ?? {})
  const quiet = d.kind === 'skip' || d.kind === 'hold'
  return (
    <li className="border-b border-hair last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={clsx(
          'flex w-full items-start gap-3 rounded-xl px-1 text-left transition-colors hover:bg-white/[0.035]',
          compact ? 'py-2.5' : 'py-3.5',
        )}
      >
        <span
          className="mt-[7px] h-2 w-2 shrink-0 rounded-full"
          style={{ background: dotColor(d) }}
          title={kindWord[d.kind] ?? 'Note'}
        />
        <span className="min-w-0 flex-1">
          <span className={clsx('block leading-snug', compact ? 'text-[13px]' : 'text-sm', quiet ? 'text-slate-300' : 'font-medium text-white')}>
            {d.headline}
          </span>
          <span className="mt-0.5 block text-xs text-dim">
            {d.game_label ? `${d.game_label} · ` : ''}
            <span title={d.ts}>{relTime(d.ts)}</span>
          </span>
        </span>
        <ChevronDown size={15} className={clsx('mt-1 shrink-0 text-dim transition-transform', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.16 }}
            className="overflow-hidden"
          >
            <div className="pb-4 pl-6 pr-2">
              <p className="hint text-slate-300">{d.reasoning}</p>
              {(facts.length > 0 || d.source === 'claude' || d.memory_ids?.length > 0) && (
                <button
                  type="button"
                  onClick={() => setDetails((v) => !v)}
                  className="mt-2 flex items-center gap-1 text-xs font-medium text-mute hover:text-white"
                >
                  Details
                  <ChevronDown size={12} className={clsx('transition-transform', details && 'rotate-180')} />
                </button>
              )}
              {details && (
                <div className="mt-2 rounded-xl bg-ink-800 px-3.5 py-3">
                  {facts.length > 0 && (
                    <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
                      {facts.map(([k, v]) => (
                        <div key={k} className="min-w-0">
                          <dt className="truncate text-[11px] text-dim">{prettyKey(k)}</dt>
                          <dd className="num truncate text-[13px] text-slate-200">{prettyValue(v)}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  <div className={clsx('space-y-0.5 text-xs text-dim', facts.length > 0 && 'mt-2.5')}>
                    {d.source === 'claude' && <div>Claude reviewed this one.</div>}
                    {d.memory_ids?.length > 0 && (
                      <div>
                        It kept {d.memory_ids.length} {d.memory_ids.length === 1 ? 'thing' : 'things'} from memory in mind.
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

/**
 * What the agent has been doing, newest first, in plain sentences.
 * `gameId` narrows it to one game; `compact` drops the filter and tightens the rows for use inside other pages.
 */
export function ActivityFeed({
  gameId,
  limit,
  compact = false,
}: {
  gameId?: string | null
  limit?: number
  compact?: boolean
}) {
  const decisions = useStore((s) => s.decisions)
  // Start on the trades: "passed on…" notes are there when you want them, but they are most of the list.
  const hasTrades = useStore((s) => s.decisions.some((d) => d.kind === 'enter' || d.kind === 'exit'))
  const [chosen, setOnly] = useState<'all' | 'trades' | null>(null)
  const only = chosen ?? (hasTrades && !compact ? 'trades' : 'all')
  const max = limit ?? (compact ? 6 : 80)

  const list = useMemo(
    () =>
      decisions
        .filter((d) => (gameId ? d.game_id === gameId : true))
        .filter((d) => (only === 'trades' ? d.kind === 'enter' || d.kind === 'exit' : true))
        .slice(0, max),
    [decisions, gameId, only, max],
  )

  return (
    <div>
      {!compact && (
        <div className="mb-2 flex items-center gap-2">
          {(
            [
              { value: 'all', label: 'All' },
              { value: 'trades', label: 'Trades only' },
            ] as const
          ).map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setOnly(f.value)}
              className={clsx(
                'rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors',
                only === f.value ? 'bg-white text-ink-950' : 'bg-ink-800 text-mute hover:text-white',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      )}
      {list.length === 0 ? (
        <Empty
          className={compact ? '!py-6' : undefined}
          title={only === 'trades' ? 'No trades yet' : gameId ? 'Nothing on this game yet' : 'Nothing to show yet'}
          body={
            only === 'trades'
              ? 'When the agent buys or sells, it shows up here with the reason.'
              : 'Every time the agent buys, sells or passes on a game, it says so here and explains why.'
          }
        />
      ) : (
        <ul>
          {list.map((d) => (
            <Row key={d.id} d={d} compact={compact} />
          ))}
        </ul>
      )}
    </div>
  )
}

export default ActivityFeed
