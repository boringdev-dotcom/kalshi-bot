import { AnimatePresence, motion } from 'framer-motion'
import clsx from 'clsx'
import {
  ArrowUp,
  ChevronDown,
  CircleSlash,
  Eye,
  LogIn,
  LogOut,
  Pause,
  Play,
  Sparkles,
  StickyNote,
  Trash2,
  Wrench,
} from 'lucide-react'
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError, streamChat } from '../api'
import { clockTime, pct, relTime } from '../format'
import { useStore } from '../store'
import type { ChatMessage, Decision, DecisionKind } from '../types'
import { agentTone } from './Layout'
import { Badge, Button, Chip, Empty, Meter, Segmented, Spinner, Tabs } from './ui'

/* ───────────────────────── Orb + header ───────────────────────── */

export function AgentOrb({ active, size = 40 }: { active: boolean; size?: number }) {
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      {active && <span className="absolute inset-0 animate-ping2 rounded-full bg-peri/25" />}
      <div
        className="absolute inset-0 overflow-hidden rounded-full border border-peri/40"
        style={{ background: 'radial-gradient(circle at 30% 25%, #c7d0ff 0%, #8b9cff 28%, #3b3f8f 62%, #14162b 100%)' }}
      >
        <div
          className={clsx('absolute -inset-2 opacity-70 mix-blend-screen', active && 'animate-drift')}
          style={{ background: 'radial-gradient(circle at 70% 75%, rgba(61,220,151,0.55), transparent 55%)' }}
        />
      </div>
    </div>
  )
}

