import { motion } from 'framer-motion'
import { Lock, LogIn, ShieldAlert } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Button, Spinner } from './components/ui'
import { startDataLayer } from './store'

interface AuthStatus {
  required: boolean
  locked: boolean
  authed: boolean
}

type Phase = 'checking' | 'open' | 'login' | 'locked' | 'down'

/**
 * Sits in front of the whole app. On a laptop with no password it is invisible;
 * hosted, it asks for the password (or explains that one has to be set first)
 * and only then lets the data layer connect.
 */
export default function Gate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>('checking')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const check = useCallback(async () => {
    try {
      const res = await fetch('/api/auth/status', { cache: 'no-store' })
      if (!res.ok) throw new Error(String(res.status))
      const s = (await res.json()) as AuthStatus
      if (typeof s?.locked !== 'boolean') throw new Error('not the API')
      if (s.locked) setPhase('locked')
      else if (s.authed) {
        startDataLayer()
        setPhase('open')
      } else setPhase('login')
    } catch {
      setPhase((p) => (p === 'open' ? 'open' : 'down'))
    }
  }, [])

  useEffect(() => {
    void check()
    const onExpired = () => setPhase('login')
    window.addEventListener('courtside:unauthorized', onExpired)
    return () => window.removeEventListener('courtside:unauthorized', onExpired)
  }, [check])

  // While the backend is unreachable or locked, keep looking for it.
  useEffect(() => {
    if (phase !== 'down' && phase !== 'locked') return
    const id = window.setInterval(() => void check(), 4000)
    return () => window.clearInterval(id)
  }, [phase, check])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!password || busy) return
    setBusy(true)
    setError(null)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      if (res.ok) {
        setPassword('')
        await check()
      } else {
        const body = await res.json().catch(() => null)
        setError(typeof body?.detail === 'string' ? body.detail : 'Could not sign in.')
      }
    } catch {
      setError('Backend unreachable.')
    } finally {
      setBusy(false)
    }
  }

  if (phase === 'open') return <>{children}</>

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: 'easeOut' }}
        className="w-full max-w-sm rounded-xl2 border border-hair2 bg-ink-900/90 p-7 shadow-lift backdrop-blur"
      >
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-hair2 bg-ink-800 text-peri">
            {phase === 'locked' ? <ShieldAlert size={18} /> : <Lock size={18} />}
          </div>
          <div>
            <div className="text-[15px] font-semibold text-white">Courtside</div>
            <div className="text-xs text-mute">Kalshi trading desk</div>
          </div>
        </div>

        {phase === 'checking' && (
          <div className="flex items-center gap-2 py-4 text-sm text-mute">
            <Spinner /> Checking the desk…
          </div>
        )}

        {phase === 'down' && (
          <div className="py-2 text-sm leading-relaxed text-mute">
            <div className="mb-1 flex items-center gap-2 font-medium text-white">
              <Spinner /> Connecting to the backend
            </div>
            It is not answering yet. If it was just deployed or has been idle, give it a minute; this page retries on
            its own.
          </div>
        )}

        {phase === 'locked' && (
          <div className="text-sm leading-relaxed text-mute">
            <div className="mb-2 font-medium text-gold">This desk is locked</div>
            It is running on a public address with no password set, so it will not let anyone in. Add an{' '}
            <code className="rounded bg-ink-700 px-1.5 py-0.5 font-mono text-[12px] text-white">APP_PASSWORD</code>{' '}
            environment variable to the API service, redeploy, and this page will turn into a sign-in.
          </div>
        )}

        {phase === 'login' && (
          <form onSubmit={submit} className="space-y-3">
            <label className="block text-xs font-medium uppercase tracking-wider text-dim" htmlFor="pw">
              Password
            </label>
            <input
              id="pw"
              type="password"
              autoFocus
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-hair2 bg-ink-950 px-3 py-2.5 text-sm text-white outline-none transition focus:border-peri/60 focus:shadow-glow"
            />
            {error && <div className="text-xs text-coral">{error}</div>}
            <Button type="submit" variant="primary" size="md" loading={busy} className="w-full">
              <LogIn size={14} className="mr-1.5" /> Sign in
            </Button>
          </form>
        )}
      </motion.div>
    </div>
  )
}
