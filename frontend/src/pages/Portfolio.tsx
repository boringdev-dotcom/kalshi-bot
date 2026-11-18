import { AnimatePresence, motion } from 'framer-motion'
import clsx from 'clsx'
import { Bot, Briefcase, History, ShieldCheck, TrendingUp, User } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, ApiError } from '../api'
import { Page } from '../components/Layout'
import { Badge, Button, Card, Dialog, Empty, Meter, RiskDot, SectionTitle, Segmented, SimTag, Skeleton, Ticker, type Tone } from '../components/ui'
import { cents, money, pct, pnlColor, relTime, shortDate, signedPct } from '../format'
import { useStore } from '../store'
import type { ExitReason, LearningState, Position, Trade } from '../types'

function Tile({
  label,
  children,
  sub,
  accent,
}: {
  label: string
  children: React.ReactNode
  sub?: React.ReactNode
  accent?: string
}) {
  return (
    <motion.div whileHover={{ y: -2 }} transition={{ type: 'spring', stiffness: 400, damping: 28 }}>
      <Card className="relative overflow-hidden p-4">
        {accent && (
          <span
            className="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full opacity-25 blur-2xl"
            style={{ background: accent }}
          />
        )}
        <div className="label">{label}</div>
        <div className="num mt-2 text-[22px] font-bold leading-none tracking-tight text-slate-50">{children}</div>
        <div className="mt-2 h-4 text-[11px] text-dim">{sub}</div>
      </Card>
    </motion.div>
  )
}

const exitMeta: Record<ExitReason, { label: string; tone: Tone }> = {
  settled_win: { label: 'Settled · won', tone: 'mint' },
  settled_loss: { label: 'Settled · lost', tone: 'coral' },
  risk_exit: { label: 'Risk exit', tone: 'gold' },
  stop_loss: { label: 'Stop loss', tone: 'coral' },
  take_profit: { label: 'Took profit', tone: 'mint' },
  manual: { label: 'Manual', tone: 'slate' },
}

function Who({ by }: { by: 'agent' | 'user' }) {
  return (
    <span
      className={clsx('inline-flex items-center gap-1 text-[10.5px]', by === 'agent' ? 'text-peri' : 'text-mute')}
      title={by === 'agent' ? 'Opened by the agent' : 'Opened by you'}
    >
      {by === 'agent' ? <Bot size={11} /> : <User size={11} />}
      {by === 'agent' ? 'Agent' : 'You'}
    </span>
  )
}

const th = 'px-3 py-2 text-left text-[9.5px] font-semibold uppercase tracking-wider text-dim whitespace-nowrap'
const td = 'px-3 py-2.5 align-middle whitespace-nowrap'