function AgentHeader() {
  const app = useStore((s) => s.app)
  const setApp = useStore((s) => s.setApp)
  const toast = useStore((s) => s.toast)
  const [busy, setBusy] = useState(false)
  const agent = app?.agent
  const enabled = app?.settings.agent_enabled ?? false
  const tone = agent ? agentTone[agent.state] : agentTone.paused
  const active = agent?.state === 'watching' || agent?.state === 'acting'

  const toggle = async () => {
    setBusy(true)
    try {
      setApp(enabled ? await api.pauseAgent() : await api.startAgent())
    } catch (e) {
      toast({ level: 'error', title: 'Could not reach the agent', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative overflow-hidden border-b border-hair px-4 pb-3.5 pt-4">
      <div
        className="pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full opacity-60 blur-3xl"
        style={{ background: 'radial-gradient(circle, rgba(139,156,255,0.22), transparent 70%)' }}
      />
      <div className="relative flex items-center gap-3">
        <AgentOrb active={active} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-slate-50">Agent</span>
            <span
              className="rounded-md px-1.5 py-[1px] text-[10px] font-bold uppercase tracking-wider"
              style={{ color: tone.color, background: `${tone.color}1f` }}
            >
              {agent ? tone.label : '—'}
            </span>
          </div>
          <div className="num mt-0.5 text-[10.5px] text-dim">
            {agent ? `${agent.ticks.toLocaleString()} ticks · last ${relTime(agent.last_tick)}` : 'waiting for backend'}
          </div>
        </div>
        <Button variant={enabled ? 'outline' : 'peri'} size="sm" onClick={toggle} loading={busy} disabled={!app}>
          {enabled ? <Pause size={13} /> : <Play size={13} />}
          {enabled ? 'Pause' : 'Start'}
        </Button>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={agent?.focus ?? 'none'}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.18 }}
          className="relative mt-3 flex items-start gap-2 rounded-lg border border-peri/15 bg-peri/[0.06] px-2.5 py-2 text-[11.5px] leading-snug text-slate-300"
        >
          <Eye size={13} className="mt-[1px] shrink-0 text-peri" />
          <span>{agent?.focus || (enabled ? 'Scanning for setups…' : 'Paused. Press Start and the agent will watch live games for your setups.')}</span>
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

/* ───────────────────────── Decision feed ───────────────────────── */

const kindMeta: Record<DecisionKind, { color: string; label: string; icon: React.ReactNode }> = {
  enter: { color: '#3ddc97', label: 'Entered', icon: <LogIn size={13} /> },
  exit: { color: '#ff6b6b', label: 'Exited', icon: <LogOut size={13} /> },
  hold: { color: '#8b9cff', label: 'Holding', icon: <Eye size={13} /> },
  skip: { color: '#5d6577', label: 'Skipped', icon: <CircleSlash size={13} /> },
  note: { color: '#f5b74e', label: 'Note', icon: <StickyNote size={13} /> },
}

const sourceTone = { rules: 'slate', model: 'peri', claude: 'gold' } as const

function fmtChip(v: number | string) {
  if (typeof v === 'string') return v
  if (Number.isInteger(v)) return v.toString()
  return Math.abs(v) < 1 ? v.toFixed(3).replace(/0+$/, '').replace(/\.$/, '') : v.toFixed(1)
}

function DecisionItem({ d }: { d: Decision }) {
  const [open, setOpen] = useState(false)
  const meta = kindMeta[d.kind] ?? kindMeta.note
  const chips = Object.entries(d.data ?? {})
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: -14, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ type: 'spring', stiffness: 420, damping: 34 }}
      className="group relative overflow-hidden rounded-xl border border-hair bg-ink-800/70 transition-colors hover:border-white/[0.11]"
    >
      <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: meta.color }} />
      <button className="w-full px-3 py-2.5 pl-4 text-left" onClick={() => setOpen((o) => !o)}>
        <div className="flex items-center gap-1.5 text-[10.5px]">
          <span className="flex items-center gap-1 font-semibold uppercase tracking-wider" style={{ color: meta.color }}>
            {meta.icon}
            {meta.label}
          </span>
          {d.game_label && <span className="text-mute">· {d.game_label}</span>}
          <span className="num ml-auto text-dim" title={d.ts}>
            {clockTime(d.ts)}
          </span>
        </div>
        <div className="mt-1 text-[12.5px] font-semibold leading-snug text-slate-100">{d.headline}</div>
        <motion.div layout="position" className={clsx('mt-1 text-[11.5px] leading-relaxed text-mute', !open && 'line-clamp-2')}>
          {d.reasoning}
        </motion.div>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              {chips.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {chips.map(([k, v]) => (
                    <Chip key={k} k={k.replace(/_/g, ' ')} v={fmtChip(v)} />
                  ))}
                </div>
              )}
              {d.ticker && <div className="num mt-2 text-[10px] text-dim">{d.ticker}</div>}
              {d.memory_ids?.length > 0 && (
                <div className="mt-1 text-[10.5px] text-peri">
                  Drew on {d.memory_ids.length} {d.memory_ids.length === 1 ? 'memory' : 'memories'}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
        <div className="mt-2 flex items-center gap-2">
          <Badge tone={sourceTone[d.source] ?? 'slate'}>{d.source}</Badge>
          <div className="flex flex-1 items-center gap-1.5" title={`Confidence ${pct(d.confidence)}`}>
            <Meter value={d.confidence} tone={meta.color} height={3} className="max-w-[70px]" />
            <span className="num text-[10px] text-dim">{pct(d.confidence)}</span>
          </div>
          {!open && chips.length > 0 && (
            <span className="num text-[10px] text-dim">{chips.length} data points</span>
          )}
          <ChevronDown size={13} className={clsx('text-dim transition-transform', open && 'rotate-180')} />
        </div>
      </button>
    </motion.li>
  )
}

