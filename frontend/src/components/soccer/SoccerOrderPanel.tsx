import clsx from 'clsx'
import { Check, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ApiError } from '../../api'
import { cents, money, pct } from '../../format'
import { sizeOrder } from '../../lib'
import { askOf, bidOf, chanceOf, labelOf, soccerApi, type SAccount, type SMarket, type SSide } from '../../soccer'
import { useStore } from '../../store'
import { Button } from '../ui'
import { useWatchNewBets, WatchSwitch } from '../Watch'

const QUICK = [25, 100, 300]
const SLIPPAGE = 2 // cents above the current price still accepted, so a moving price does not bounce the order

export interface SPick {
  ticker: string
  side: SSide
}

function Line({ label, value, tone, strong }: { label: string; value: string; tone?: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="text-[13px] text-mute">{label}</span>
      <span className={clsx('num text-right', strong ? 'text-[15px] font-semibold' : 'text-sm font-medium', tone ?? 'text-white')}>{value}</span>
    </div>
  )
}

const where = (m: SMarket) =>
  `${m.segment === '1h' ? '1st half' : 'Full match'} · ${m.kind === 'winner' ? 'result' : m.kind === 'total' ? 'goals' : 'spread'}`

/** Building one soccer order: what you buy, what it costs, what it pays. */
export default function SoccerOrderPanel({
  label,
  markets,
  pick,
  onPick,
  account,
  live,
  closed,
  onPlaced,
  bare = false,
}: {
  label: string
  markets: SMarket[]
  pick: SPick | null
  onPick: (p: SPick | null) => void
  account: SAccount | null
  live: boolean
  closed: (m: SMarket) => boolean
  onPlaced: () => void
  bare?: boolean
}) {
  const [amount, setAmount] = useState('100')
  const [reviewing, setReviewing] = useState(false)
  const [watch, setWatch] = useWatchNewBets()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const toast = useStore((s) => s.toast)
  const market = pick ? (markets.find((m) => m.ticker === pick.ticker) ?? null) : null

  useEffect(() => {
    setReviewing(false)
    setError(null)
    if (pick) setDone(null)
  }, [pick?.ticker, pick?.side]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!pick || !market) {
    return (
      <div className={bare ? 'p-6' : 'surface p-6'}>
        {done ? (
          <div className="flex flex-col items-center py-6 text-center">
            <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-mint/15 text-mint">
              <Check size={22} />
            </span>
            <div className="h-section">Order placed</div>
            <p className="hint mt-1">{done}</p>
            <Button variant="outline" className="mt-5" onClick={() => setDone(null)}>
              Done
            </Button>
          </div>
        ) : (
          <>
            <div className="h-section">Pick a price to start</div>
            <p className="hint mt-1.5">
              Tap Yes or No on any market. Yes is the outcome in its name; No is everything else. Each contract pays $1 if you are right.
            </p>
          </>
        )}
      </div>
    )
  }

  const side = pick.side
  const ask = askOf(market, side)
  const bid = bidOf(market, side)
  const dollars = Number(amount) || 0
  const order = ask != null ? sizeOrder(dollars, ask) : { contracts: 0, cost: 0, fees: 0 }
  const profit = order.contracts - order.cost
  const limit = ask != null ? Math.min(99, ask + SLIPPAGE) : null
  const model = chanceOf(market, side)
  const cash = account?.cash ?? 0

  const problem = closed(market)
    ? 'This market is decided.'
    : ask == null
      ? 'No one is selling this side right now.'
      : dollars <= 0
        ? 'Enter an amount.'
        : order.contracts === 0
          ? `That is not enough for one contract at ${cents(ask)}.`
          : !live && order.cost > cash + 0.005
            ? `You only have ${money(cash)} of soccer paper cash.`
            : null

  const place = async () => {
    if (problem || limit == null) return
    setBusy(true)
    setError(null)
    try {
      const pos = await soccerApi.order({ ticker: market.ticker, side, contracts: order.contracts, price: limit, watch })
      const text = `${pos.contracts} of ${pos.label} at ${cents(pos.entry_price)}. You paid ${money(pos.cost)} and win ${money(pos.max_profit)} if it comes in.`
      setDone(text)
      if (bare) toast({ level: 'success', title: 'Order placed', body: text }) // the phone sheet closes, so say it here
      onPick(null)
      onPlaced()
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
          <div className="break-words text-xs text-mute">
            {label} · {where(market)}
          </div>
          <div className="mt-0.5 text-xl font-semibold leading-tight text-white">Buy {labelOf(market, side)}</div>
        </div>
        <button onClick={() => onPick(null)} className="-mr-2 rounded-full p-2 text-dim hover:bg-white/[0.06] hover:text-white" aria-label="Clear">
          <X size={16} />
        </button>
      </div>

      <div className="px-5 pb-5 sm:px-6 sm:pb-6">
        <div className="mt-4 grid grid-cols-2 gap-2">
          {(['yes', 'no'] as SSide[]).map((s) => (
            <button
              key={s}
              onClick={() => onPick({ ticker: market.ticker, side: s })}
              disabled={askOf(market, s) == null}
              className={clsx(
                'flex h-11 items-center justify-between gap-2 rounded-full px-4 text-[13px] font-medium transition-colors disabled:opacity-35',
                s === side ? 'bg-white text-ink-950' : 'bg-ink-800 text-slate-200 hover:bg-ink-700',
              )}
            >
              <span>{s === 'yes' ? 'Yes' : 'No'}</span>
              <span className="num font-semibold">{cents(askOf(market, s))}</span>
            </button>
          ))}
        </div>
        <p className="mt-3 text-[13px] leading-relaxed text-slate-300">You win if: {labelOf(market, side)}.</p>

        <label className="mt-5 block text-[13px] text-mute" htmlFor="soccer-amount">
          How much do you want to put down?
        </label>
        <div className="mt-2 flex items-center rounded-2xl bg-ink-800 px-4 focus-within:ring-1 focus-within:ring-white/40">
          <span className="text-2xl font-semibold text-mute">$</span>
          <input
            id="soccer-amount"
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

        <div className="mt-5 border-t border-hair pt-3">
          <Line label={order.contracts ? `You pay (${order.contracts} × ${cents(ask)}${order.fees ? ` + ${money(order.fees)} fee` : ''})` : 'You pay'} value={money(order.cost)} strong />
          <Line label="If you are right, you get" value={money(order.contracts)} />
          <Line label="Your profit if right" value={order.contracts ? `${money(profit, { sign: true })}  (${pct(order.cost ? profit / order.cost : 0)})` : '—'} tone="text-mint" />
          <Line label="If you are wrong, you lose" value={order.contracts ? money(order.cost) : '—'} tone="text-coral" />
        </div>

        <div className="mt-3 rounded-2xl bg-ink-800 px-4 py-3 text-[13px] leading-relaxed text-slate-300">
          The price says this happens about <span className="num font-semibold text-white">{ask != null ? `${ask}%` : '—'}</span> of the time. The goals model says{' '}
          <span
            className={clsx(
              'num font-semibold',
              model == null || ask == null ? 'text-white' : model * 100 >= ask + 1 ? 'text-mint' : model * 100 <= ask - 1 ? 'text-coral' : 'text-white',
            )}
          >
            {model != null ? pct(model) : '—'}
          </span>
          . It knows the score, the minute and red cards, not who is on top. You could sell right now for {cents(bid)}.
        </div>

        <WatchSwitch on={watch} onChange={setWatch} />

        {(problem || error) && <div className={clsx('mt-4 text-[13px]', error ? 'text-coral' : 'text-gold')}>{error ?? problem}</div>}

        {live && reviewing ? (
          <div className="mt-4 rounded-2xl border border-coral/40 bg-coral/[0.08] p-4">
            <div className="text-sm font-semibold text-white">This is a real-money order</div>
            <p className="mt-1 text-[13px] leading-relaxed text-slate-300">
              {money(order.cost)} will be spent from your Kalshi account on {order.contracts} × {labelOf(market, side)}.
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
        <p className="mt-3 text-center text-xs text-dim">{live ? 'Live mode: orders go to your real Kalshi account.' : 'Paper mode: pretend money, separate from the NBA book.'}</p>
      </div>
    </div>
  )
}
