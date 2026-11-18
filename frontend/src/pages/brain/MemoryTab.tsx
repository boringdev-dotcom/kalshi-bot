import clsx from 'clsx'
import { Library, Pin, PinOff, Search, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { Button, Card, Empty, Skeleton, SimTag } from '../../components/ui'
import { pct, relTime } from '../../format'
import { useStore } from '../../store'
import type { Memory, MemoryKind } from '../../types'

const KINDS: MemoryKind[] = ['guidance', 'lesson', 'episode']

const kindMeta: Record<MemoryKind, { title: string; blurb: string }> = {
  guidance: { title: 'Your guidance', blurb: 'Things you told it. It checks these before every trade.' },
  lesson: { title: 'What it learned', blurb: 'Conclusions it drew from how trades turned out.' },
  episode: { title: 'Trade history', blurb: 'A short record of each trade and how it ended.' },
}

const EXAMPLES = [
  'In the 4th quarter I buy the under 10 to 12 points above the line.',
  'In a one-possession game with under two minutes left, get out. Fouls and overtime kill unders.',
  'Never risk more than $300 to make $20.',
  'Skip games where both teams are in the bonus early in the 4th.',
]

/** How well results have backed a memory up, in words. The numbers go in the tooltip. */
function standing(m: Memory): { word: string; className: string; title: string } {
  const total = m.support + m.against
  const title =
    total > 0
      ? `${m.support} ${m.support === 1 ? 'trade' : 'trades'} agreed, ${m.against} disagreed · confidence ${pct(m.confidence)} · weight ${pct(m.importance)}`
      : `No trade has tested this yet · weight ${pct(m.importance)}`
  if (total === 0) return { word: 'untested', className: 'text-dim', title }
  if (m.confidence >= 0.66) return { word: 'well supported', className: 'text-mint', title }
  if (m.confidence >= 0.4) return { word: 'mixed', className: 'text-gold', title }
  return { word: 'not holding up', className: 'text-coral', title }
}

function Teach({ onAdded }: { onAdded: (m: Memory) => void }) {
  const toast = useStore((s) => s.toast)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLTextAreaElement | null>(null)

  const submit = async () => {
    const t = text.trim()
    if (!t || busy) return
    setBusy(true)
    try {
      const m = await api.addGuidance(t)
      onAdded(m)
      setText('')
      const claude = useStore.getState().app?.health.anthropic
      toast(
        claude
          ? { level: 'success', title: 'Got it', body: 'Saved. Claude is working out what to change; watch the Activity tab.' }
          : {
              level: 'warn',
              title: 'Saved, but not acted on yet',
              body: 'It is pinned in memory. Turning plain words into rule changes needs Claude: add ANTHROPIC_API_KEY, or set the sliders on the Rules tab yourself.',
            },
      )
    } catch (e) {
      toast({ level: 'error', title: 'Could not save that', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="p-6">
      <h3 className="h-section">Teach the agent</h3>
      <p className="hint mt-1 max-w-2xl">
        Say it the way you would tell another trader. It is kept at the top of the agent’s memory and checked before every
        trade.
      </p>
      <textarea
        ref={ref}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit()
        }}
        rows={3}
        placeholder="For example: when the lead is under 4 with less than 3 minutes left, sell even at a small loss."
        aria-label="Guidance for the agent"
        className="field mt-4 resize-none !rounded-2xl !px-4 !py-3.5 !text-[15px] leading-relaxed"
      />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <span className="text-xs text-dim">⌘ or Ctrl + Enter also saves</span>
        <Button variant="primary" size="md" onClick={submit} loading={busy} disabled={!text.trim()}>
          Teach
        </Button>
      </div>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            title={ex}
            onClick={() => {
              setText(ex)
              ref.current?.focus()
            }}
            className="rounded-full bg-ink-800 px-3 py-1.5 text-[13px] text-mute transition-colors hover:bg-ink-700 hover:text-white"
          >
            {ex.length > 60 ? `${ex.slice(0, 58)}…` : ex}
          </button>
        ))}
      </div>
    </Card>
  )
}

