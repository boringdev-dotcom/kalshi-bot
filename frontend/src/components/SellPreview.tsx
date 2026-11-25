import { bookSide, count, planSell, useBook } from '../book'
import { cents, money } from '../format'

/** What selling a live bet would really do right now, from Kalshi's book: all of it, or only part. */
export function SellPreview({ ticker, side, contracts }: { ticker: string; side: string; contracts: number }) {
  const book = useBook(ticker)
  if (!book) return null
  const s = bookSide(side)
  const plan = planSell(contracts, book[s], book.floor[s])
  if (plan.sold <= 0) {
    return <p className="mt-3 text-[13px] leading-relaxed text-gold">Nobody on Kalshi is buying this right now, so a sale would not go through. Your bet stays open.</p>
  }
  if (plan.left > 0) {
    return (
      <p className="mt-3 text-[13px] leading-relaxed text-gold">
        Buyers on Kalshi only want {count(plan.sold)} of your {count(contracts)} right now (down to {cents(plan.lowest)}), for about {money(plan.proceeds)}. The
        other {count(plan.left)} would stay yours and stay open here, so you can sell them when more buyers show up.
      </p>
    )
  }
  return (
    <p className="mt-3 text-[13px] leading-relaxed text-dim">
      All {count(contracts)} sell now for about {money(plan.proceeds)}
      {plan.lowest != null && plan.avg != null && Math.round(plan.lowest) < Math.round(book[s][0][0])
        ? `, at about ${plan.avg.toFixed(1)}¢ each: the best buyer at ${cents(book[s][0][0])} does not want them all, so it goes down to ${cents(plan.lowest)}.`
        : '.'}
    </p>
  )
}

/** The toast after a sale you asked for. A part-sale is announced by the server, so it returns null. */
export function soldToast(t: { pnl: number; contracts: number; exit_price: number; left?: number }, what: string) {
  if (t.left) return null
  return {
    level: t.pnl >= 0 ? ('success' as const) : ('warn' as const),
    title: `Sold ${what}: ${money(t.pnl, { sign: true })}`,
    body: `${count(t.contracts)} sold at ${cents(t.exit_price)}.`,
  }
}
