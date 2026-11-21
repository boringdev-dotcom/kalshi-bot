import { motion } from 'framer-motion'
import clsx from 'clsx'
import { ArrowUp, ChevronDown, RotateCw, Sparkles, Star } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, streamChat, type FavsResult } from '../../api'
import { pct } from '../../format'
import { useStore } from '../../store'
import type { Game } from '../../types'
import { AgentDot, RichText, ToolLines } from '../AgentChat'
import { Spinner } from '../ui'
import FavsView from './Favs'

type Tool = { name: string; summary: string }
type Turn = { id: number; role: 'user' | 'assistant'; text: string; tools: Tool[] }

// Each game's conversation survives moving between pages for this visit. It is also saved in Agent chat.
const threads = new Map<string, Turn[]>()
// Which games have the panel minimized, for this visit.
const minimized = new Set<string>()
// Each game's last favs and which answer was showing, for this visit.
const favsCache = new Map<string, FavsResult>()
type View = 'read' | 'favs'
const views = new Map<string, View>()
let nextId = 1

/**
 * "Agent analysis": the agent's read on this game, with everything on the page handed to it
 * (score, line, projections, what is happening on the floor, the box score, quarter lines,
 * your positions here, how trades have gone by pattern). Then a follow-up box to think it
 * through together.
 */
