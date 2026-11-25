# Handoff notes (read this first in a new chat)

Last updated: 25 Nov 2026. Background from earlier conversations that the code doesn't show.

## The owner
- Lives in **Kenya: give all times in Nairobi time (EAT, UTC+3, no daylight saving)**. Quote UTC only alongside EAT.
- Wants **gold (XAU/USD) only**. The FX pairs were dropped on 18 Nov 2026 (code, `ANALYST.md` and the daily task).
- Sizing rule discussed: risk **1% of the account per trade** (the daily system's own setting). Example: $10,000
  account, stop $265/oz away -> about 0.38 oz.
- Prefers plain answers: what to do, at what level, and why. Every reply ends with "Research, not financial advice."

## Position and plan (as of 25 Nov 2026, evening)
- The owner is **not in any trade**. They did not take the 19 Nov daily-breakout SELL.
- They are waiting for the **daily-breakout SELL** signal: a daily close (00:00 UTC = 03:00 EAT) below the 20-day
  low, **3504.02** for the 25 Nov close. Daily RSI was about 29, above the 25 "oversold" cut-off, so a close
  below 3504.02 should give a real signal. If it fires: sell at market when the brief arrives, using the system's
  stop (2.5x daily ATR, about $265/oz) and target (5x ATR).
- In the system's own books the 19 Nov SELL (entry 3735.06) is still open: it exits on a daily close above the
  10-day high (4066.53 on 25 Nov, falling fast). The signal check is stateless, so a new signal is still reported.

## Daily brief
- Scheduled task **"Daily gold analyst"**: weekdays **10:10 EAT**. It starts a **fresh session each run**, follows
  `ANALYST.md`, records ideas in `journal/ideas.jsonl`, pushes to `main` and sends a phone notification.
- 10:10 EAT is deliberate: it is after the 03:00 EAT daily close and after the London-breakout overnight range,
  which ends at 07:00 London time (10:00 EAT in winter).
- The old task ("Daily gold analyst (old, replaced)") is **disabled**. It fired into one long chat and **missed
  20-25 Nov** because that chat sat idle. No ideas exist for 20, 23 or 24 Nov.
- The first run of the new task is Thu 26 Nov. It is untested: if no notification arrives by 10:30 EAT,
  check by hand (`python3 -m signals.market_context`, then the `tested_systems` lines in `journal/context.json`).

## What has been tested
- Working setups and their backtests: see the table in `README.md` (daily breakout, 4H pullback, London breakout).
- **Rejected 25 Nov 2026: prior-day breakout/breakdown** (`research/gold_breakdown_backtest.py`). Strong
  2023-26 (a gold bull market, mostly longs) but break-even on daily data since 2007, and shorts lost (-0.09R avg,
  219 trades). Don't add it to the daily method without new evidence.
- Lesson from 17-25 Nov: in a fast fall, discretionary **sell-the-bounce limit orders mostly never filled**
  (4 of 6 expired). The tested daily breakout caught the move instead.

## Track record (journal, gold only)
- As of 25 Nov: 2 closed (one win +1.5R, one timed out +0.54R), 4 never filled. 8 old FX ideas are kept but
  not counted. Run `python3 -m signals.journal grade` for the current numbers (run `market_context` first; it
  writes the price cache the grader reads).
