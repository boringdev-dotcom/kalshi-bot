# Phase 0 pattern report — Kalshi soccer totals

Reverse-engineered from live Kalshi portfolio history (fills, orders, settlements) matched to FotMob/ESPN scorelines. Import draft: [`internal/import_history.py`](../internal/import_history.py).

Pulled 2026-09-21 using Cloud Agent secrets `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_PEM` against production `https://api.elections.kalshi.com`. Demo host rejected the key (`NOT_FOUND`).

## What was collected

| Source | Count |
| --- | ---: |
| Live fills | 1,185 |
| Historical fills (before cutoff 2026-07-22) | 1,259 |
| Fills after de-dupe | 2,444 |
| Live + historical orders (de-duped) | 1,265 |
| Settlements (all sports) | 332 |
| Soccer-total fills | **1,240** |
| Soccer-total orders | 485 |
| Soccer-total settlements | 280 |
| Distinct soccer-total markets | 376 |
| Distinct matches (home/away/kickoff) | 317 |
| Fill date range | 2025-11-30 → 2026-09-20 |

Signing note: portfolio and historical GETs must be signed against the **path only**. Including `?limit=` in the RSA-PSS message returns `INCORRECT_API_KEY_SIGNATURE`. Balance worked either way; fills/orders/settlements do not.

Soccer-total filter: ticker contains `TOTAL` and is not NBA/WNBA/NFL/NHL/MLB. That includes 1H totals (`KXSERIEA1HTOTAL`, `KXEPL1HTOTAL`, …) — 12 fills, 3 settled markets.

Account snapshot at pull: about **$2,367.66** cash, no open soccer positions.

## Scoreline match

State at each fill: soccer minute, score, `rem = strike_n − goals_so_far`, No price, league.

- Strike: ticker suffix `N` is **Over (N − 0.5)**. `rem` is the integer goals still needed to go over (Over 3.5 → `strike_n = 4`).
- Kickoff and goal minutes: FotMob `/api/data/matches?date=` + `/api/data/matchDetails?matchId=`. ESPN `site.web.api.espn.com` as fallback (`site.api.espn.com` is 403 from this environment).
- Minute uses FotMob `firstHalfStarted` / `secondHalfStarted` when present, else kickoff + 15-minute half-time.

| Fixture match | Markets |
| --- | ---: |
| FotMob | 320 / 376 |
| ESPN fallback | 8 / 376 |
| Unmatched | 48 / 376 |
| Buy-No fills with a scoreline | **574 / 643 (89%)** |

Unmatched series are mostly Liga MX, older Bundesliga, Club Friendlies, UCL, and Libertadores — name/abbrev misses, not API outages.

Worked example (Milan vs Lecce, 2026-09-20, 1H Over 2.5):

- Fill 19:03:30Z, kickoff 18:45Z, Pulisic 14'
- State: **minute 15.7, 1–0, rem 2, No 75¢**, 131.04 contracts
- Settled No (1H finished 1–0). Official P&L **+$31.04** after $1.72 fees.

## Entry distribution (buy-No)

643 buy-No fills. Side mix on soccer totals: buy-No 643, sell-No 314, buy-Yes 167, sell-Yes 116.

Median buy-No: **minute 45, rem 3, No 87¢, 52 contracts**. Mean size is 232 because of 1,000–2,200 contract clips.

### Minute (574 matched buy-No)

| Bucket | Fills |
| --- | ---: |
| Pre-kick | 48 |
| 00–44 (1H) | 134 |
| 45–59 (HT window) | 250 |
| 60–69 | 61 |
| 70–79 | 64 |
| 80–89 | 6 |
| Post-FT / parse error (`minute > 120`) | 11 |

Phase: 2H 268, 1H 153, HT 105, pre-kick 48. The live bot is **not** waiting until rem is dead. Half-time is the mode.

### rem at fill (matched buy-No)

| rem | Fills |
| --- | ---: |
| ≤ 0 (already over) | 9 |
| 1 | 39 |
| 2 | 146 |
| 3 | 189 |
| ≥ 4 | 191 |

Typical board: Over 3.5 / 4.5 / 5.5 with 0–1 goals at HT → rem 3–5.

