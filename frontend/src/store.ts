import { create } from 'zustand'
import { api } from './api'
import type { Account, AppState, Decision, Game, Memory, Position, Trade, WsEvent } from './types'

const CAP = 200

export interface Toast {
  id: number
  level: 'info' | 'success' | 'warn' | 'error'
  title: string
  body: string
}

interface Store {
  /** WebSocket link. */
  connected: boolean
  /** null = not known yet, false = REST calls failing. */
  backendUp: boolean | null
  app: AppState | null
  games: Game[]
  gamesLoaded: boolean
  positions: Position[]
  trades: Trade[]
  decisions: Decision[]
  /** Memories pushed over the socket since load (newest first); pages merge these by id. */
  memoryEvents: Memory[]
  /** Bumps whenever a trade closes, so pages can refetch derived data. */
  tradeTick: number
  selectedGameId: string | null
  toasts: Toast[]

  hydrate: () => Promise<void>
  setApp: (app: AppState) => void
  selectGame: (id: string) => void
  toast: (t: Omit<Toast, 'id'>) => void
  dismissToast: (id: number) => void
  upsertPosition: (p: Position) => void
  /** Record a closed trade and drop the position it came from. */
  addTrade: (t: Trade, closedPositionId?: number) => void
}

let toastSeq = 1

function prependUnique<T extends { id: number }>(list: T[], item: T): T[] {
  return [item, ...list.filter((x) => x.id !== item.id)].slice(0, CAP)
}

export const useStore = create<Store>((set, get) => ({
  connected: false,
  backendUp: null,
  app: null,
  games: [],
  gamesLoaded: false,
  positions: [],
  trades: [],
  decisions: [],
  memoryEvents: [],
  tradeTick: 0,
  selectedGameId: null,
  toasts: [],

  hydrate: async () => {
    const [app, games, positions, trades, decisions] = await Promise.allSettled([
      api.state(),
      api.games(),
      api.positions(),
      api.trades(100),
      api.decisions(100),
    ])
    const patch: Partial<Store> = { backendUp: app.status === 'fulfilled' }
    if (app.status === 'fulfilled') patch.app = app.value
    if (games.status === 'fulfilled' && Array.isArray(games.value)) {
      patch.games = games.value
      patch.gamesLoaded = true
    }
    if (positions.status === 'fulfilled' && Array.isArray(positions.value)) patch.positions = positions.value
    if (trades.status === 'fulfilled' && Array.isArray(trades.value)) patch.trades = trades.value.slice(0, CAP)
    if (decisions.status === 'fulfilled' && Array.isArray(decisions.value))
      patch.decisions = decisions.value.slice(0, CAP)
    set(patch)
  },

  setApp: (app) => set({ app, backendUp: true }),
  selectGame: (id) => set({ selectedGameId: id }),

  toast: (t) => {
    const id = toastSeq++
    set((s) => ({ toasts: [...s.toasts, { ...t, id }].slice(-5) }))
    window.setTimeout(() => get().dismissToast(id), t.level === 'error' ? 8000 : 5200)
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),

  upsertPosition: (p) =>
    set((s) => ({
      positions: s.positions.some((x) => x.id === p.id)
        ? s.positions.map((x) => (x.id === p.id ? p : x))
        : [p, ...s.positions],
    })),
  addTrade: (t, closedPositionId) =>
    set((s) => ({
      trades: prependUnique(s.trades, t),
      positions: closedPositionId == null ? s.positions : s.positions.filter((p) => p.id !== closedPositionId),
      tradeTick: s.tradeTick + 1,
    })),
}))

function handle(ev: WsEvent) {
  const s = useStore.getState()
  switch (ev.type) {
    case 'state':
      useStore.setState({ app: ev.data, backendUp: true })
      break
    case 'games':
      if (Array.isArray(ev.data)) useStore.setState({ games: ev.data, gamesLoaded: true })
      break
    case 'positions':
      if (Array.isArray(ev.data)) useStore.setState({ positions: ev.data })
      break
    case 'account':
      if (s.app) useStore.setState({ app: { ...s.app, account: ev.data as Account } })
      break
    case 'decision':
      useStore.setState({ decisions: prependUnique(s.decisions, ev.data) })
      break
    case 'trade':
      useStore.setState({ trades: prependUnique(s.trades, ev.data), tradeTick: s.tradeTick + 1 })
      break
    case 'memory':
      useStore.setState({ memoryEvents: prependUnique(s.memoryEvents, ev.data) })
      break
    case 'toast':
      if (ev.data) s.toast(ev.data)
      break
  }
}

let started = false
let retry = 0
let socket: WebSocket | null = null

function connect() {
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`
  try {
    socket = new WebSocket(url)
  } catch {
    scheduleReconnect()
    return
  }
  socket.onopen = () => {
    retry = 0
    useStore.setState({ connected: true })
    void useStore.getState().hydrate()
  }
  socket.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data as string) as WsEvent
      if (msg && typeof msg.type === 'string') handle(msg)
    } catch {
      /* ignore malformed frames */
    }
  }
  socket.onclose = () => {
    useStore.setState({ connected: false })
    scheduleReconnect()
  }
  socket.onerror = () => {
    try {
      socket?.close()
    } catch {
      /* noop */
    }
  }
}

function scheduleReconnect() {
  const delay = Math.min(1000 * 2 ** retry, 8000)
  retry += 1
  window.setTimeout(connect, delay)
}

/** Start the data layer once: first REST hydrate, live socket, and a slow retry while the backend is down. */
export function startDataLayer() {
  if (started) return
  started = true
  void useStore.getState().hydrate()
  connect()
  window.setInterval(() => {
    const s = useStore.getState()
    if (!s.connected || !s.app) void s.hydrate()
  }, 4000)
}