function PositionsTable({ positions, onClose }: { positions: Position[]; onClose: (p: Position) => void }) {
  if (positions.length === 0)
    return (
      <Empty
        icon={<Briefcase size={18} />}
        title="No open positions"
        body="Positions opened by you or the agent appear here with live marks and the model’s current win chance."
      />
    )
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] border-collapse">
        <thead>
          <tr className="border-b border-hair">
            <th className={th}>Position</th>
            <th className={clsx(th, 'text-right')}>Qty</th>
            <th className={clsx(th, 'text-right')}>Entry → Mark</th>
            <th className={clsx(th, 'text-right')}>Cost</th>
            <th className={clsx(th, 'text-right')}>P&L</th>
            <th className={th}>Win chance · now vs entry</th>
            <th className={th}>Risk</th>
            <th className={th} />
          </tr>
        </thead>
        <tbody>
          <AnimatePresence initial={false}>
            {positions.map((p) => {
              const drift = p.p_win - p.p_win_entry
              return (
                <motion.tr
                  key={p.id}
                  layout
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0, x: -20 }}
                  className="group border-b border-hair transition-colors last:border-0 hover:bg-white/[0.025]"
                >
                  <td className={td}>
                    <div className="flex items-center gap-2">
                      <span
                        className={clsx(
                          'rounded-md px-1.5 py-[2px] text-[10.5px] font-bold uppercase tracking-wide',
                          p.side === 'under' ? 'text-mint' : 'text-coral',
                        )}
                        style={{ background: p.side === 'under' ? 'rgba(61,220,151,0.12)' : 'rgba(255,107,107,0.12)' }}
                      >
                        {p.side} {p.strike}
                      </span>
                      <span className="text-xs font-semibold text-slate-100">{p.game_label}</span>
                      {p.simulated && <SimTag />}
                      {p.mode === 'live' && <Badge tone="coral">Live</Badge>}
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <Who by={p.opened_by} />
                      <span className="text-[10.5px] text-dim">{relTime(p.opened_at)}</span>
                      {p.exit_profile && <span className="text-[10.5px] text-dim">· exit: {p.exit_profile}</span>}
                    </div>
                  </td>
                  <td className={clsx(td, 'num text-right text-xs text-slate-200')}>{p.contracts}</td>
                  <td className={clsx(td, 'num text-right text-xs')}>
                    <span className="text-mute">{cents(p.entry_price)}</span>
                    <span className="mx-1 text-dim">→</span>
                    <Ticker value={p.mark_price} format={(n) => cents(n)} className="font-semibold text-slate-100" />
                  </td>
                  <td className={clsx(td, 'num text-right text-xs text-slate-300')}>{money(p.cost)}</td>
                  <td className={clsx(td, 'text-right')}>
                    <Ticker
                      value={p.pnl}
                      format={(n) => money(n, { sign: true })}
                      flash={false}
                      className={clsx('text-[13px] font-semibold', pnlColor(p.pnl))}
                    />
                    <div className="num text-[10px] text-dim">max {money(p.max_profit, { sign: true })}</div>
                  </td>
                  <td className={td}>
                    <div className="flex items-center gap-2">
                      <Meter
                        value={p.p_win}
                        marker={p.p_win_entry}
                        tone={p.p_win >= 0.9 ? '#3ddc97' : p.p_win >= 0.75 ? '#f5b74e' : '#ff6b6b'}
                        height={6}
                        className="w-[110px]"
                      />
                      <span className="num text-xs font-semibold text-slate-100">{pct(p.p_win, 1)}</span>
                      <span className={clsx('num text-[10.5px]', drift >= 0 ? 'text-mint' : 'text-coral')}>
                        {signedPct(drift, 1)}
                      </span>
                    </div>
                  </td>
                  <td className={td}>
                    <div className="flex max-w-[220px] items-center gap-1.5">
                      <RiskDot level={p.risk.level} flags={p.risk.flags} />
                      <span className="truncate text-[11px] text-mute" title={p.risk.flags.join(' · ')}>
                        {p.risk.flags[0] ?? (p.risk.level === 'low' ? 'Comfortable' : p.risk.level)}
                      </span>
                    </div>
                  </td>
                  <td className={clsx(td, 'text-right')}>
                    <Button size="xs" variant="outline" onClick={() => onClose(p)}>
                      Close
                    </Button>
                  </td>
                </motion.tr>
              )
            })}
          </AnimatePresence>
        </tbody>
      </table>
    </div>
  )
}

