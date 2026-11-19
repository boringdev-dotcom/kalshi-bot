# Courtside design guide

The bar: someone who has never traded a prediction market should be able to open a game, understand where the line is and what a bet pays, and place it, without reading documentation. The reference points are Robinhood and Kalshi: one idea per screen, plain words, big numbers, very little chrome.

## Principles

1. **One primary thing per screen.** A page has one headline number or one job. Everything else is secondary and looks it.
2. **Say it in words first.** "94% chance", "Pay $300, win $19", "Wins if the final total is under 250.5". Numbers without a sentence next to them are for people who already know what they mean.
3. **Show the line.** Any place a strike appears, the user should be able to see where it sits relative to the score now, the betting line and the projection.
4. **Progressive disclosure.** Model internals (edge, standard deviation, arm keys, exit profiles) live behind "Details" or on the Agent page's Learning tab, never in the main flow.
5. **Calm.** Flat surfaces, hairline dividers, generous spacing. Colour means something: green is up or a win, red is down or a loss, amber is caution. Nothing glows, nothing is decorated.

## Words

| Say | Not |
|---|---|
| chance | probability, p_under, model p |
| price (94¢) and what it pays | ask, no_ask |
| cushion ("10 points above the line") | buffer |
| the line | reference, FanDuel total_line |
| Practice mode / practice data | sim, simulated, paper (keep "Paper" only as the trading-mode badge) |
| Agent | bot, engine |
| Rules | playbook, strategy params |
| "The agent bought…", "passed on…", "sold…" | entered, skipped, exited |
| Under / Over, or `HOU -3.5` / `IND +3.5` (always from `yes_label` / `no_label` / `label`) | YES/NO, side |

Sentence case everywhere. No ALL-CAPS micro labels, no monospace numbers (numbers are Inter with tabular figures: use the `num` class).

## Look

- Page background `bg-ink-950`; cards `bg-ink-900` with `border-hair` and `rounded-xl2` (the `surface` class, or `<Card>`); inputs and selected rows `bg-ink-800`.
- Text: `text-white` for the thing that matters, `text-slate-200` body, `text-mute` secondary, `text-dim` tertiary.
- Type scale: page title `h-page` (26px semibold), section title `h-section` (16px semibold), body 14px, captions `label` / `hint` (12-13px). Hero numbers 36-44px semibold.
- Buttons are pills (`<Button>`): `primary` (white) for the one main action on a screen, `outline` or `ghost` for the rest, `mint` to confirm a buy, `coral` for destructive.
- Lists are rows, not grids of boxes: `row` + `row-hover` (hairline between, soft hover).
- Page column: wrap page content in `page` (max 1180px, centred).
- Green `mint`, red `coral`, amber `gold`. `peri` is reserved for the agent's own voice (its avatar dot, its chat bubbles) and used nowhere else.
- Motion: short fades and number ticks only. No pulsing except the single "live" dot.

## Structure

Top navigation bar (no side rail): **Markets · Portfolio · Agent · Settings**, with the Paper/Live badge, practice-data badge, buying power and the agent's state on the right.

| Route | Page | Job |
|---|---|---|
| `/` | Markets | Tonight's games as simple cards: score, clock, the line, the projection. Agent one-liner on top. |
| `/game/:id` | Game | Scoreboard, the line bar, chart, markets list (Game total / Q1-Q4, Total / Spread), sticky order panel on the right. |
| `/portfolio` | Portfolio | Big account value and chart, open positions as rows, history. |
| `/agent` | Agent | Tabs: Activity (what it did, in sentences, plus chat) · Rules · Memory · Learning. |
| `/settings` | Settings | Mode, data, limits, connections. |

`/brain` redirects to `/agent`.

## Phones

Every screen must work at 320px wide with no sideways scrolling (check with `document.documentElement.scrollWidth === innerWidth`).

- Below `md` (768px) the top navigation becomes a bottom tab bar; pages reserve room for it with `pb-tabbar`. Use `safe-bottom` on anything pinned to the bottom edge.
- Below `lg` (1024px) the game page's order panel is a bottom sheet that opens when a price is tapped; dialogs are bottom sheets below `sm`.
- Price buttons stack (name over price) on phones so two fit beside a strike.
- Rows of chips or tabs that can outgrow the screen scroll sideways inside a `no-scrollbar` container instead of widening the page. Grid and flex children that hold text get `min-w-0`.
- Touch targets are at least 44px tall; inputs are 16px so iOS does not zoom; nothing depends on hover.
