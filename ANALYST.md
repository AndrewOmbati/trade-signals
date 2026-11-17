# Daily analyst: method

You are producing the daily trade ideas for the owner of this repository. Gold (XAU/USD) is their priority.
Markets available: XAU/USD, EUR/USD, GBP/USD, USD/JPY, AUD/USD (all driven by the US dollar and the same news).

## 1. Gather
1. `python3 -m signals.market_context` writes `journal/context.json`: price, daily/4H/1H trend, RSI, ATR,
   previous-day and weekly highs/lows, 20-day range, recent 4H swing highs/lows, and for gold the status of the
   three **tested systems** (daily breakout, 4H pullback, London breakout). It takes 2-4 minutes (rate limits).
2. `python3 -m signals.journal grade` prints the track record of past ideas. Read it: if a grade or kind of idea
   keeps losing, be stricter with it today.
3. News (WebSearch, standard mode, several searches in one go):
   - today's economic calendar: high-impact US releases (CPI, PCE, NFP, jobless claims, retail sales, GDP, ISM),
     FOMC decisions/minutes, Fed speakers, and ECB/BoE/BoJ/RBA events for the currency pairs
   - what moved gold and the dollar in the last 24 hours (yields, Fed expectations, geopolitics, central-bank buying)
   Use only what you find; cite nothing you did not read. If search fails, say "news unavailable" and lean on charts.

## 2. Build ideas (at least 5, at least 2 on gold when it offers any sensible level)
Every idea needs a concrete level from `context.json`, not a feeling.
- **Tested systems first.** If a gold tested system has a live signal or London plan, include it with
  `basis` = `tested: daily breakout`, `tested: 4H pullback` or `tested: London breakout`, using its exact levels.
- **Discretionary ideas** (`basis` = `discretionary`): trade *with* the 4H/daily trend at a level: pullback to a
  broken level, prior-day or weekly high/low, 4H swing, or the 1H/4H EMAs. Counter-trend only at a major level
  (20-day / weekly extreme) with a news reason, and grade it C.
- Stops go beyond the level that proves the idea wrong (beyond the swing), never at an arbitrary distance.
  Targets at the next real level; reward:risk at least 1.5.
- If a high-impact release is due within the idea's window, say so in `catalyst` and prefer pending orders that
  only trigger after the move, or skip that market.
- **Grades:** A = trend-aligned + clear level + tested system or strong confluence (expect 0-2 a day).
  B = reasonable, trend-aligned. C = weak, counter-trend or filler to reach 5; say why in the thesis.
  Never inflate a grade to look useful. Five ideas are required; five *good* ideas are not guaranteed.

## 3. Record
Write a JSON list to `/tmp/ideas.json`; each item:
`{"symbol","side":"BUY|SELL","entry_type":"market|limit|stop","entry","stop","target","grade":"A|B|C",
"basis","thesis","invalidation","catalyst","expires_hours":24}`
Then `python3 -m signals.journal add /tmp/ideas.json`. If it prints REJECTED, fix the listed problems and retry.
Commit only `journal/ideas.jsonl` with message `Ideas for <date>` and push to `main`
(`git -c push.negotiate=true push`). If the push fails, continue and mention it at the end.

## 4. Notify
Push notification, gold first, one line per idea:
`1. XAU/USD SELL limit 3870 | SL 3900 | TP 3810 | A | tested: London breakout`
then one line with the track record summary, then "Ideas expire after 24h. Research, not financial advice."
Reply with the full ideas (including thesis, invalidation, catalyst) and the news you used, with links.
