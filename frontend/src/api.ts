import type {
  AppState,
  ChatEvent,
  ChatMessage,
  Decision,
  Game,
  GameDetail,
  LearningState,
  Memory,
  MemoryKind,
  OrderRequest,
  Position,
  Settings,
  Strategy,
  Trade,
  TrainResult,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError('Backend unreachable', 0)
  }
  if (res.status === 401) window.dispatchEvent(new Event('courtside:unauthorized'))
  if (!res.ok) {
    let detail = res.statusText || `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body && typeof body.detail === 'string') detail = body.detail
      else if (body && Array.isArray(body.detail) && body.detail[0]?.msg) detail = body.detail[0].msg
    } catch {
      if (res.status >= 500) detail = 'Backend unreachable'
    }
    throw new ApiError(detail, res.status)
  }
  try {
    return (await res.json()) as T
  } catch {
    throw new ApiError('Unexpected response from backend', res.status)
  }
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

function qs(params: Record<string, string | number | undefined | null>) {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  state: () => req<AppState>('/state'),
  updateSettings: (patch: Partial<Settings>) => req<AppState>('/settings', json('PUT', patch)),
  startAgent: () => req<AppState>('/agent/start', json('POST')),
  pauseAgent: () => req<AppState>('/agent/pause', json('POST')),

  games: () => req<Game[]>('/games'),
  game: (id: string) => req<GameDetail>(`/games/${encodeURIComponent(id)}`),

  positions: () => req<Position[]>('/positions'),
  closePosition: (id: number) => req<Trade>(`/positions/${id}/close`, json('POST')),
  trades: (limit = 100) => req<Trade[]>(`/trades${qs({ limit })}`),
  decisions: (limit = 100, gameId?: string) => req<Decision[]>(`/decisions${qs({ limit, game_id: gameId })}`),
  placeOrder: (order: OrderRequest) => req<Position>('/orders', json('POST', order)),

  playbook: () => req<Strategy[]>('/playbook'),
  updateStrategy: (id: string, patch: { enabled?: boolean; params?: Record<string, number> }) =>
    req<Strategy>(`/playbook/${encodeURIComponent(id)}`, json('PUT', patch)),

  memory: (kind?: MemoryKind | '', q?: string) => req<Memory[]>(`/memory${qs({ kind, q })}`),
  addGuidance: (text: string) => req<Memory>('/memory', json('POST', { text })),
  patchMemory: (id: number, patch: { pinned?: boolean; text?: string; importance?: number }) =>
    req<Memory>(`/memory/${id}`, json('PATCH', patch)),
  deleteMemory: (id: number) => req<{ ok: true }>(`/memory/${id}`, json('DELETE')),

  learning: () => req<LearningState>('/learning'),
  train: (episodes: number) => req<TrainResult>('/sim/train', json('POST', { episodes })),
  resetSim: () => req<AppState>('/sim/reset', json('POST')),

  chatHistory: () => req<ChatMessage[]>('/chat/history'),
  clearChat: () => req<{ ok: true }>('/chat/history', json('DELETE')),
}

/** POST /api/chat and feed each server-sent `ChatEvent` to `onEvent`. */
export async function streamChat(message: string, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) {
  let res: Response
  try {
    res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message }),
      signal,
    })
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') return
    throw new ApiError('Backend unreachable', 0)
  }
  if (!res.ok || !res.body) {
    let detail = 'The agent could not answer right now.'
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* keep default */
    }
    throw new ApiError(detail, res.status)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  const flush = (chunk: string) => {
    for (const line of chunk.split('\n')) {
      if (!line.startsWith('data:')) continue
      const payload = line.slice(5).trim()
      if (!payload) continue
      try {
        onEvent(JSON.parse(payload) as ChatEvent)
      } catch {
        /* ignore malformed frames */
      }
    }
  }
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let idx: number
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        flush(buf.slice(0, idx))
        buf = buf.slice(idx + 2)
      }
    }
    if (buf.trim()) flush(buf)
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') return
    throw new ApiError('Connection to the agent dropped mid-answer.', 0)
  }
}
