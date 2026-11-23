import clsx from 'clsx'
import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'
import { relTime } from '../format'
import type { WatchNote } from '../types'
import { Spinner, Toggle } from './ui'

/** What "the agent watches this bet" means, in one place so every screen says the same thing. */
export const WATCH_RULE =
  'Claude keeps reading the game: the plays, runs, fouls, cards, who is on. If it judges the bet has turned against you and is worth less than the sell price, it sells. It looks more often when things get tense.'

const KEY = 'courtside.watch-new-bets'

/** Whether new orders start with the agent watching. Remembered on this device. */
export function useWatchNewBets(): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(KEY) === '1'
    } catch {
      return false
    }
  })
  const set = (v: boolean) => {
    setOn(v)
    try {
      localStorage.setItem(KEY, v ? '1' : '0')
    } catch {
      /* private window: it just will not be remembered */
    }
  }
  return [on, set]
}

/** The switch in an order form. */
export function WatchSwitch({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="mt-4 flex items-start gap-3 rounded-2xl bg-ink-800 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium text-white">Agent watches this bet</div>
        <p className="mt-0.5 text-xs leading-relaxed text-dim">{on ? WATCH_RULE : 'Off: only you can sell it.'}</p>
      </div>
      <Toggle checked={on} onChange={onChange} tone="#19c37d" label="Agent watches this bet" />
    </div>
  )
}

/** A tap-to-flip pill on an open bet, with Claude's latest read under it. `onChange` saves it. */
export function WatchPill({ on, onChange, note }: { on: boolean; onChange: (v: boolean) => Promise<void>; note?: WatchNote | null }) {
  const [busy, setBusy] = useState(false)
  const flip = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (busy) return
    setBusy(true)
    try {
      await onChange(!on)
    } finally {
      setBusy(false)
    }
  }
  const Icon = on ? Eye : EyeOff
  return (
    <>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        onClick={flip}
        title={on ? WATCH_RULE : 'Tap to let the agent sell this bet if it turns against you'}
        className={clsx(
          'inline-flex min-h-7 items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors',
          on ? 'bg-mint/[0.14] text-mint' : 'bg-white/[0.06] text-mute hover:text-white',
        )}
      >
        {busy ? <Spinner size={11} /> : <Icon size={12} />}
        {on ? 'Agent watching' : 'Not watched'}
      </button>
      {on && note && <WatchRead note={note} />}
    </>
  )
}

/** Claude's latest read on a watched bet, so you can see what it thinks without opening the game. */
function WatchRead({ note }: { note: WatchNote }) {
  const tone = note.concern === 'high' ? 'text-coral' : note.concern === 'medium' ? 'text-gold' : 'text-mint'
  return (
    <p className="mt-1 break-words text-xs leading-relaxed text-dim">
      <span className={clsx('font-semibold', tone)}>
        {note.action === 'sell' ? 'Selling' : 'Holding'} · rates it {Math.round(note.win_chance * 100)}%
      </span>{' '}
      · {relTime(note.at)}: {note.reason}
    </p>
  )
}
