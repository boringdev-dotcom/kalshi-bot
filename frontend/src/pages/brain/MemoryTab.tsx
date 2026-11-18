import { AnimatePresence, motion } from 'framer-motion'
import clsx from 'clsx'
import { Bot, GraduationCap, Library, Pin, PinOff, Search, Send, Sparkles, Trash2, User } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { Badge, Button, Card, Empty, Meter, Skeleton, SimTag, type Tone } from '../../components/ui'
import { pct, relTime } from '../../format'
import { useStore } from '../../store'
import type { Memory, MemoryKind } from '../../types'

const kindMeta: Record<MemoryKind, { label: string; tone: Tone; color: string; blurb: string }> = {
  guidance: { label: 'Guidance', tone: 'peri', color: '#8b9cff', blurb: 'Rules you gave it' },
  lesson: { label: 'Lesson', tone: 'mint', color: '#3ddc97', blurb: 'What it worked out from results' },
  episode: { label: 'Episode', tone: 'slate', color: '#8d96a8', blurb: 'Individual trades it remembers' },
}

const EXAMPLES = [
  'In the 4th quarter I buy the under 10–12 points above the live line.',
  'If it is a one-possession game with under two minutes left, get out — fouls and overtime kill unders.',
  'Never risk more than $300 to make $20.',
  'Skip games where both teams are in the bonus early in the 4th.',
]

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
          ? { level: 'success', title: 'Got it', body: 'Saved. Claude is working out what to change; watch the decision feed.' }
          : {
              level: 'warn',
              title: 'Saved, but not acted on yet',
              body: 'It is pinned in memory. Turning plain language into rule changes needs Claude: add ANTHROPIC_API_KEY, or set the playbook sliders yourself.',
            },
      )
    } catch (e) {
      toast({ level: 'error', title: 'Could not save that', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="relative overflow-hidden border-peri/25 p-5">
      <div
        className="pointer-events-none absolute -right-24 -top-28 h-64 w-64 rounded-full blur-3xl"
        style={{ background: 'radial-gradient(circle, rgba(139,156,255,0.20), transparent 70%)' }}
      />
      <div className="relative">
        <div className="flex items-center gap-2">
          <GraduationCap size={17} className="text-peri" />
          <h3 className="text-[15px] font-semibold text-slate-50">Teach the agent</h3>
        </div>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-mute">
          Say it the way you would tell another trader. It is stored as guidance, pinned to the top of the agent’s memory, and
          consulted before every entry and exit.
        </p>
        <div className="mt-3 rounded-xl border border-hair2 bg-ink-950/70 transition-colors focus-within:border-peri/60">
          <textarea
            ref={ref}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit()
            }}
            rows={3}
            placeholder="e.g. When the lead is under 4 with less than 3 minutes left, sell even at a small loss."
            className="block w-full resize-none bg-transparent px-3.5 py-3 text-[13px] leading-relaxed text-slate-100 placeholder:text-dim focus:outline-none"
          />
          <div className="flex items-center justify-between border-t border-hair px-3 py-2">
            <span className="text-[10.5px] text-dim">⌘/Ctrl + Enter to save</span>
            <Button variant="peri" size="sm" onClick={submit} loading={busy} disabled={!text.trim()}>
              <Send size={12} /> Teach
            </Button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => {
                setText(ex)
                ref.current?.focus()
              }}
              className="rounded-full border border-hair bg-white/[0.02] px-2.5 py-1 text-[11px] text-mute transition-colors hover:border-peri/40 hover:text-slate-100"
            >
              {ex.length > 58 ? `${ex.slice(0, 56)}…` : ex}
            </button>
          ))}
        </div>
      </div>
    </Card>
  )
}