### No price (all buy-No)

| No price | Fills |
| --- | ---: |
| < 70¢ | 118 |
| 70–79¢ | 98 |
| 80–84¢ | 70 |
| 85–89¢ | 108 |
| 90–94¢ | 185 |
| 95–100¢ | 64 |

p10 / p50 / p90 = 54¢ / 87¢ / 94¢.

### Size

| | Contracts |
| --- | ---: |
| p10 | 5.6 |
| p25 | 12 |
| p50 | 52 |
| p75 | 250 |
| p90 | 725 |
| max | 2,207 |
| sum (all buy-No) | 149,487 |

Tier 1 median clip 103; tier 2/3 median ~27–29. The fat tail is top-flight and a few whale tier-2/3 shots (UWCL 3,106, Peru 2,328).

### League / tier (buy-No fills)

| Tier | Fills | Median size |
| --- | ---: | ---: |
| 1 (EPL, La Liga, Serie A, Bundesliga, Ligue 1, UCL, WC) | 251 | 103 |
| 2 (MLS, UEL, Liga MX, cups, CWC/friendlies, …) | 292 | 27 |
| 3 (NWSL, UWCL, Peru, Denmark, lower leagues) | 100 | 29 |

Most traded series: Club Friendlies/CWC 129, La Liga 66, EPL 62, Serie A 49, MLS 37.

## Exit triggers

Same-ticker FIFO pairing: **639 hold-to-settlement**, 3 price flattens, 1 goal flatten.

Sell-No / buy-Yes are common (481 fills) but almost always on **another strike** (ladder/spread), not a close of the same contract. Only **4** markets have buy-No plus a same-ticker flatten.

So the historical playbook is: **buy No, hold to settlement**, optionally hedge by selling Yes / buying Yes on a nearby line (52 settled markets held a complete yes+no set).

## Realized P&L

Two numbers. Do not mix them.

### Official restated settlement (use this)

Kalshi `revenue` is winning-contract payout in cents. When `yes_count == no_count`, that is a **complete set** that redeems $1/pair and `revenue` is 0. Naive `revenue − costs` marks those 52 hedges as ~−$1×size losses.

Restated: `revenue/100 + min(yes,no) − no_cost − yes_cost − fee`.

| | |
| --- | ---: |
| Settled soccer-total markets | 280 |
| Restated P&L | **−$2,212** |
| Wins / losses | 230 / 50 (82% win rate) |
| Under hits (`result=no`) | 260 markets, **+$8,362** (avg +$32) |
| Over hits (`result=yes`) | 20 markets, **−$10,574** (avg −$529) |

This is the classic under-No payoff: many small wins, few large wipeouts. Size on the losers dominates.

Fill-cashflow without pair redemption printed **+$32k** on the first script pass. That overstates (double-counts sell-Yes premium and misses pair redemption). Ignore it.

### Restated P&L by entry state (settled markets)

Weighted by first/size-averaged buy-No on that ticker.

**Minute** (matched):

| Bucket | n | Win % | P&L | Avg |
| --- | ---: | ---: | ---: | ---: |
| 00–44 | 28 | 75% | +182 | +7 |
| 45–59 HT | 119 | 83% | **−4,570** | −38 |
| 60–69 | 53 | 89% | +718 | +14 |
| 70–79 | 23 | 74% | +305 | +13 |
| 80–89 | 6 | 100% | +129 | +22 |
| 90+ | 15 | 93% | +339 | +23 |

HT is where the money was lost despite a high win rate. After minute 60 the same strategy is profitable in this sample.

**rem:**

| rem | n | Win % | P&L |
| --- | ---: | ---: | ---: |
| ≤ 1 | 3 | 33% | −22 |
| 2 | 24 | 62% | +165 |
| 3 | 72 | 72% | **−5,206** |
| ≥ 4 | 152 | 92% | +2,274 |

`rem ≥ 4` wins often (high line, low score). `rem = 3` is the hole — HT entries on Over 3.5 with one goal already in.

**No price:**

