import type { Caps, Pnl } from "../types";

function dollars(cents: number | undefined): string {
  if (cents === undefined || cents === null || Number.isNaN(cents)) return "—";
  return `${cents >= 0 ? "+" : "−"}$${(Math.abs(cents) / 100).toFixed(2)}`;
}

export function CapsBar({ caps, pnl }: { caps?: Caps | null; pnl?: Pnl | null }) {
  if (!caps) return null;
  return (
    <div className="caps-bar">
      <span>
        Match {caps.used_match}/{caps.per_match}
        <em> {caps.remaining_match} left</em>
      </span>
      <span>
        Day {caps.used_today}/{caps.per_day}
        <em> {caps.remaining_day} left</em>
      </span>
      <span className={pnl && (pnl.total_cents || 0) < 0 ? "loss" : ""}>
        P&amp;L {dollars(pnl?.total_cents)}
        <em> cap −${((caps.max_daily_loss_cents || 0) / 100).toFixed(2)}</em>
      </span>
    </div>
  );
}
