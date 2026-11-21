import { motion } from 'framer-motion'
import { ChevronRight } from 'lucide-react'
import type { FavsResult } from '../../api'
import { cents, pct, relTime } from '../../format'

/**
 * The agent's favourite bets on one game: picks it is 85-90% sure of that are still priced
 * below that. Shown inside the Agent card; tap a pick to load it in the order panel.
 */
export default function FavsView({
  result,
  busy,
  onPick,
}: {
  result: FavsResult | null
  busy: boolean
  onPick?: (ticker: string, side: string) => void
}) {
  if (!result) {
    return busy ? (
      <div aria-label="The agent is picking">
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="mb-2 h-14 rounded-xl bg-ink-800"
            animate={{ opacity: [0.35, 0.75, 0.35] }}
            transition={{ duration: 1.4, repeat: Infinity, delay: i * 0.2 }}
          />
        ))}
        <p className="text-xs text-dim">Checking every line and the game itself. Usually under a minute.</p>
      </div>
    ) : null
  }

  return (
    <div className={busy ? 'opacity-50 transition-opacity' : 'transition-opacity'}>
      {result.summary && <p className="text-[13px] leading-relaxed text-slate-300">{result.summary}</p>}
      {result.picks.length === 0 ? (
        <p className="mt-3 rounded-xl bg-ink-800 px-4 py-3 text-[13px] text-mute">Nothing fits 85–90% at a price that still pays right now.</p>
      ) : (
        <ul className="mt-3 divide-y divide-white/[0.06] overflow-hidden rounded-xl bg-ink-800">
          {result.picks.map((p) => (
            <li key={`${p.ticker}-${p.side}`}>
              <button
                onClick={() => onPick?.(p.ticker, p.side)}
                className="group flex w-full items-center gap-3 px-3.5 py-3 text-left transition-colors hover:bg-ink-700"
              >
                <span className="num flex h-10 w-12 shrink-0 items-center justify-center rounded-lg bg-gold/[0.12] text-[15px] font-semibold text-gold">
                  {pct(p.confidence)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline justify-between gap-3">
                    <span className="truncate text-[14px] font-semibold text-white">{p.label}</span>
                    <span className="num shrink-0 text-[13px] font-medium text-white">
                      {cents(p.ask)}
                      <span className="ml-1.5 text-mint">+{Math.round(p.edge * 100)}¢</span>
                    </span>
                  </span>
                  <span className="mt-0.5 block text-[13px] leading-snug text-slate-300">{p.reason}</span>
                  <span className="mt-0.5 block text-[11px] text-dim">
                    {p.where} · model {pct(p.model_p)}
                  </span>
                </span>
                <ChevronRight size={15} className="shrink-0 text-dim group-hover:text-white" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] leading-relaxed text-dim">
        Picked {relTime(result.generated_at)}. The % is the agent's confidence; +¢ is how far the price sits below it. Prices move, so tap a pick to see it live before buying.
      </p>
    </div>
  )
}
