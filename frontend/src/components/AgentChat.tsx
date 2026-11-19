import { motion } from 'framer-motion'
import clsx from 'clsx'
import { ArrowUp, Check } from 'lucide-react'
import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, streamChat } from '../api'
import { useStore } from '../store'
import type { ChatMessage } from '../types'
import { Spinner } from './ui'

type Tool = { name: string; summary: string }

/* ───────────────────────── Text ───────────────────────── */

function inline(text: string, keyBase: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**') && p.length > 4)
      return (
        <strong key={`${keyBase}-${i}`} className="font-semibold text-white">
          {p.slice(2, -2)}
        </strong>
      )
    if (p.startsWith('`') && p.endsWith('`') && p.length > 2)
      return (
        <code key={`${keyBase}-${i}`} className="num rounded bg-white/[0.08] px-1 py-[1px] text-[13px] text-slate-100">
          {p.slice(1, -1)}
        </code>
      )
    return <Fragment key={`${keyBase}-${i}`}>{p}</Fragment>
  })
}

/** Small markdown subset: paragraphs, bullets, numbered lists, headings, bold, code. */
export function RichText({ text }: { text: string }) {
  const blocks: React.ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (!list) return
    const L = list
    const k = `l${blocks.length}`
    blocks.push(
      L.ordered ? (
        <ol key={k} className="ml-5 list-decimal space-y-1 marker:text-dim">
          {L.items.map((it, i) => (
            <li key={i}>{inline(it, `${k}-${i}`)}</li>
          ))}
        </ol>
      ) : (
        <ul key={k} className="ml-5 list-disc space-y-1 marker:text-dim">
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
        <div key={`h${i}`} className="pt-1 font-semibold text-white">
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

/** What the agent looked at while answering: one quiet line each. */
export function ToolLines({ tools, live }: { tools: Tool[]; live?: boolean }) {
  if (!tools.length) return null
  return (
    <div className="mb-1.5 space-y-0.5">
      {tools.map((t, i) => {
        const text = (t.summary || t.name.replace(/_/g, ' ')).trim()
        const working = live && i === tools.length - 1
        return (
          <div key={`${t.name}-${i}`} className="flex items-center gap-1.5 text-xs text-dim">
            {working ? <Spinner size={10} /> : <Check size={11} />}
            <span className="truncate">{text.charAt(0).toUpperCase() + text.slice(1)}</span>
          </div>
        )
      })}
    </div>
  )
}

export function AgentDot() {
  return <span className="mt-[7px] h-2.5 w-2.5 shrink-0 rounded-full bg-peri" aria-hidden />
}

function Message({ role, children }: { role: 'user' | 'assistant'; children: React.ReactNode }) {
  if (role === 'user')
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-3xl rounded-br-lg bg-ink-800 px-4 py-2.5 text-sm leading-relaxed text-white">
          {children}
        </div>
      </div>
    )
  return (
    <div className="flex gap-2.5">
      <AgentDot />
      <div className="min-w-0 flex-1 text-sm leading-relaxed text-slate-200">{children}</div>
    </div>
  )
}

const SUGGESTIONS = [
  'What are you watching right now?',
  'Why did you pass on the last game?',
  'Be more careful in close games',
  'What have you learned so far?',
]

/**
 * Talk to the agent. Fills its parent: give the parent a height (the transcript scrolls inside it).
 */
export default function AgentChat({ className }: { className?: string }) {
  const anthropic = useStore((s) => s.app?.health.anthropic)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loaded, setLoaded] = useState(false)
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [draft, setDraft] = useState('')
  const [draftTools, setDraftTools] = useState<Tool[]>([])
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
      const tools: Tool[] = []
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

  const offline = anthropic === false
  const empty = loaded && messages.length === 0 && !streaming

  return (
    <div className={clsx('flex h-full min-h-0 flex-col', className)}>
      <div className="flex items-center justify-between px-5 pb-2 pt-4">
        <h3 className="h-section">Ask the agent</h3>
        {messages.length > 0 && (
          <button type="button" onClick={clear} className="text-xs font-medium text-dim hover:text-white">
            Clear chat
          </button>
        )}
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-2">
        {offline && (
          <div className="mb-4 rounded-2xl bg-gold/[0.1] px-4 py-3 text-[13px] leading-relaxed text-gold">
            Chat needs Claude. Add an <span className="font-semibold">ANTHROPIC_API_KEY</span> to the server and restart it. Until
            then the agent still trades by your rules; it just cannot talk.
          </div>
        )}
        {empty ? (
          <div className="flex h-full flex-col justify-end pb-2">
            <div className="flex gap-2.5">
              <AgentDot />
              <p className="hint text-slate-300">
                Ask why it did something, or tell it how you want it to trade. Anything you teach it here is remembered.
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-4 pb-2">
            {messages.map((m) => (
              <Message key={m.id} role={m.role}>
                {m.role === 'assistant' ? (
                  <>
                    <ToolLines tools={m.tools ?? []} />
                    <RichText text={m.text} />
                  </>
                ) : (
                  m.text
                )}
              </Message>
            ))}
            {streaming && (
              <Message role="assistant">
                <ToolLines tools={draftTools} live={!draft} />
                {draft ? (
                  <RichText text={draft} />
                ) : (
                  <span className="flex items-center gap-1 py-1.5" aria-label="The agent is thinking">
                    {[0, 1, 2].map((i) => (
                      <motion.span
                        key={i}
                        className="h-1.5 w-1.5 rounded-full bg-mute"
                        animate={{ opacity: [0.25, 1, 0.25] }}
                        transition={{ duration: 1, repeat: Infinity, delay: i * 0.15 }}
                      />
                    ))}
                  </span>
                )}
              </Message>
            )}
            {error && <div className="rounded-2xl bg-coral/[0.12] px-4 py-2.5 text-[13px] text-coral">{error}</div>}
          </div>
        )}
      </div>

      <div className="px-4 pb-4 pt-2">
        {empty && !offline && (
          <div className="mb-2.5 flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => void send(s)}
                className="rounded-full bg-ink-800 px-3 py-1.5 text-[13px] text-slate-200 transition-colors hover:bg-ink-700 hover:text-white"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2 rounded-3xl bg-ink-800 py-1.5 pl-4 pr-1.5 transition-colors focus-within:bg-ink-700">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send(input)
              }
            }}
            rows={1}
            disabled={offline}
            placeholder={offline ? 'Connect Claude to chat' : 'Ask a question or tell it how to trade'}
            aria-label="Message the agent"
            className="block max-h-32 min-h-[36px] w-full resize-none bg-transparent py-2 text-sm text-white placeholder:text-dim focus:outline-none disabled:cursor-not-allowed"
          />
          <button
            type="button"
            onClick={() => void send(input)}
            disabled={!input.trim() || streaming || offline}
            aria-label="Send"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-ink-950 transition-all hover:bg-slate-200 active:scale-95 disabled:bg-white/[0.08] disabled:text-dim"
          >
            {streaming ? <Spinner size={13} /> : <ArrowUp size={16} strokeWidth={2.6} />}
          </button>
        </div>
      </div>
    </div>
  )
}
