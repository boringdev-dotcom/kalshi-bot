import { AnimatePresence, motion } from 'framer-motion'
import { Radar } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import AgentPanel from '../components/AgentPanel'
import GameList from '../components/GameList'
import Ladder, { DEFAULT_VIEW, type MarketView, type TicketTarget } from '../components/Ladder'
import OrderTicket from '../components/OrderTicket'
import Scorebug from '../components/Scorebug'
import TotalChart from '../components/TotalChart'
import { Card, Empty, Skeleton } from '../components/ui'
import { cents, money, pct, pnlColor, tradeLabel } from '../format'
import { useStore } from '../store'
import type { GameDetail, LadderRung, Position } from '../types'

function useGameDetail(id: string | null) {
  const [detail, setDetail] = useState<GameDetail | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    if (!id) {
      setDetail(null)
      return
    }
    let alive = true
    setLoading(true)
    setDetail((d) => (d && d.game.id === id ? d : null))
    const load = () =>
      api
        .game(id)
        .then((d) => alive && d && Array.isArray(d.timeline) && setDetail(d))
        .catch(() => undefined)
        .finally(() => alive && setLoading(false))
    void load()
    const timer = window.setInterval(load, 3000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [id])
  return { detail, loading }
}

function HeldStrip({ positions }: { positions: Position[] }) {
  if (positions.length === 0) return null
  return (
    <Card className="flex flex-wrap items-center gap-x-5 gap-y-2 border-peri/20 bg-peri/[0.05] px-4 py-2.5">
      <span className="label !text-peri">Your positions here</span>
      {positions.map((p) => (
        <div key={p.id} className="flex items-center gap-2 text-[11.5px]">
          <span className="num font-semibold text-slate-100">{tradeLabel(p)}</span>
          <span className="num text-mute">
            {p.contracts} @ {cents(p.entry_price)} → {cents(p.mark_price)}
          </span>
          <span className={`num font-semibold ${pnlColor(p.pnl)}`}>{money(p.pnl, { sign: true })}</span>
          <span className="num text-dim">win {pct(p.p_win, 1)}</span>
        </div>
      ))}
    </Card>
  )
}

export default function Desk() {
  const games = useStore((s) => s.games)
  const loaded = useStore((s) => s.gamesLoaded)
  const selectedId = useStore((s) => s.selectedGameId)
  const selectGame = useStore((s) => s.selectGame)
  const positions = useStore((s) => s.positions)
  const [ticket, setTicket] = useState<TicketTarget | null>(null)
  // Which market each game's ladder is showing. A game you have not touched opens on its full-game total.
  const [views, setViews] = useState<Record<string, MarketView>>({})

  // Default to the first live game, else the first on the board.
  useEffect(() => {
    if (games.length === 0) return
    if (selectedId && games.some((g) => g.id === selectedId)) return
    const pick = games.find((g) => g.state === 'live') ?? games[0]
    selectGame(pick.id)
  }, [games, selectedId, selectGame])

  const game = useMemo(() => games.find((g) => g.id === selectedId) ?? null, [games, selectedId])
  const { detail, loading } = useGameDetail(game?.id ?? null)
  const gamePositions = useMemo(
    () => (game ? positions.filter((p) => p.game_id === game.id) : []),
    [positions, game],
  )

  useEffect(() => setTicket(null), [selectedId])

  const liveDetail = detail && game && detail.game.id === game.id ? detail : null
  const quarterMarkets = liveDetail ? (liveDetail.quarter_markets ?? []) : null
  const view = (game && views[game.id]) || DEFAULT_VIEW
  // Every rung of this game, so an open ticket keeps following its market's live price.
  const allRungs = useMemo<LadderRung[]>(
    () => [...(game?.ladder ?? []), ...(quarterMarkets ?? []).flatMap((m) => [...(m.totals ?? []), ...(m.spreads ?? [])])],
    [game?.ladder, quarterMarkets],
  )

  return (
    <div className="grid h-full grid-cols-1 gap-3 overflow-y-auto p-3 lg:grid-cols-[236px_minmax(0,1fr)_320px] lg:overflow-hidden xl:grid-cols-[280px_minmax(0,1fr)_380px]">
      <aside className="surface min-h-0 overflow-hidden lg:h-full">
        <div className="h-full max-h-[420px] overflow-y-auto lg:max-h-none">
          <GameList />
        </div>
      </aside>

      <section className="min-h-0 lg:h-full lg:overflow-y-auto lg:pr-1">
        <AnimatePresence mode="wait" initial={false}>
          {game ? (
            <motion.div
              key={game.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="space-y-3 pb-3"
            >
              <Scorebug game={game} />
              <HeldStrip positions={gamePositions} />
              <TotalChart
                game={game}
                timeline={liveDetail ? liveDetail.timeline : null}
                positions={gamePositions}
                loading={loading}
              />
              <Ladder
                game={game}
                quarterMarkets={quarterMarkets}
                positions={gamePositions}
                view={view}
                onViewChange={(v) => setViews((all) => ({ ...all, [game.id]: v }))}
                onPick={setTicket}
              />
            </motion.div>
          ) : !loaded ? (
            <motion.div key="skeleton" className="space-y-3" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <Skeleton className="h-[220px] w-full !rounded-xl2" />
              <Skeleton className="h-[300px] w-full !rounded-xl2" />
              <Skeleton className="h-[360px] w-full !rounded-xl2" />
            </motion.div>
          ) : (
            <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <Card className="py-16">
                <Empty
                  icon={<Radar size={18} />}
                  title="Nothing to watch yet"
                  body="Pick a game on the left once the slate loads. Switch the data source to Simulation in Settings to see the desk in action any time."
                />
              </Card>
            </motion.div>
          )}
        </AnimatePresence>
      </section>

      <aside className="min-h-[560px] lg:h-full lg:min-h-0">
        <AgentPanel gameId={game?.id ?? null} />
      </aside>

      {game && <OrderTicket game={game} rungs={allRungs} target={ticket} onClose={() => setTicket(null)} />}
    </div>
  )
}