export default function GameAnalysis({
  game,
  blurb,
  noun = 'game',
  onPickFav,
}: {
  game: Pick<Game, 'id' | 'label' | 'state'>
  blurb?: string
  noun?: string
  /** Tapping a fav loads it in the page's order panel. */
  onPickFav?: (ticker: string, side: string) => void
}) {
  const anthropic = useStore((s) => s.app?.health.anthropic)
  const [turns, setTurns] = useState<Turn[]>(() => threads.get(game.id) ?? [])
  const [streaming, setStreaming] = useState(false)
  const [draft, setDraft] = useState('')
  const [draftTools, setDraftTools] = useState<Tool[]>([])
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(() => !minimized.has(game.id))
  const [view, setView] = useState<View>(() => views.get(game.id) ?? 'read')
  const [favs, setFavs] = useState<FavsResult | null>(() => favsCache.get(game.id) ?? null)
  const [favsBusy, setFavsBusy] = useState(false)
  const [favsError, setFavsError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const gameRef = useRef(game.id)
  gameRef.current = game.id

  useEffect(() => {
    setTurns(threads.get(game.id) ?? [])
    setOpen(!minimized.has(game.id))
    setView(views.get(game.id) ?? 'read')
    setFavs(favsCache.get(game.id) ?? null)
    setFavsError(null)
    setFavsBusy(false)
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

  // The agent only works when you ask: nothing here starts a read or a pick by itself.
  const offline = anthropic === false
  const hasRead = turns.length > 0 || streaming
  const hasFavs = !!favs || favsBusy
  const started = hasRead || hasFavs
  const toggle = (next: boolean) => {
    setOpen(next)
    if (next) minimized.delete(game.id)
    else minimized.add(game.id)
  }
  const show = (v: View) => {
    setView(v)
    views.set(game.id, v)
    toggle(true)
  }
  const analyse = () => {
    show('read')
    void ask(`Agent analysis: ${game.label}`, true)
  }
  const pickFavs = async () => {
    const id = game.id
    show('favs')
    setFavsBusy(true)
    setFavsError(null)
    try {
      const r = await api.favs(id)
      favsCache.set(id, r)
      if (gameRef.current === id) setFavs(r) // you may have moved to another game meanwhile
    } catch (e) {
      if (gameRef.current === id) setFavsError(e instanceof ApiError ? e.message : 'The agent could not pick right now.')
    } finally {
      if (gameRef.current === id) setFavsBusy(false)
    }
  }
  const send = () => {
    const t = input.trim()
    if (!t) return
    setInput('')
    void ask(t, false)
  }

  const lastReply = [...turns].reverse().find((t) => t.role === 'assistant')?.text ?? ''
  const current: View = view === 'favs' ? (hasFavs ? 'favs' : 'read') : hasRead ? 'read' : 'favs'
  const preview =
    current === 'favs'
      ? favsBusy
        ? 'Picking favs…'
        : favs
          ? favs.picks.length
            ? `${favs.picks.length} fav${favs.picks.length > 1 ? 's' : ''} · top: ${favs.picks[0].label} at ${pct(favs.picks[0].confidence)}`
            : 'No favs right now'
          : ''
      : streaming
        ? draft
          ? plain(draft)
          : 'Reading the game…'
        : plain(lastReply)
  const subtitle = offline
    ? 'Needs Claude: add an ANTHROPIC_API_KEY to the server.'
    : (blurb ?? `Its read on this ${noun}, or its favourite bets: 85–90% sure and still priced to pay.`)

  return (
    <section className="mt-6 overflow-hidden rounded-2xl border border-hair bg-ink-900">
      {/* header: who, and what it has to say; tap to fold once there is something to fold */}
      <div className={clsx('flex items-center gap-3 px-4 pt-4 sm:px-5', !open && 'pb-4')}>
        <AgentDot />
        <button
          onClick={() => started && toggle(!open)}
          className={clsx('min-w-0 flex-1 text-left', !started && 'cursor-default')}
          aria-expanded={started ? open : undefined}
          title={started ? (open ? 'Minimize' : 'Expand') : undefined}
        >
          <span className="flex items-center gap-1.5 text-[15px] font-semibold text-white">
            Agent
            {started && <ChevronDown size={15} className={clsx('text-mute transition-transform', open && 'rotate-180')} />}
          </span>
          <span className={clsx('mt-0.5 block text-[13px] leading-snug text-mute', !open && preview && 'truncate')}>
            {!open && preview ? (
              <>
                {(streaming || favsBusy) && <Spinner size={11} className="mr-1.5 inline-block align-[-1px]" />}
                {preview}
              </>
            ) : (
              subtitle
            )}
          </span>
        </button>
      </div>

      {open && (
        <>
          {/* the two things it can do, side by side */}
          <div className="grid grid-cols-2 gap-2 px-4 pb-4 pt-3.5 sm:px-5">
            <ActionButton onClick={analyse} disabled={streaming || offline} busy={streaming} primary={!hasRead} icon={hasRead ? <RotateCw size={14} /> : <Sparkles size={14} />}>
              {hasRead ? 'Fresh read' : `Analyse ${noun}`}
            </ActionButton>
            <ActionButton onClick={pickFavs} disabled={favsBusy || offline} busy={favsBusy} primary={!favs} icon={favs ? <RotateCw size={14} /> : <Star size={14} />}>
              {favsBusy ? 'Picking…' : favs ? 'Refresh favs' : 'Show favs'}
            </ActionButton>
          </div>

          {started && (
            <>
              {/* which answer is showing, once there is more than one */}
              {hasRead && hasFavs && (
                <div className="flex gap-5 border-t border-hair px-4 sm:px-5" role="tablist">
                  {(['read', 'favs'] as View[]).map((v) => (
                    <button
                      key={v}
                      role="tab"
                      aria-selected={current === v}
                      onClick={() => show(v)}
                      className={clsx(
                        'relative py-2.5 text-[13px] font-medium transition-colors',
                        current === v ? 'text-white' : 'text-mute hover:text-white',
                      )}
                    >
                      {v === 'read' ? 'Read' : `Favs${favs?.picks.length ? ` · ${favs.picks.length}` : ''}`}
                      {current === v && <span className="absolute inset-x-0 bottom-0 h-[2px] rounded-full bg-white" />}
                    </button>
                  ))}
                </div>
              )}

              <div className="border-t border-hair px-4 pb-4 pt-4 sm:px-5">
                {current === 'favs' ? (
                  <>
                    {favsError && <div className="mb-3 rounded-xl bg-coral/[0.12] px-4 py-2.5 text-[13px] text-coral">{favsError}</div>}
                    <FavsView result={favs} busy={favsBusy} onPick={onPickFav} />
                  </>
                ) : (
                  <div className="space-y-4">
                    {turns.map((t) =>
                      t.role === 'user' ? (
                        t.text.startsWith('Agent analysis:') ? null : (
                          <div key={t.id} className="flex justify-end">
                            <div className="max-w-[85%] whitespace-pre-wrap rounded-3xl rounded-br-lg bg-ink-800 px-4 py-2.5 text-sm leading-relaxed text-white">{t.text}</div>
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
                            Reading the {noun}…
                          </span>
                        )}
                      </div>
                    )}
                    {error && <div className="rounded-xl bg-coral/[0.12] px-4 py-2.5 text-[13px] text-coral">{error}</div>}

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
                        aria-label={`Ask the agent a follow-up about this ${noun}`}
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
                    <p className="text-[11px] text-dim">
                      Each question sends the latest numbers. Also saved in{' '}
                      <Link to="/agent" className="text-mute underline-offset-2 hover:text-white hover:underline">
                        Agent chat
                      </Link>
                      .
                    </p>
                  </div>
                )}
              </div>
            </>
          )}
        </>
      )}
    </section>
  )
}

function ActionButton({
  onClick,
  disabled,
  busy,
  primary,
  icon,
  children,
}: {
  onClick: () => void
  disabled: boolean
  busy: boolean
  primary: boolean
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'flex h-11 items-center justify-center gap-2 rounded-full px-3 text-sm font-semibold transition-colors disabled:cursor-not-allowed',
        primary ? 'bg-white text-ink-950 hover:bg-slate-200 disabled:bg-white/[0.08] disabled:text-dim' : 'bg-ink-800 text-slate-200 hover:bg-ink-700 disabled:text-dim',
      )}
    >
      {busy ? <Spinner size={13} /> : icon}
      <span className="truncate">{children}</span>
    </button>
  )
}

/** One line of the latest reply for the minimized panel: markdown stripped. */
function plain(text: string): string {
  return text.replace(/[*_`#>]+/g, '').replace(/\s+/g, ' ').trim()
}
