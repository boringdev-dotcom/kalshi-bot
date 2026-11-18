import clsx from 'clsx'
import { ArrowDownRight, ArrowUpRight, Minus, Plus } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import { cents, clamp, money, pct, signedPct } from '../format'
import { useStore } from '../store'
import type { Game, Side } from '../types'
import type { TicketTarget } from './Ladder'
import { Badge, Button, Dialog, Meter, Segmented, Slider } from './ui'

function Line({ label, children, strong }: { label: string; children: React.ReactNode; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-mute">{label}</span>
      <span className={clsx('num text-[13px]', strong ? 'font-semibold text-slate-50' : 'text-slate-200')}>{children}</span>
    </div>
  )
}

export default function OrderTicket({
  game,
  target,
  onClose,
}: {
  game: Game
  target: TicketTarget | null
  onClose: () => void
}) {
  const settings = useStore((s) => s.app?.settings)
  const cash = useStore((s) => s.app?.account.cash)
  const toast = useStore((s) => s.toast)
  const upsertPosition = useStore((s) => s.upsertPosition)

  const [side, setSide] = useState<Side>('under')
  const [price, setPrice] = useState(50)
  const [stake, setStake] = useState(100)
  const [mode, setMode] = useState<'dollars' | 'contracts'>('dollars')
  const [contractsInput, setContractsInput] = useState(100)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // The ladder keeps ticking underneath; follow the live rung for model numbers.
  // Remember the last target so the dialog keeps its content while it animates out.
  const lastTarget = useRef(target)
  if (target) lastTarget.current = target
  const shown = target ?? lastTarget.current
  const rung = useMemo(() => {
    if (!shown) return null
    return game.ladder.find((r) => r.ticker === shown.rung.ticker) ?? shown.rung
  }, [game.ladder, shown])

  const maxStake = Math.max(10, settings?.max_stake_per_trade ?? 500)

  useEffect(() => {
    if (!target) return
    const ask = target.side === 'under' ? target.rung.no_ask : target.rung.yes_ask
    setSide(target.side)
    setPrice(ask ?? 50)
    setStake((s) => clamp(s, 1, maxStake))
    setError(null)
    setBusy(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target?.rung.ticker, target?.side])

  if (!rung) return null

  const ask = side === 'under' ? rung.no_ask : rung.yes_ask
  const bid = side === 'under' ? rung.no_bid : rung.yes_bid
  const pWin = side === 'under' ? rung.p_under : 1 - rung.p_under
  const px = clamp(Math.round(price) || 1, 1, 99)
  const contracts = mode === 'dollars' ? Math.max(0, Math.floor((stake * 100) / px)) : Math.max(0, Math.floor(contractsInput))
  const cost = (contracts * px) / 100
  const maxProfit = (contracts * (100 - px)) / 100
  const ret = (100 - px) / px
  const breakeven = px / 100
  const edge = pWin - breakeven
  const expected = contracts * (pWin - breakeven)
  const overLimit = cost > maxStake + 0.001
  const overCash = cash != null && cost > cash + 0.001
  const live = settings?.trading_mode === 'live'
  const accent = side === 'under' ? '#3ddc97' : '#ff6b6b'

  const submit = async () => {
    if (contracts <= 0) return
    setBusy(true)
    setError(null)
    try {
      const pos = await api.placeOrder({ ticker: rung.ticker, side, contracts, price: px })
      upsertPosition(pos)
      toast({
        level: 'success',
        title: `${live ? 'Order sent' : 'Paper order filled'} · ${side === 'under' ? 'Under' : 'Over'} ${rung.strike}`,
        body: `${contracts} contracts at ${cents(px)} for ${money(cost)} — ${game.label}`,
      })
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Order failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={!!target}
      onClose={onClose}
      accent={accent}
      width={460}
      title={
        <span className="flex items-center gap-2">
          {side === 'under' ? <ArrowDownRight size={17} className="text-mint" /> : <ArrowUpRight size={17} className="text-coral" />}
          {side === 'under' ? 'Under' : 'Over'} <span className="num">{rung.strike.toFixed(1)}</span>
        </span>
      }
      subtitle={
        <span className="flex items-center gap-2">
          {game.label} · total points
          {game.simulated && <Badge tone="gold">Sim</Badge>}
          <Badge tone={live ? 'coral' : 'peri'}>{live ? 'Live money' : 'Paper'}</Badge>
        </span>
      }
    >
      <div className="mb-4 flex items-center justify-between">
        <Segmented<Side>
          id="ticket-side"
          size="md"
          value={side}
          onChange={(s) => {
            setSide(s)
            const a = s === 'under' ? rung.no_ask : rung.yes_ask
            if (a != null) setPrice(a)
          }}
          options={[
            { value: 'under', label: `Under ${cents(rung.no_ask)}`, tone: '#3ddc97' },
            { value: 'over', label: `Over ${cents(rung.yes_ask)}`, tone: '#ff6b6b' },
          ]}
        />
        <Segmented
          id="ticket-mode"
          value={mode}
          onChange={setMode}
          options={[
            { value: 'dollars', label: '$' },
            { value: 'contracts', label: 'Qty' },
          ]}
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="surface-raised p-3">
          <div className="label">Limit price</div>
          <div className="mt-1.5 flex items-center gap-1.5">
            <button
              className="flex h-7 w-7 items-center justify-center rounded-md border border-hair2 text-mute hover:bg-white/[0.06] hover:text-slate-100"
              onClick={() => setPrice((p) => clamp(p - 1, 1, 99))}
              aria-label="Lower price"
            >
              <Minus size={13} />
            </button>
            <div className="num flex-1 text-center text-xl font-bold text-slate-50">{cents(px)}</div>
            <button
              className="flex h-7 w-7 items-center justify-center rounded-md border border-hair2 text-mute hover:bg-white/[0.06] hover:text-slate-100"
              onClick={() => setPrice((p) => clamp(p + 1, 1, 99))}
              aria-label="Raise price"
            >
              <Plus size={13} />
            </button>
          </div>
          <div className="num mt-1.5 text-center text-[10.5px] text-dim">
            bid {cents(bid)} · ask {cents(ask)}
            {ask != null && px < ask && <span className="ml-1 text-gold">below the ask, will not fill</span>}
          </div>
        </div>

        <div className="surface-raised p-3">
          <div className="label">{mode === 'dollars' ? 'Stake' : 'Contracts'}</div>
          <div className="mt-1.5 flex items-baseline justify-center gap-1">
            {mode === 'dollars' && <span className="num text-sm text-dim">$</span>}
            <input
              type="number"
              min={1}
              value={mode === 'dollars' ? stake : contractsInput}
              onChange={(e) => {
                const v = Math.max(0, Number(e.target.value) || 0)
                if (mode === 'dollars') setStake(v)
                else setContractsInput(v)
              }}
              className="num w-24 bg-transparent text-center text-xl font-bold text-slate-50 outline-none"
            />
          </div>
          <div className="num mt-1.5 text-center text-[10.5px] text-dim">
            {mode === 'dollars' ? `${contracts} contracts` : `${money(cost)} cost`}
          </div>
        </div>
      </div>

      <div className="mt-3 px-1">
        {mode === 'dollars' ? (
          <Slider value={Math.min(stake, maxStake)} min={5} max={maxStake} step={5} onChange={setStake} tone={accent} ariaLabel="Stake" />
        ) : (
          <Slider
            value={Math.min(contractsInput, Math.floor((maxStake * 100) / px))}
            min={1}
            max={Math.max(1, Math.floor((maxStake * 100) / px))}
            step={1}
            onChange={setContractsInput}
            tone={accent}
            ariaLabel="Contracts"
          />
        )}
        <div className="num mt-0.5 flex justify-between text-[10px] text-dim">
          <span>min</span>
          <span>per-trade limit {money(maxStake, { decimals: 0 })}</span>
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-hair bg-ink-950/50 px-3.5 py-2">
        <Line label="Cost" strong>
          {money(cost)}
        </Line>
        <Line label="Max profit if it wins">
          <span className="text-mint">{money(maxProfit, { sign: true })}</span>
          <span className="ml-1.5 text-[11px] text-dim">({signedPct(ret, 1)})</span>
        </Line>
        <Line label="Max loss if it loses">
          <span className="text-coral">{money(-cost, { sign: true })}</span>
        </Line>
        <div className="my-1.5 border-t border-hair" />
        <div className="py-1.5">
          <div className="mb-1.5 flex items-center justify-between text-xs">
            <span className="text-mute">Model win chance vs break-even</span>
            <span className="num">
              <span className="font-semibold text-slate-100">{pct(pWin, 1)}</span>
              <span className="mx-1 text-dim">vs</span>
              <span className="text-slate-300">{pct(breakeven, 0)}</span>
            </span>
          </div>
          <Meter value={pWin} marker={breakeven} tone={edge >= 0 ? '#3ddc97' : '#ff6b6b'} height={6} />
          <div className="mt-1.5 flex items-center justify-between text-[11px]">
            <span className="text-dim">White tick = break-even at this price</span>
            <span className={clsx('num font-medium', edge >= 0 ? 'text-mint' : 'text-coral')}>
              model edge {signedPct(edge, 1)} · exp. {money(expected, { sign: true })}
            </span>
          </div>
        </div>
      </div>

      {(overLimit || overCash || error) && (
        <div className="mt-3 rounded-lg border border-coral/25 bg-coral/10 px-3 py-2 text-[11.5px] text-coral">
          {error ??
            (overLimit
              ? `That is above your ${money(maxStake, { decimals: 0 })} per-trade limit.`
              : `Not enough cash — ${money(cash ?? 0)} available.`)}
        </div>
      )}

      <div className="mt-4 flex gap-2">
        <Button variant="ghost" size="md" onClick={onClose} className="flex-1">
          Cancel
        </Button>
        <Button
          variant={side === 'under' ? 'mint' : 'coral'}
          size="md"
          className="flex-[2]"
          loading={busy}
          disabled={contracts <= 0 || overLimit || overCash}
          onClick={submit}
        >
          {live ? 'Place live order' : 'Place paper order'} · {money(cost)}
        </Button>
      </div>
      <p className="mt-2.5 text-center text-[10.5px] leading-relaxed text-dim">
        Model numbers are estimates, not guarantees.{' '}
        {live ? 'This sends a real order to Kalshi.' : 'Paper mode: no real order is sent.'}
      </p>
    </Dialog>
  )
}