function MemoryRow({ m, onPin, onDelete }: { m: Memory; onPin: (m: Memory) => void; onDelete: (m: Memory) => void }) {
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState(false)
  useEffect(() => {
    if (!confirm) return
    const t = window.setTimeout(() => setConfirm(false), 2600)
    return () => window.clearTimeout(t)
  }, [confirm])
  const s = standing(m)

  return (
    <li className="group flex items-start gap-3 border-b border-hair py-3.5 last:border-b-0">
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setOpen((o) => !o)
          }
        }}
        aria-expanded={open}
        className="min-w-0 flex-1 cursor-pointer rounded-lg text-left"
      >
        <p className={clsx('text-sm leading-relaxed text-slate-100', !open && 'line-clamp-3')}>{m.text}</p>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-dim">
          {m.pinned && (
            <span className="flex items-center gap-1 text-slate-300">
              <Pin size={11} /> Pinned
            </span>
          )}
          <span>{m.source === 'user' ? 'From you' : 'From the agent'}</span>
          <span>·</span>
          <span className={s.className} title={s.title}>
            {s.word}
          </span>
          <span>·</span>
          <span title={m.last_used_at ? `Last used ${relTime(m.last_used_at)}` : 'Not used yet'}>
            used {m.uses} {m.uses === 1 ? 'time' : 'times'}
          </span>
          <span>·</span>
          <span>{relTime(m.created_at)}</span>
          {m.simulated && <SimTag />}
        </div>
        {open && m.tags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {m.tags.map((t) => (
              <span key={t} className="rounded-full bg-white/[0.05] px-2 py-[1px] text-[11px] text-mute">
                {t}
              </span>
            ))}
          </div>
        )}
      </div>
      <span className="flex shrink-0 items-center gap-0.5 opacity-60 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
        <button
          type="button"
          onClick={() => onPin(m)}
          title={m.pinned ? 'Unpin' : 'Pin: always keep this in mind'}
          aria-label={m.pinned ? 'Unpin' : 'Pin'}
          className="rounded-lg p-1.5 text-dim hover:bg-white/[0.07] hover:text-white"
        >
          {m.pinned ? <PinOff size={15} /> : <Pin size={15} />}
        </button>
        <button
          type="button"
          onClick={() => (confirm ? onDelete(m) : setConfirm(true))}
          title="Forget this"
          aria-label="Forget this"
          className={clsx(
            'flex items-center gap-1 rounded-lg p-1.5 text-xs font-medium',
            confirm ? 'bg-coral/[0.14] px-2 text-coral' : 'text-dim hover:bg-white/[0.07] hover:text-coral',
          )}
        >
          <Trash2 size={15} />
          {confirm && 'Forget?'}
        </button>
      </span>
    </li>
  )
}

/** How many rows of a kind show before "Show all". Trade history gets long quickly. */
const PREVIEW = 8

type Filter = 'all' | MemoryKind