function TradesTable({ trades }: { trades: Trade[] }) {
  if (trades.length === 0)
    return (
      <Empty
        icon={<History size={18} />}
        title="No closed trades yet"
        body="Once a position settles or is sold, it lands here with what holding to the end would have paid."
      />
    )
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] border-collapse">
        <thead>
          <tr className="border-b border-hair">
            <th className={th}>Trade</th>
            <th className={clsx(th, 'text-right')}>Qty</th>
            <th className={clsx(th, 'text-right')}>Entry → Exit</th>
            <th className={clsx(th, 'text-right')}>P&L</th>
            <th className={th}>Exit</th>
            <th className={clsx(th, 'text-right')}>If held</th>
            <th className={th}>Verdict</th>
            <th className={clsx(th, 'text-right')}>Final</th>
            <th className={clsx(th, 'text-right')}>Closed</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => {
            const exit = exitMeta[t.exit_reason] ?? { label: t.exit_reason, tone: 'slate' as Tone }
            return (
              <tr key={t.id} className="border-b border-hair transition-colors last:border-0 hover:bg-white/[0.025]">
                <td className={td}>
                  <div className="flex items-center gap-2">
                    <span
                      className={clsx(
                        'rounded-md px-1.5 py-[2px] text-[10.5px] font-bold uppercase tracking-wide',
                        t.side === 'under' ? 'text-mint' : 'text-coral',
                      )}
                      style={{ background: t.side === 'under' ? 'rgba(61,220,151,0.12)' : 'rgba(255,107,107,0.12)' }}
                    >
                      {t.side} {t.strike}
                    </span>
                    <span className="text-xs font-semibold text-slate-100">{t.game_label}</span>
                    {t.simulated && <SimTag />}
                    {t.mode === 'live' && <Badge tone="coral">Live</Badge>}
                  </div>
                  <div className="mt-1">
                    <Who by={t.opened_by} />
                  </div>
                </td>
                <td className={clsx(td, 'num text-right text-xs text-slate-200')}>{t.contracts}</td>
                <td className={clsx(td, 'num text-right text-xs text-mute')}>
                  {cents(t.entry_price)} <span className="text-dim">→</span>{' '}
                  <span className="text-slate-100">{cents(t.exit_price)}</span>
                </td>
                <td className={clsx(td, 'num text-right text-[13px] font-semibold', pnlColor(t.pnl))}>
                  {money(t.pnl, { sign: true })}
                </td>
                <td className={td}>
                  <Badge tone={exit.tone}>{exit.label}</Badge>
                </td>
                <td className={clsx(td, 'num text-right text-xs', t.counterfactual_pnl == null ? 'text-dim' : pnlColor(t.counterfactual_pnl))}>
                  {t.counterfactual_pnl == null ? 'pending' : money(t.counterfactual_pnl, { sign: true })}
                </td>
                <td className={td}>
                  {t.exit_verdict === 'saved' ? (
                    <Badge tone="mint" title="Selling early beat holding to the end">
                      <ShieldCheck size={10} /> Saved
                    </Badge>
                  ) : t.exit_verdict === 'shaken_out' ? (
                    <Badge tone="gold" title="Holding to the end would have paid more">
                      Shaken out
                    </Badge>
                  ) : (
                    <span className="text-[11px] text-dim">—</span>
                  )}
                </td>
                <td className={clsx(td, 'num text-right text-xs text-slate-300')}>{t.final_total ?? '—'}</td>
                <td className={clsx(td, 'num text-right text-[11px] text-dim')}>{shortDate(t.closed_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function EquityTooltip({ active, payload }: { active?: boolean; payload?: { payload: { ts: string; equity: number; simulated: boolean } }[] }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="rounded-xl border border-hair2 bg-ink-800/95 px-3 py-2 shadow-lift">
      <div className="num text-[10.5px] text-mute">{shortDate(p.ts)}</div>
      <div className="num mt-0.5 text-sm font-semibold text-slate-50">{money(p.equity)}</div>
      {p.simulated && <div className="mt-0.5 text-[10px] text-gold">simulated</div>}
    </div>
  )
}

function EquityCurve({ learning }: { learning: LearningState | null }) {
  const [scope, setScope] = useState<'real' | 'all'>('all')
  const data = useMemo(() => {
    const pts = learning?.equity_curve ?? []
    const filtered = scope === 'real' ? pts.filter((p) => !p.simulated) : pts
    return filtered.map((p, i) => ({ ...p, i }))
  }, [learning, scope])
  const hasSim = (learning?.equity_curve ?? []).some((p) => p.simulated)
  const up = data.length > 1 ? data[data.length - 1].equity >= data[0].equity : true
  const color = up ? '#3ddc97' : '#ff6b6b'

  return (
    <Card className="p-4">
      <SectionTitle
        right={
          hasSim ? (
            <Segmented
              id="equity-scope"
              value={scope}
              onChange={setScope}
              options={[
                { value: 'all', label: 'All' },
                { value: 'real', label: 'Exclude sim' },
              ]}
            />
          ) : undefined
        }
      >
        Equity curve
      </SectionTitle>
      <div className="mt-3 h-[220px]">
        {!learning ? (
          <Skeleton className="h-full w-full !rounded-xl" />
        ) : data.length < 2 ? (
          <Empty icon={<TrendingUp size={18} />} title="Not enough history yet" body="Your equity is plotted here after the first few closed trades." />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: -6 }}>
              <defs>
                <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={0.28} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis dataKey="i" hide />
              <YAxis
                domain={['auto', 'auto']}
                axisLine={false}
                tickLine={false}
                width={62}
                tickFormatter={(v: number) => `$${Math.round(v).toLocaleString()}`}
              />
              <Tooltip content={<EquityTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.14)', strokeDasharray: '3 3' }} />
              <Area dataKey="equity" type="monotone" stroke={color} strokeWidth={2} fill="url(#eqFill)" isAnimationActive={false} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  )
}

export default function Portfolio() {
  const account = useStore((s) => s.app?.account)
  const positions = useStore((s) => s.positions)
  const trades = useStore((s) => s.trades)
  const tradeTick = useStore((s) => s.tradeTick)
  const addTrade = useStore((s) => s.addTrade)
  const toast = useStore((s) => s.toast)
  const [learning, setLearning] = useState<LearningState | null>(null)
  const [closing, setClosing] = useState<Position | null>(null)
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState<'all' | 'agent' | 'user'>('all')

  useEffect(() => {
    let alive = true
    api
      .learning()
      .then((l) => alive && l && setLearning(l))
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [tradeTick])

  const shownTrades = useMemo(
    () => (filter === 'all' ? trades : trades.filter((t) => t.opened_by === filter)),
    [trades, filter],
  )
  // Keep the dialog's numbers live while it is open.
  const closingLive = closing ? positions.find((p) => p.id === closing.id) ?? closing : null

  const confirmClose = async () => {
    if (!closing) return
    setBusy(true)
    try {
      const trade = await api.closePosition(closing.id)
      addTrade(trade, closing.id)
      toast({
        level: trade.pnl >= 0 ? 'success' : 'warn',
        title: `Closed ${trade.side} ${trade.strike} · ${money(trade.pnl, { sign: true })}`,
        body: `${trade.contracts} contracts sold at ${cents(trade.exit_price)} — ${trade.game_label}`,
      })
      setClosing(null)
    } catch (e) {
      toast({ level: 'error', title: 'Could not close the position', body: e instanceof ApiError ? e.message : '' })
    } finally {
      setBusy(false)
    }
  }

  const record = account ? account.wins + account.losses : 0

  return (
    <Page title="Portfolio" subtitle="Open risk, closed trades and how early exits compared with holding.">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Tile label="Equity" accent="#8b9cff" sub={account ? `Total P&L ${money(account.pnl_total, { sign: true })}` : null}>
          {account ? <Ticker value={account.equity} format={(n) => money(n)} /> : <Skeleton className="h-6 w-28" />}
        </Tile>
        <Tile label="Cash" sub="Available to trade">
          {account ? <Ticker value={account.cash} format={(n) => money(n)} flash={false} /> : <Skeleton className="h-6 w-24" />}
        </Tile>
        <Tile label="Exposure" accent="#f5b74e" sub={account ? `${account.open_positions} open position${account.open_positions === 1 ? '' : 's'}` : null}>
          {account ? <Ticker value={account.exposure} format={(n) => money(n)} flash={false} /> : <Skeleton className="h-6 w-24" />}
        </Tile>
        <Tile label="Today" accent={account && account.pnl_today < 0 ? '#ff6b6b' : '#3ddc97'} sub="Realized + open marks">
          {account ? (
            <span className={pnlColor(account.pnl_today)}>
              <Ticker value={account.pnl_today} format={(n) => money(n, { sign: true })} flash={false} />
            </span>
          ) : (
            <Skeleton className="h-6 w-20" />
          )}
        </Tile>
        <Tile label="Record" sub={account && record > 0 ? `${pct(account.wins / record)} win rate` : 'No closed trades'}>
          {account ? (
            <span>
              <span className="text-mint">{account.wins}</span>
              <span className="mx-1 text-dim">–</span>
              <span className="text-coral">{account.losses}</span>
            </span>
          ) : (
            <Skeleton className="h-6 w-16" />
          )}
        </Tile>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3">
        <Card className="overflow-hidden">
          <div className="px-4 pb-2 pt-4">
            <SectionTitle right={<span className="num text-[11px] text-dim">{positions.length} open</span>}>
              Open positions
            </SectionTitle>
          </div>
          <PositionsTable positions={positions} onClose={setClosing} />
        </Card>

        <EquityCurve learning={learning} />

        <Card className="overflow-hidden">
          <div className="px-4 pb-2 pt-4">
            <SectionTitle
              right={
                <Segmented
                  id="trade-filter"
                  value={filter}
                  onChange={setFilter}
                  options={[
                    { value: 'all', label: 'All' },
                    { value: 'agent', label: 'Agent' },
                    { value: 'user', label: 'Mine' },
                  ]}
                />
              }
            >
              Closed trades
            </SectionTitle>
          </div>
          <TradesTable trades={shownTrades} />
        </Card>
      </div>

      <Dialog
        open={!!closing}
        onClose={() => !busy && setClosing(null)}
        title="Close this position?"
        subtitle={closingLive ? `${closingLive.game_label} · ${closingLive.side} ${closingLive.strike}` : undefined}
        accent="#f5b74e"
        width={420}
      >
        {closingLive && (
          <>
            <div className="rounded-xl border border-hair bg-ink-950/50 px-3.5 py-2.5 text-xs">
              <div className="flex justify-between py-1">
                <span className="text-mute">Sell</span>
                <span className="num text-slate-100">
                  {closingLive.contracts} contracts at about {cents(closingLive.mark_price)}
                </span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-mute">Result if filled at the mark</span>
                <span className={clsx('num font-semibold', pnlColor(closingLive.pnl))}>{money(closingLive.pnl, { sign: true })}</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-mute">Model win chance if you hold</span>
                <span className="num text-slate-100">{pct(closingLive.p_win, 1)}</span>
              </div>
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-dim">
              {closingLive.mode === 'live'
                ? 'This sends a real sell order to Kalshi at the current bid.'
                : 'Paper position — nothing is sent to Kalshi.'}
            </p>
            <div className="mt-4 flex gap-2">
              <Button variant="ghost" size="md" className="flex-1" onClick={() => setClosing(null)} disabled={busy}>
                Keep it
              </Button>
              <Button variant="primary" size="md" className="flex-[2]" onClick={confirmClose} loading={busy}>
                Close position
              </Button>
            </div>
          </>
        )}
      </Dialog>
    </Page>
  )
}