function DecisionFeed({ gameId }: { gameId: string | null }) {
  const decisions = useStore((s) => s.decisions)
  const [scope, setScope] = useState<'all' | 'game'>('all')
  const [hideSkips, setHideSkips] = useState(false)
  const list = useMemo(
    () =>
      decisions
        .filter((d) => (scope === 'game' && gameId ? d.game_id === gameId : true))
        .filter((d) => (hideSkips ? d.kind !== 'skip' && d.kind !== 'hold' : true))
        .slice(0, 60),
    [decisions, scope, gameId, hideSkips],
  )
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <Segmented
          id="feed-scope"
          value={scope}
          onChange={setScope}
          options={[
            { value: 'all', label: 'All games' },
            { value: 'game', label: 'This game' },
          ]}
        />
        <button
          onClick={() => setHideSkips((v) => !v)}
          className={clsx(
            'rounded-md px-2 py-1 text-[11px] font-medium transition-colors',
            hideSkips ? 'bg-peri/15 text-peri' : 'text-dim hover:text-slate-300',
          )}
        >
          Actions only
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {list.length === 0 ? (
          <Empty
            icon={<Sparkles size={18} />}
            title="No decisions yet"
            body="Every time the agent enters, skips, holds or exits, it explains itself here with the numbers behind the call."
          />
        ) : (
          <ul className="space-y-2">
            <AnimatePresence initial={false}>
              {list.map((d) => (
                <DecisionItem key={d.id} d={d} />
              ))}
            </AnimatePresence>
          </ul>
        )}
      </div>
    </div>
  )
}

/* ───────────────────────── Chat ───────────────────────── */

function inline(text: string, keyBase: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**') && p.length > 4)
      return (
        <strong key={`${keyBase}-${i}`} className="font-semibold text-slate-50">
          {p.slice(2, -2)}
        </strong>
      )
    if (p.startsWith('`') && p.endsWith('`') && p.length > 2)
      return (
        <code key={`${keyBase}-${i}`} className="num rounded bg-white/[0.07] px-1 py-[1px] text-[11px] text-peri">
          {p.slice(1, -1)}
        </code>
      )
    return <Fragment key={`${keyBase}-${i}`}>{p}</Fragment>
  })
}

/** Small markdown subset: paragraphs, bullets, numbered lists, headings, bold, code. */
function RichText({ text }: { text: string }) {
  const blocks: React.ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (!list) return
    const L = list
    const k = `l${blocks.length}`
    blocks.push(
      L.ordered ? (
        <ol key={k} className="ml-4 list-decimal space-y-1 marker:text-dim">
          {L.items.map((it, i) => (
            <li key={i}>{inline(it, `${k}-${i}`)}</li>
          ))}
        </ol>
      ) : (
        <ul key={k} className="ml-4 list-disc space-y-1 marker:text-peri/70">
          {L.items.map((it, i) => (
            <li key={i}>{inline(it, `${k}-${i}`)}</li>
          ))}
        </ul>
      ),
    )
    list = null
  }
  text.split('\n').forEach((raw, i) => {
    const line = raw.trimEnd()
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/)
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    const heading = line.match(/^#{1,4}\s+(.*)$/)
    if (bullet || numbered) {
      const ordered = !!numbered
      if (!list || list.ordered !== ordered) {
        flush()
        list = { ordered, items: [] }
      }
      list.items.push((bullet ?? numbered)![1])
      return
    }
    flush()
    if (!line.trim()) return
    if (heading) {
      blocks.push(
        <div key={`h${i}`} className="pt-1 text-[12px] font-semibold text-slate-50">
          {inline(heading[1], `h${i}`)}
        </div>,
      )
      return
    }
    blocks.push(<p key={`p${i}`}>{inline(line, `p${i}`)}</p>)
  })
  flush()
  return <div className="space-y-2">{blocks}</div>
}

function ToolChips({ tools, live }: { tools: { name: string; summary: string }[]; live?: boolean }) {
  if (!tools.length) return null
  return (
    <div className="mb-2 flex flex-wrap gap-1">
      {tools.map((t, i) => (
        <motion.span
          key={`${t.name}-${i}`}
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          title={t.summary}
          className="inline-flex max-w-full items-center gap-1 rounded-md border border-peri/20 bg-peri/[0.08] px-1.5 py-[2px] text-[10.5px] text-peri"
        >
          {live && i === tools.length - 1 ? <Spinner size={9} /> : <Wrench size={9} />}
          <span className="font-medium">{t.name.replace(/_/g, ' ')}</span>
          {t.summary && <span className="truncate text-peri/60">· {t.summary}</span>}
        </motion.span>
      ))}
    </div>
  )
}