| No ¢ | n | Win % | P&L |
| --- | ---: | ---: | ---: |
| < 70 | 11 | 55% | +19 |
| 70–79 | 14 | 50% | −98 |
| 80–84 | 16 | 81% | **+1,356** |
| 85–89 | 41 | 56% | −1,712 |
| 90–94 | 103 | 88% | +491 |
| 95+ | 95 | 95% | −2,267 |

80–84¢ is the only clearly +EV price band. 95¢+ still dies when the 5% miss is a 2,000-contract clip.

**Tier:** tier 1 about flat (+$29), tier 2 +$3,194, tier 3 **−$5,434** (UWCL −$3,000, Peru −$1,778, Venezuela −$987).

**Size:** 1,000+ contract markets −$1,932. 50–399 contract markets modestly green.

**In-sample slice that matches the intended Grok bot** (matched, FT, minute ≥ 60, rem ≤ 3, No 80–94¢, tier 1–2): **31 markets, 28 wins, +$1,406**. Tiny, but the only region that is both frequent enough and green.

Largest single restated loss: `KXUCLWTOTAL-26AUG07SERAKT-4` (UWCL Over 3.5) −$2,999.90 on 3,105.66 No @ ~96¢, market result Yes.

## Proposed playbook (seed for Phase 4)

Tighten versus the historical median (HT / rem 3 / 87¢ / 52–250). History’s median is high-hit-rate and **negative** after wipeouts.

| Rule | Proposed | Why |
| --- | --- | --- |
| Side | Buy No only | 643/643 directed under-No |
| Minute | **60–92** | HT bucket −$4.6k; 60+ green |
| rem | **≤ 2** (allow 3 only on Over ≥ 4.5 in tier 1) | rem=3 is the loss hole |
| No ask | **80–92¢** | 80–84¢ best; skip <70 and ≥95 |
| Flatten on goal | Yes | Almost never done historically; would have cut rem=3 HT blowups |
| Flatten if rem drops to 1 | Yes | Same |
| Price stop | Flatten if No falls **12¢** | Protects the 80–92¢ band |
| No re-entry after stop | Yes |  |
| Max contracts / match | **150** (hard 250) | p75 was 250; 1,000+ clips drove the left tail |
| Max contracts / day | **600** |  |
| Leagues | Tier 1–2 only | Tier 3 −$5.4k |
| 1H totals | Off until more sample | 3 settled markets, −$394 |
| Paper mode | Default on |  |

Do **not** copy the historical HT / rem≥3 / 95¢ / 2,000-contract habit into the new watcher. That is what the Grok bots actually did; it is not what the P&L supports.

## Gaps

1. **48 / 376 markets unmatched** (69 buy-No fills). Worst: Liga MX, Bundesliga (older dates), Club Friendlies, UCL, Libertadores. Need a better abbrev table and FotMob search fallback.
2. **11 fills with `minute > 120`** — half-start timezone parse errors or post-FT prints. Treated as `postFT/parse_err`, not used for thresholds.
3. **Same-ticker flatten sample is ~4 markets.** Exit-trigger stats cannot reverse-engineer a stop rule from history; the stop above is proposed, not observed.
4. **Complete-set hedges** (52 markets) need the pair-redemption adjustment. Raw Kalshi `revenue` understates those P&Ls by about $1×pair.
5. **Fill-cashflow P&L (+$32k first pass)** is not trustworthy. Use restated settlement.
6. **1H totals** are 12 fills. Do not tune a separate 1H book yet.
7. **`site.api.espn.com` is 403** here; ESPN only via `site.web.api.espn.com`.
8. Kalshi `get_markets` in `src/kalshi_api.py` signs the query string (works for public markets). Portfolio endpoints do not. The import client signs path-only and does not change repo source.
9. Historical market endpoint 404’d for recent finalized tickers; live `/markets/{ticker}` still returned them. Older settled markets may thin out as the cutoff advances.
10. No Discord. Telegram unused in this phase.

## How to re-run

```bash
PYTHONPATH=/path/to/kalshi-bot \
  python internal/import_history.py --out-dir /tmp/kalshi_phase0_out
```

Requires `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_PEM`. `--skip-pull` / `--skip-match` reuse `raw.json` / `enriched.json`.
