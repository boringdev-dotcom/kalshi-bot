import { motion } from 'framer-motion'
import clsx from 'clsx'
import { ArrowUp, ChevronDown, RotateCw } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, streamChat } from '../../api'
import { useStore } from '../../store'
import type { Game } from '../../types'
import { AgentDot, RichText, ToolLines } from '../AgentChat'
import { Spinner } from '../ui'

type Tool = { name: string; summary: string }
type Turn = { id: number; role: 'user' | 'assistant'; text: string; tools: Tool[] }

// Each game's conversation survives moving between pages for this visit. It is also saved in Agent chat.
const threads = new Map<string, Turn[]>()
// Which games have the panel minimized, for this visit.
const minimized = new Set<string>()
let nextId = 1

/**
 * "Agent analysis": the agent's read on this game, with everything on the page handed to it
 * (score, line, projections, what is happening on the floor, the box score, quarter lines,
 * your positions here, how trades have gone by pattern). Then a follow-up box to think it
 * through together.
 */
export default function GameAnalysis({ game }: { game: Game }) {
  const anthropic = useStore((s) => s.app?.health.anthropic)
  const [turns, setTurns] = useState<Turn[]>(() => threads.get(game.id) ?? [])
  const [streaming, setStreaming] = useState(false)
  const [draft, setDraft] = useState('')
  const [draftTools, setDraftTools] = useState<Tool[]>([])
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(() => !minimized.has(game.id))
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    setTurns(threads.get(game.id) ?? [])
    setOpen(!minimized.has(game.id))
    setError(null)
    return () => abortRef.current?.abort()
  }, [game.id])

  const push = useCallback(
    (t: Turn) =>
      setTurns((prev) => {
        const next = [...prev, t]
        threads.set(game.id, next)
        return next
      }),
    [game.id],
  )

  const ask = useCallback(
    async (text: string, analysis: boolean) => {
      if (streaming) return
      setError(null)
      push({ id: nextId++, role: 'user', text, tools: [] })
      setStreaming(true)
      setDraft('')
      setDraftTools([])
      let acc = ''
      const tools: Tool[] = []
      let done = false
      const ctl = new AbortController()
      abortRef.current = ctl
      try {
        await streamChat(
          text,
          (ev) => {
            if (ev.type === 'text') {
              acc += ev.delta
              setDraft(acc)
            } else if (ev.type === 'tool') {
              tools.push({ name: ev.name, summary: ev.summary })
              setDraftTools([...tools])
            } else if (ev.type === 'done') {
              done = true
              push({ id: nextId++, role: 'assistant', text: ev.message.text, tools })
            } else if (ev.type === 'error') {
              setError(ev.message)
            }
          },
          ctl.signal,
          { gameId: game.id, analysis },
        )
        if (!done && acc) push({ id: nextId++, role: 'assistant', text: acc, tools })
      } catch (e) {
        setError(e instanceof ApiError ? e.message : 'The agent could not answer right now.')
      } finally {
        setStreaming(false)
        setDraft('')
        setDraftTools([])
      }
    },
    [streaming, push, game.id],
  )

  const offline = anthropic === false
  const started = turns.length > 0 || streaming
  const analyse = () => {
    toggle(true)
    void ask(`Agent analysis: ${game.label}`, true)
  }
  const toggle = (next: boolean) => {
    setOpen(next)
    if (next) minimized.delete(game.id)
    else minimized.add(game.id)
  }
  const lastReply = [...turns].reverse().find((t) => t.role === 'assistant')?.text ?? ''
  const preview = streaming ? (draft ? plain(draft) : 'Reading the game…') : plain(lastReply)
  const collapsed = started && !open
  const send = () => {
    const t = input.trim()
    if (!t) return
    setInput('')
    void ask(t, false)
  }

  return (
    <section className="mt-6 rounded-2xl bg-ink-900 p-4 ring-1 ring-hair sm:p-5">
      <div className="flex items-start gap-3">
        <AgentDot />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <div className="min-w-0 flex-1">
              {started ? (
                <button
                  onClick={() => toggle(!open)}
                  className="flex w-full min-w-0 items-center gap-1.5 text-left"
                  aria-expanded={open}
                  title={open ? 'Minimize' : 'Expand'}
                >
                  <span className="text-sm font-semibold text-white">Agent analysis</span>
                  <ChevronDown size={15} className={clsx('shrink-0 text-mute transition-transform', open && 'rotate-180')} />
                </button>
              ) : (
                <div className="text-sm font-semibold text-white">Agent analysis</div>
              )}
              {collapsed && preview && (
                <button onClick={() => toggle(true)} className="mt-0.5 block w-full truncate text-left text-[13px] text-mute hover:text-slate-300">
                  {streaming && <Spinner size={11} className="mr-1.5 inline-block align-[-1px]" />}
                  {preview}
                </button>
              )}
              {!started && (
                <p className="mt-0.5 text-[13px] leading-snug text-mute">
                  {offline
                    ? 'Needs Claude: add an ANTHROPIC_API_KEY to the server.'
                    : 'Its read on this game: the line, the floor, your positions, and what to watch. Then talk it through.'}
                </p>
              )}
            </div>
            {!started ? (
              <button
                onClick={analyse}
                disabled={offline}
                className="min-h-[40px] shrink-0 rounded-full bg-white px-4 text-sm font-semibold text-ink-950 transition-colors hover:bg-slate-200 disabled:bg-white/[0.08] disabled:text-dim"
              >
                Analyse this game
              </button>
            ) : open ? (
              <button
                onClick={analyse}
                disabled={streaming || offline}
                className="flex min-h-[36px] shrink-0 items-center gap-1.5 text-[13px] font-medium text-mute hover:text-white disabled:opacity-40"
                title="Ask again with the latest numbers"
              >
                <RotateCw size={13} /> Fresh read
              </button>
            ) : null}
          </div>

          {started && open && (
            <div className="mt-4 space-y-4">
              {turns.map((t) =>
                t.role === 'user' ? (
                  t.text.startsWith('Agent analysis:') ? null : (
                    <div key={t.id} className="flex justify-end">
                      <div className="max-w-[85%] whitespace-pre-wrap rounded-3xl rounded-br-lg bg-ink-800 px-4 py-2.5 text-sm leading-relaxed text-white">
                        {t.text}
                      </div>
                    </div>
                  )
                ) : (
                  <div key={t.id} className="text-sm leading-relaxed text-slate-200">
                    <ToolLines tools={t.tools} />
                    <RichText text={t.text} />
                  </div>
                ),
              )}
              {streaming && (
                <div className="text-sm leading-relaxed text-slate-200">
                  <ToolLines tools={draftTools} live={!draft} />
                  {draft ? (
                    <RichText text={draft} />
                  ) : (
                    <span className="flex items-center gap-2 py-1 text-[13px] text-mute" aria-label="The agent is thinking">
                      <span className="flex gap-1">
                        {[0, 1, 2].map((i) => (
                          <motion.span
                            key={i}
                            className="h-1.5 w-1.5 rounded-full bg-mute"
                            animate={{ opacity: [0.25, 1, 0.25] }}
                            transition={{ duration: 1, repeat: Infinity, delay: i * 0.15 }}
                          />
                        ))}
                      </span>
                      Reading the game…
                    </span>
                  )}
                </div>
              )}
              {error && <div className="rounded-2xl bg-coral/[0.12] px-4 py-2.5 text-[13px] text-coral">{error}</div>}

              <div className="flex items-end gap-2 rounded-3xl bg-ink-800 py-1.5 pl-4 pr-1.5 transition-colors focus-within:bg-ink-700">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      send()
                    }
                  }}
                  rows={1}
                  disabled={offline}
                  placeholder="Ask a follow-up"
                  aria-label="Ask the agent a follow-up about this game"
                  className="block max-h-32 min-h-[36px] w-full resize-none bg-transparent py-2 text-base text-white placeholder:text-dim focus:outline-none sm:text-sm"
                />
                <button
                  type="button"
                  onClick={send}
                  disabled={!input.trim() || streaming || offline}
                  aria-label="Send"
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-ink-950 transition-all hover:bg-slate-200 active:scale-95 disabled:bg-white/[0.08] disabled:text-dim"
                >
                  {streaming ? <Spinner size={13} /> : <ArrowUp size={16} strokeWidth={2.6} />}
                </button>
              </div>
              <p className="text-xs text-dim">
                Each question sends the agent the latest numbers for this game. The conversation is also saved in{' '}
                <Link to="/agent" className="text-mute underline-offset-2 hover:text-white hover:underline">
                  Agent chat
                </Link>
                .
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

/** One line of the latest reply for the minimized panel: markdown stripped. */
function plain(text: string): string {
  return text.replace(/[*_`#>]+/g, '').replace(/\s+/g, ' ').trim()
}