export default function MemoryTab() {
  const toast = useStore((s) => s.toast)
  const memoryEvents = useStore((s) => s.memoryEvents)
  const connected = useStore((s) => s.connected)
  const [items, setItems] = useState<Memory[] | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const [hideSim, setHideSim] = useState(false)
  const [expanded, setExpanded] = useState<Partial<Record<MemoryKind, boolean>>>({})

  useEffect(() => {
    const t = window.setTimeout(() => setQuery(q.trim()), 250)
    return () => window.clearTimeout(t)
  }, [q])

  useEffect(() => {
    let alive = true
    api
      .memory('', query)
      .then((list) => alive && Array.isArray(list) && setItems(list))
      .catch(() => alive && setItems((cur) => cur ?? []))
    return () => {
      alive = false
    }
  }, [query, connected])

  // Fold in memories pushed live over the socket (skip while a search is active).
  useEffect(() => {
    if (query || memoryEvents.length === 0) return
    setItems((cur) => {
      if (!cur) return cur
      const byId = new Map(cur.map((m) => [m.id, m]))
      const fresh: Memory[] = []
      for (const m of memoryEvents) {
        if (byId.has(m.id)) byId.set(m.id, m)
        else fresh.push(m)
      }
      if (fresh.length === 0 && memoryEvents.every((m) => cur.find((c) => c.id === m.id) === m)) return cur
      return [...fresh, ...cur.map((m) => byId.get(m.id) ?? m)]
    })
  }, [memoryEvents, query])

  const visible = useMemo(() => (items ?? []).filter((m) => !hideSim || !m.simulated), [items, hideSim])

  const byKind = useMemo(() => {
    const out: Record<MemoryKind, Memory[]> = { guidance: [], lesson: [], episode: [] }
    for (const m of visible) (out[m.kind] ?? out.episode).push(m)
    for (const k of KINDS) out[k] = [...out[k]].sort((a, b) => Number(b.pinned) - Number(a.pinned))
    return out
  }, [visible])

  const hasSim = (items ?? []).some((m) => m.simulated)
  const shownKinds = KINDS.filter((k) => (filter === 'all' ? byKind[k].length > 0 : k === filter))
  const nothing = shownKinds.every((k) => byKind[k].length === 0)

  const onPin = async (m: Memory) => {
    const next = { ...m, pinned: !m.pinned }
    setItems((cur) => cur?.map((x) => (x.id === m.id ? next : x)) ?? cur)
    try {
      const saved = await api.patchMemory(m.id, { pinned: next.pinned })
      setItems((cur) => cur?.map((x) => (x.id === m.id ? saved : x)) ?? cur)
    } catch (e) {
      setItems((cur) => cur?.map((x) => (x.id === m.id ? m : x)) ?? cur)
      toast({ level: 'error', title: 'Could not update that memory', body: e instanceof ApiError ? e.message : '' })
    }
  }

  const onDelete = async (m: Memory) => {
    const before = items
    setItems((cur) => cur?.filter((x) => x.id !== m.id) ?? cur)
    try {
      await api.deleteMemory(m.id)
    } catch (e) {
      setItems(before)
      toast({ level: 'error', title: 'Could not forget that', body: e instanceof ApiError ? e.message : '' })
    }
  }

  const pills: { value: Filter; label: string; count: number }[] = [
    { value: 'all', label: 'All', count: visible.length },
    ...KINDS.map((k) => ({ value: k as Filter, label: kindMeta[k].title, count: byKind[k].length })),
  ]

  return (
    <div className="space-y-6">
      <Teach onAdded={(m) => setItems((cur) => [m, ...(cur ?? []).filter((x) => x.id !== m.id)])} />

      <div className="flex flex-wrap items-center gap-2">
        {pills.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setFilter(f.value)}
            className={clsx(
              'rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors',
              filter === f.value ? 'bg-white text-ink-950' : 'bg-ink-800 text-mute hover:text-white',
            )}
          >
            {f.label}
            <span className={clsx('num ml-1.5', filter === f.value ? 'text-ink-600' : 'text-dim')}>{f.count}</span>
          </button>
        ))}
        {hasSim && (
          <button
            type="button"
            onClick={() => setHideSim((v) => !v)}
            className={clsx(
              'rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors',
              hideSim ? 'bg-gold/[0.14] text-gold' : 'bg-ink-800 text-mute hover:text-white',
            )}
          >
            {hideSim ? 'Practice hidden' : 'Hide practice'}
          </button>
        )}
        <div className="relative ml-auto w-full sm:w-64">
          <Search size={14} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-dim" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search memory" aria-label="Search memory" className="field !rounded-full !py-2 !pl-9" />
        </div>
      </div>

      {items === null ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[60px] w-full !rounded-xl" />
          ))}
        </div>
      ) : nothing ? (
        <Card className="py-10">
          <Empty
            icon={query ? <Search size={18} /> : <Library size={18} />}
            title={query ? `Nothing matches “${query}”` : filter === 'lesson' ? 'No lessons yet' : 'Nothing remembered yet'}
            body={
              query
                ? 'Try a different word, or clear the search.'
                : filter === 'lesson'
                  ? 'After trades finish, the agent looks back at what happened and writes down what it would do differently.'
                  : 'Teach it something above, or let it trade. Your guidance, its lessons and a record of each trade collect here.'
            }
          />
        </Card>
      ) : (
        shownKinds.map((k) => {
          const list = byKind[k]
          const all = expanded[k] || list.length <= PREVIEW
          const rows = all ? list : list.slice(0, PREVIEW)
          return (
            <section key={k}>
              <h3 className="h-section">{kindMeta[k].title}</h3>
              <p className="hint mt-0.5">{kindMeta[k].blurb}</p>
              <ul className="mt-2">
                {rows.map((m) => (
                  <MemoryRow key={m.id} m={m} onPin={onPin} onDelete={onDelete} />
                ))}
              </ul>
              {!all && (
                <button
                  type="button"
                  onClick={() => setExpanded((e) => ({ ...e, [k]: true }))}
                  className="mt-2 text-[13px] font-medium text-mute hover:text-white"
                >
                  Show all {list.length}
                </button>
              )}
            </section>
          )
        })
      )}
    </div>
  )
}