function Bubble({ role, children }: { role: 'user' | 'assistant'; children: React.ReactNode }) {
  return (
    <motion.div
      layout="position"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={clsx('flex', role === 'user' ? 'justify-end' : 'justify-start')}
    >
      <div
        className={clsx(
          'max-w-[92%] rounded-2xl px-3 py-2 text-[12.5px] leading-relaxed',
          role === 'user'
            ? 'rounded-br-md bg-peri/20 text-slate-50'
            : 'rounded-bl-md border border-hair bg-ink-800/80 text-slate-300',
        )}
      >
        {children}
      </div>
    </motion.div>
  )
}

const SUGGESTIONS = [
  'Why did you skip the last game?',
  'Be more careful in one-possession games',
  'What have you learned this week?',
  'Walk me through your open positions',
]

function Chat() {
  const anthropic = useStore((s) => s.app?.health.anthropic)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loaded, setLoaded] = useState(false)
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [draft, setDraft] = useState('')
  const [draftTools, setDraftTools] = useState<{ name: string; summary: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const localId = useRef(-1)

  useEffect(() => {
    let alive = true
    api
      .chatHistory()
      .then((h) => alive && Array.isArray(h) && setMessages(h))
      .catch(() => undefined)
      .finally(() => alive && setLoaded(true))
    return () => {
      alive = false
      abortRef.current?.abort()
    }
  }, [])

  // Pin the transcript to the bottom without scrolling the page around it.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, draft, draftTools, streaming])

  const send = useCallback(
    async (text: string) => {
      const msg = text.trim()
      if (!msg || streaming) return
      setInput('')
      setError(null)
      setMessages((m) => [
        ...m,
        { id: localId.current--, role: 'user', text: msg, ts: new Date().toISOString(), tools: [] },
      ])
      setStreaming(true)
      setDraft('')
      setDraftTools([])
      let acc = ''
      const tools: { name: string; summary: string }[] = []
      let finished = false
      const ctl = new AbortController()
      abortRef.current = ctl
      try {
        await streamChat(
          msg,
          (ev) => {
            if (ev.type === 'text') {
              acc += ev.delta
              setDraft(acc)
            } else if (ev.type === 'tool') {
              tools.push({ name: ev.name, summary: ev.summary })
              setDraftTools([...tools])
            } else if (ev.type === 'done') {
              finished = true
              setMessages((m) => [...m, ev.message])
            } else if (ev.type === 'error') {
              setError(ev.message)
            }
          },
          ctl.signal,
        )
        if (!finished && acc) {
          setMessages((m) => [
            ...m,
            { id: localId.current--, role: 'assistant', text: acc, ts: new Date().toISOString(), tools },
          ])
        }
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'The agent could not answer right now.')
      } finally {
        setStreaming(false)
        setDraft('')
        setDraftTools([])
      }
    },
    [streaming],
  )

  const clear = async () => {
    try {
      await api.clearChat()
      setMessages([])
    } catch {
      /* keep the transcript if the backend is away */
    }
  }

  const empty = loaded && messages.length === 0 && !streaming

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {anthropic === false && (
          <div className="mb-3 rounded-lg border border-gold/25 bg-gold/[0.08] px-3 py-2 text-[11.5px] leading-snug text-gold">
            No Anthropic API key found. Add <code className="num">ANTHROPIC_API_KEY</code> to your <code className="num">.env</code> and
            restart the backend to talk to the agent.
          </div>
        )}
        {empty ? (
          <div className="flex h-full flex-col items-center justify-center px-2 text-center">
            <AgentOrb active size={48} />
            <div className="mt-3 text-sm font-semibold text-slate-100">Talk to your agent</div>
            <p className="mt-1 max-w-[260px] text-[11.5px] leading-relaxed text-dim">
              Ask why it did something, or tell it how you want it to trade. Guidance you give here is remembered.
            </p>
            <div className="mt-4 flex flex-col gap-1.5 self-stretch">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-lg border border-hair bg-white/[0.02] px-3 py-2 text-left text-[11.5px] text-slate-300 transition-colors hover:border-peri/40 hover:bg-peri/[0.07] hover:text-slate-100"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-2.5">
            {messages.map((m) => (
              <Bubble key={m.id} role={m.role}>
                {m.role === 'assistant' ? (
                  <>
                    <ToolChips tools={m.tools ?? []} />
                    <RichText text={m.text} />
                  </>
                ) : (
                  <span className="whitespace-pre-wrap">{m.text}</span>
                )}
              </Bubble>
            ))}
            {streaming && (
              <Bubble role="assistant">
                <ToolChips tools={draftTools} live={!draft} />
                {draft ? (
                  <RichText text={draft} />
                ) : (
                  <span className="flex items-center gap-1 py-1">
                    {[0, 1, 2].map((i) => (
                      <motion.span
                        key={i}
                        className="h-1.5 w-1.5 rounded-full bg-peri"
                        animate={{ opacity: [0.25, 1, 0.25], y: [0, -2, 0] }}
                        transition={{ duration: 1, repeat: Infinity, delay: i * 0.15 }}
                      />
                    ))}
                  </span>
                )}
              </Bubble>
            )}
            {error && (
              <div className="rounded-lg border border-coral/25 bg-coral/10 px-3 py-2 text-[11.5px] text-coral">{error}</div>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-hair p-3">
        <div className="relative rounded-xl border border-hair2 bg-ink-950/70 transition-colors focus-within:border-peri/60">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send(input)
              }
            }}
            rows={2}
            placeholder="Ask a question or give it guidance…"
            className="block w-full resize-none bg-transparent px-3 py-2.5 pr-11 text-[12.5px] text-slate-100 placeholder:text-dim focus:outline-none"
          />
          <button
            onClick={() => void send(input)}
            disabled={!input.trim() || streaming}
            aria-label="Send"
            className="absolute bottom-2 right-2 flex h-7 w-7 items-center justify-center rounded-lg bg-peri text-ink-950 transition-all hover:brightness-110 active:scale-95 disabled:bg-white/[0.08] disabled:text-dim"
          >
            {streaming ? <Spinner size={12} /> : <ArrowUp size={14} strokeWidth={2.6} />}
          </button>
        </div>
        <div className="mt-1.5 flex items-center justify-between text-[10px] text-dim">
          <span>Enter to send · Shift+Enter for a new line</span>
          {messages.length > 0 && (
            <button onClick={clear} className="flex items-center gap-1 hover:text-slate-300">
              <Trash2 size={10} /> Clear
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/* ───────────────────────── Panel ───────────────────────── */

export default function AgentPanel({ gameId }: { gameId: string | null }) {
  const [tab, setTab] = useState<'feed' | 'chat'>('feed')
  const count = useStore((s) => s.decisions.length)
  return (
    <div className="surface flex h-full min-h-0 flex-col overflow-hidden">
      <AgentHeader />
      <Tabs
        id="agent"
        value={tab}
        onChange={setTab}
        className="px-2"
        tabs={[
          { value: 'feed', label: 'Decisions', count },
          { value: 'chat', label: 'Chat' },
        ]}
      />
      {/* Keep chat mounted so an in-flight answer survives a tab switch. */}
      <div className={clsx('min-h-0 flex-1 flex-col', tab === 'feed' ? 'flex' : 'hidden')}>
        <DecisionFeed gameId={gameId} />
      </div>
      <div className={clsx('min-h-0 flex-1 flex-col', tab === 'chat' ? 'flex' : 'hidden')}>
        <Chat />
      </div>
    </div>
  )
}