function MemoryCard({
  m,
  onPin,
  onDelete,
}: {
  m: Memory
  onPin: (m: Memory) => void
  onDelete: (m: Memory) => void
}) {
  const meta = kindMeta[m.kind] ?? kindMeta.episode
  const [confirm, setConfirm] = useState(false)
  useEffect(() => {
    if (!confirm) return
    const t = window.setTimeout(() => setConfirm(false), 2600)
    return () => window.clearTimeout(t)
  }, [confirm])
  const total = m.support + m.against

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ type: 'spring', stiffness: 380, damping: 32 }}
      whileHover={{ y: -2 }}
      className={clsx(
        'group relative overflow-hidden rounded-xl border bg-ink-900/90 p-4',
        m.pinned ? 'border-peri/30' : 'border-hair hover:border-white/[0.12]',
      )}
    >
      <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: meta.color, opacity: m.pinned ? 1 : 0.55 }} />
      <div className="flex items-center gap-1.5">
        <Badge tone={meta.tone}>{meta.label}</Badge>
        {m.pinned && (
          <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-peri">
            <Pin size={10} /> Pinned
          </span>
        )}
        {m.simulated && <SimTag />}
        <span className="ml-auto flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          <button
            onClick={() => onPin(m)}
            title={m.pinned ? 'Unpin' : 'Pin — always consult this'}
            className="rounded-md p-1 text-dim hover:bg-white/[0.07] hover:text-peri"
          >
            {m.pinned ? <PinOff size={13} /> : <Pin size={13} />}
          </button>
          <button
            onClick={() => (confirm ? onDelete(m) : setConfirm(true))}
            title="Forget this"
            className={clsx(
              'flex items-center gap-1 rounded-md p-1 text-[10.5px] font-semibold',
              confirm ? 'bg-coral/15 px-1.5 text-coral' : 'text-dim hover:bg-white/[0.07] hover:text-coral',
            )}
          >
            <Trash2 size={13} />
            {confirm && 'Forget?'}
          </button>
        </span>
      </div>

      <p className="mt-2.5 text-[13px] leading-relaxed text-slate-100">{m.text}</p>

      {m.tags.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1">
          {m.tags.map((t) => (
            <span key={t} className="rounded bg-white/[0.05] px-1.5 py-[1px] text-[10px] text-mute">
              #{t}
            </span>
          ))}
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-3 border-t border-hair pt-3">
        <div title="How well outcomes have supported this memory">
          <div className="flex items-center justify-between text-[10px]">
            <span className="uppercase tracking-wider text-dim">Confidence</span>
            <span className="num text-slate-300">{pct(m.confidence)}</span>
          </div>
          <Meter
            value={m.confidence}
            tone={m.confidence >= 0.66 ? '#3ddc97' : m.confidence >= 0.4 ? '#f5b74e' : '#ff6b6b'}
            className="mt-1"
          />
        </div>
        <div title="How much weight the agent gives this memory">
          <div className="flex items-center justify-between text-[10px]">
            <span className="uppercase tracking-wider text-dim">Weight</span>
            <span className="num text-slate-300">{pct(m.importance)}</span>
          </div>
          <Meter value={m.importance} tone="#8b9cff" className="mt-1" />
        </div>
      </div>

      <div className="mt-2.5 flex items-center gap-3 text-[10.5px] text-dim">
        <span className="flex items-center gap-1" title={m.source === 'user' ? 'You told it this' : 'The agent worked this out'}>
          {m.source === 'user' ? <User size={11} /> : <Bot size={11} />}
          {m.source === 'user' ? 'You' : 'Agent'}
        </span>
        {total > 0 ? (
          <span className="num" title="Trades that confirmed vs contradicted this">
            <span className="text-mint">+{m.support}</span> / <span className="text-coral">−{m.against}</span>
          </span>
        ) : (
          <span>untested</span>
        )}
        <span className="num" title={m.last_used_at ? `Last used ${relTime(m.last_used_at)}` : 'Not used yet'}>
          used {m.uses}×
        </span>
        <span className="ml-auto">{relTime(m.created_at)}</span>
      </div>
    </motion.div>
  )
}

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

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: 0, guidance: 0, lesson: 0, episode: 0 }
    for (const m of items ?? []) {
      c.all += 1
      if (m.kind in c) c[m.kind] += 1
    }
    return c
  }, [items])

  const shown = useMemo(() => {
    const list = (items ?? [])
      .filter((m) => filter === 'all' || m.kind === filter)
      .filter((m) => !hideSim || !m.simulated)
    return [...list].sort((a, b) => Number(b.pinned) - Number(a.pinned))
  }, [items, filter, hideSim])

  const hasSim = (items ?? []).some((m) => m.simulated)

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

  const filters: { value: Filter; label: string; color: string }[] = [
    { value: 'all', label: 'Everything', color: '#e6e9f2' },
    { value: 'guidance', label: 'Guidance', color: kindMeta.guidance.color },
    { value: 'lesson', label: 'Lessons', color: kindMeta.lesson.color },
    { value: 'episode', label: 'Episodes', color: kindMeta.episode.color },
  ]

  return (
    <div className="space-y-4">
      <Teach onAdded={(m) => setItems((cur) => [m, ...(cur ?? []).filter((x) => x.id !== m.id)])} />

      <div className="flex flex-wrap items-center gap-2">
        {filters.map((f) => {
          const active = filter === f.value
          return (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={clsx(
                'relative flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                active ? 'border-white/20 bg-white/[0.07] text-slate-50' : 'border-hair text-mute hover:text-slate-200',
              )}
              title={f.value === 'all' ? undefined : kindMeta[f.value as MemoryKind].blurb}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: f.color }} />
              {f.label}
              <span className="num text-[10.5px] text-dim">{counts[f.value]}</span>
            </button>
          )
        })}
        {hasSim && (
          <button
            onClick={() => setHideSim((v) => !v)}
            className={clsx(
              'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
              hideSim ? 'border-gold/40 bg-gold/10 text-gold' : 'border-hair text-mute hover:text-slate-200',
            )}
          >
            Hide simulated
          </button>
        )}
        <div className="relative ml-auto w-full sm:w-64">
          <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-dim" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search memory…" className="field !pl-8 !py-1.5 !text-xs" />
        </div>
      </div>

      {items === null ? (
        <div className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[170px] w-full !rounded-xl" />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <Card className="py-10">
          <Empty
            icon={query ? <Search size={18} /> : filter === 'lesson' ? <Sparkles size={18} /> : <Library size={18} />}
            title={query ? `Nothing matches “${query}”` : filter === 'lesson' ? 'No lessons yet' : 'Memory is empty'}
            body={
              query
                ? 'Try a different word, or clear the search.'
                : filter === 'lesson'
                  ? 'After trades close, the agent reviews what happened and writes down what it would do differently.'
                  : 'Teach it something above, or let it trade — guidance, lessons and remembered trades collect here.'
            }
          />
        </Card>
      ) : (
        <div className="grid items-start gap-3 md:grid-cols-2 xl:grid-cols-3">
          <AnimatePresence initial={false}>
            {shown.map((m) => (
              <MemoryCard key={m.id} m={m} onPin={onPin} onDelete={onDelete} />
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}
