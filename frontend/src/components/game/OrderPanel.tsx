import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, ChevronDown, Minus, Plus, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../../api'
import { cents, money, pct, segmentLabel, sideLabel, winsIf } from '../../format'
import { askOf, bidOf, modelChance, sizeOrder, type Pick } from '../../lib'
import { useStore } from '../../store'
import type { Game, LadderRung, Side } from '../../types'
import { Button } from '../ui'
import { useWatchNewBets, WatchSwitch } from '../Watch'

const QUICK = [25, 100, 300]
const SLIPPAGE = 2 // cents above the current price we will still accept, so a moving price does not bounce the order

function Line({ label, value, tone, strong }: { label: string; value: string; tone?: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="text-[13px] text-mute">{label}</span>
      <span className={clsx('num text-right', strong ? 'text-[15px] font-semibold' : 'text-sm font-medium', tone ?? 'text-white')}>{value}</span>
    </div>
  )
}

function HowItWorks() {
  return (
    <div className="p-6">
      <div className="h-section">Pick a price to start</div>
      <p className="hint mt-1.5">Tap any price on the left and your order shows up here.</p>
      <ol className="mt-5 space-y-3.5 text-[13px] leading-relaxed text-slate-300">
        {[
          ['Every contract pays $1 if you are right', 'and nothing if you are wrong.'],
          ['The price is the chance.', 'A 94¢ price means the market thinks it happens about 94 times in 100.'],
          ['You can sell before the end.', 'If the game turns, get out for whatever the price is then.'],
        ].map(([head, rest], i) => (
          <li key={i} className="flex gap-3">
            <span className="num flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink-800 text-xs font-semibold text-white">{i + 1}</span>
            <span>
              <span className="font-medium text-white">{head}</span> {rest}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

/** The one place an order is built: what you are buying, what it costs, what it pays. */
export default function OrderPanel({
  game,
  rungs,
  pick,
  onPick,
  closedSegments,
  bare = false,
}: {
  game: Game
  /** Every market of this game, so the panel follows the live price of whatever is picked. */
  rungs: LadderRung[]
  pick: Pick | null
  onPick: (p: Pick | null) => void
  /** Segments that can no longer be traded (finished quarters, or everything once the game is final). */
  closedSegments: Set<string>
  /** Drop the card frame: used inside the phone order sheet, which supplies its own. */
  bare?: boolean
}) {
  const settings = useStore((s) => s.app?.settings)
  const cash = useStore((s) => s.app?.account.cash ?? 0)
  const upsertPosition = useStore((s) => s.upsertPosition)

  const [amount, setAmount] = useState('100')
  const [fixedLimit, setFixedLimit] = useState<number | null>(null)
  const [advanced, setAdvanced] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [watch, setWatch] = useWatchNewBets()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  const rung = useMemo(() => (pick ? (rungs.find((r) => r.ticker === pick.ticker) ?? null) : null), [rungs, pick])

  // A new pick starts a clean order.
  useEffect(() => {
    setFixedLimit(null)
    setReviewing(false)
    setError(null)
    if (pick) setDone(null) // keep the "order placed" note up until the next pick
  }, [pick?.ticker, pick?.side]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!pick || !rung) {
    return (
      <div className="surface">
        <AnimatePresence mode="wait">
          {done ? (
            <motion.div key="done" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col items-center px-6 py-12 text-center">
              <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-mint/15 text-mint">
                <Check size={22} />
              </span>
              <div className="h-section">Order placed</div>
              <p className="hint mt-1">{done}</p>
              <Button variant="outline" className="mt-5" onClick={() => setDone(null)}>
                Done
              </Button>
            </motion.div>
          ) : (
            <motion.div key="how" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <HowItWorks />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    )
  }

  const side: Side = pick.side
  const live = settings?.trading_mode === 'live'
  const ask = askOf(rung, side)
  const bid = bidOf(rung, side)
  const closed = closedSegments.has(rung.segment ?? 'game')
  const dollars = Number(amount) || 0
  const order = ask != null ? sizeOrder(dollars, ask) : { contracts: 0, cost: 0, fees: 0 }
  const profit = order.contracts - order.cost
  const limit = fixedLimit ?? (ask != null ? Math.min(99, ask + SLIPPAGE) : null)
  const model = modelChance(rung, side)
  const where = rung.segment && rung.segment !== 'game' ? `${segmentLabel(rung.segment)} ${rung.kind === 'spread' ? 'spread' : 'total'}` : `Full game ${rung.kind === 'spread' ? 'spread' : 'total'}`

  const problem = closed
    ? 'This market has finished.'
    : ask == null
      ? 'No one is selling this side right now.'
      : dollars <= 0
        ? 'Enter an amount.'
        : order.contracts === 0
          ? `That is not enough for one contract at ${cents(ask)}.`
          : !live && order.cost > cash + 0.005
            ? `You only have ${money(cash)} to spend.`
            : fixedLimit != null && fixedLimit < ask
              ? `Your limit of ${cents(fixedLimit)} is below the current price, so this would not fill.`
              : null

  const place = async () => {
    if (problem || limit == null) return
    setBusy(true)
    setError(null)
    try {
      const pos = await api.placeOrder({ ticker: rung.ticker, side, contracts: order.contracts, price: limit, watch })
      upsertPosition(pos)
      const text = `${pos.contracts} of ${pos.label ?? sideLabel(rung, side)} at ${cents(pos.entry_price)}. You paid ${money(pos.cost)} and win ${money(pos.max_profit)} if it comes in.`
      setDone(text)
      onPick(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The order did not go through.')
      setReviewing(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={bare ? '' : 'surface overflow-hidden'}>
      <div className="flex items-start justify-between gap-3 px-5 pt-4 sm:px-6 sm:pt-5">
        <div className="min-w-0">
          <div className="text-xs text-mute">
            {game.label} · {where}
          </div>
          <div className="mt-0.5 break-words text-xl font-semibold text-white">Buy {sideLabel(rung, side)}</div>
        </div>
        <button onClick={() => onPick(null)} className="-mr-2 rounded-full p-2 text-dim hover:bg-white/[0.06] hover:text-white" aria-label="Clear">
          <X size={16} />
        </button>
      </div>

      <div className="px-5 pb-5 sm:px-6 sm:pb-6">
        {/* the two sides of this market */}
        <div className="mt-4 grid grid-cols-2 gap-2">
          {(['under', 'over'] as Side[]).map((s) => {
            const price = askOf(rung, s)
            return (
              <button
                key={s}
                onClick={() => onPick({ ticker: rung.ticker, side: s })}
                disabled={price == null}
                className={clsx(
                  'flex h-11 items-center justify-between rounded-full px-4 text-[13px] font-medium transition-colors disabled:opacity-35',
                  s === side ? 'bg-white text-ink-950' : 'bg-ink-800 text-slate-200 hover:bg-ink-700',
                )}
              >
                <span className="break-words">{sideLabel(rung, s)}</span>
                <span className="num font-semibold">{cents(price)}</span>
              </button>
            )
          })}
        </div>

        <p className="mt-3 text-[13px] leading-relaxed text-slate-300">{winsIf(rung, side)}.</p>

        {/* amount */}
        <label className="mt-5 block text-[13px] text-mute" htmlFor="amount">
          How much do you want to put down?
        </label>
        <div className="mt-2 flex items-center rounded-2xl bg-ink-800 px-4 focus-within:ring-1 focus-within:ring-white/40">
          <span className="text-2xl font-semibold text-mute">$</span>
          <input
            id="amount"
            inputMode="decimal"
            value={amount}
            onChange={(e) => {
              setAmount(e.target.value.replace(/[^0-9.]/g, ''))
              setReviewing(false)
            }}
            className="num h-14 w-full bg-transparent pl-1.5 text-2xl font-semibold text-white outline-none placeholder:text-dim"
            placeholder="0"
          />
        </div>
        <div className="mt-2 flex gap-2">
          {QUICK.map((q) => (
            <button
              key={q}
              onClick={() => {
                setAmount(String(q))
                setReviewing(false)
              }}
              className={clsx('num h-8 flex-1 rounded-full text-[13px] font-medium transition-colors', Number(amount) === q ? 'bg-white/[0.16] text-white' : 'bg-ink-800 text-mute hover:text-white')}
            >
              ${q}
            </button>
          ))}
        </div>

        {/* what happens */}
        <div className="mt-5 border-t border-hair pt-3">
          <Line label={order.contracts ? `You pay (${order.contracts} × ${cents(ask)}${order.fees ? ` + ${money(order.fees)} fee` : ''})` : 'You pay'} value={money(order.cost)} strong />
          <Line label="If you are right, you get" value={money(order.contracts)} />
          <Line label="Your profit if right" value={order.contracts ? `${money(profit, { sign: true })}  (${pct(order.cost ? profit / order.cost : 0)})` : '—'} tone="text-mint" />
          <Line label="If you are wrong, you lose" value={order.contracts ? money(order.cost) : '—'} tone="text-coral" />
        </div>

        <div className="mt-3 rounded-2xl bg-ink-800 px-4 py-3 text-[13px] leading-relaxed text-slate-300">
          The price says this happens about <span className="num font-semibold text-white">{ask != null ? `${ask}%` : '—'}</span> of the time. The model thinks{' '}
          <span className={clsx('num font-semibold', ask != null && model * 100 >= ask + 1 ? 'text-mint' : ask != null && model * 100 <= ask - 1 ? 'text-coral' : 'text-white')}>{pct(model)}</span>
          {ask != null && model * 100 >= ask + 1 ? ', so the price looks fair or better.' : ask != null && model * 100 <= ask - 1 ? ', so you may be overpaying.' : ', about the same.'}
        </div>

        {/* advanced: a fixed limit price */}
        <button onClick={() => setAdvanced((a) => !a)} className="mt-3 flex items-center gap-1 text-xs text-dim hover:text-mute">
          <ChevronDown size={13} className={clsx('transition-transform', advanced && 'rotate-180')} /> Price options
        </button>
        {advanced && (
          <div className="mt-2 rounded-2xl bg-ink-800 px-4 py-3">
            <div className="flex items-center justify-between">
              <div className="text-[13px] text-mute">Most you will pay per contract</div>
              <div className="flex items-center gap-1">
                <button className="rounded-full p-1.5 text-mute hover:bg-white/10 hover:text-white" onClick={() => setFixedLimit(Math.max(1, (limit ?? 50) - 1))} aria-label="Lower">
                  <Minus size={14} />
                </button>
                <span className="num w-11 text-center text-sm font-semibold text-white">{cents(limit)}</span>
                <button className="rounded-full p-1.5 text-mute hover:bg-white/10 hover:text-white" onClick={() => setFixedLimit(Math.min(99, (limit ?? 50) + 1))} aria-label="Raise">
                  <Plus size={14} />
                </button>
              </div>
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-dim">
              {fixedLimit == null
                ? `Following the price: you pay the going rate (${cents(ask)} now), up to ${SLIPPAGE}¢ more if it moves as you tap. You could sell right now for ${cents(bid)}.`
                : `Fixed at ${cents(fixedLimit)}. The order only fills if the price is at or below that.`}
              {fixedLimit != null && (
                <button className="ml-1 underline hover:text-mute" onClick={() => setFixedLimit(null)}>
                  Follow the price instead
                </button>
              )}
            </p>
          </div>
        )}

        <WatchSwitch on={watch} onChange={setWatch} />

        {(problem || error) && <div className={clsx('mt-4 text-[13px]', error ? 'text-coral' : 'text-gold')}>{error ?? problem}</div>}

        {live && reviewing ? (
          <div className="mt-4 rounded-2xl border border-coral/40 bg-coral/[0.08] p-4">
            <div className="text-sm font-semibold text-white">This is a real-money order</div>
            <p className="mt-1 text-[13px] leading-relaxed text-slate-300">
              {money(order.cost)} will be spent from your Kalshi account on {order.contracts} × {sideLabel(rung, side)}.
            </p>
            <div className="mt-3 flex gap-2">
              <Button variant="outline" className="flex-1" onClick={() => setReviewing(false)}>
                Cancel
              </Button>
              <Button variant="coral" className="flex-1" loading={busy} onClick={place}>
                Send order
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="mint" size="md" className="mt-4 w-full" disabled={!!problem} loading={busy} onClick={() => (live ? setReviewing(true) : place())}>
            {live ? 'Review order' : 'Place paper order'}
            {order.contracts > 0 && !problem ? ` · ${money(order.cost)}` : ''}
          </Button>
        )}
        <p className="mt-3 text-center text-xs text-dim">{live ? 'Live mode: orders go to your real Kalshi account.' : 'Paper mode: pretend money. Nothing is sent to Kalshi.'}</p>
      </div>
    </div>
  )
}
