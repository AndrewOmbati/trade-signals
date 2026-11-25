# Trade signals: gold first, plus insider and congressional purchases

## Gold (XAU/USD)
Two setups, prices from Twelve Data:

| Setup | Timeframe | How often | Backtest |
|---|---|---|---|
| Trend breakout (`gold_agent`) | daily | ~5 a year | 2007-2026: 96 trades, 44% win, PF 1.67; since 2021 PF 2.1 |
| Trend pullback (`signals/gold_pullback.py`) | 4-hour | ~3 a month | Mar 2024-Nov 2026: 93 trades, 50% win, +0.27R avg, PF 1.58; out-of-sample PF 1.78 |
| London open breakout, with daily trend (`signals/gold_setups.py`) | 1-hour | ~4-5 a month | Mar 2024-Nov 2026: 166 trades, 52% win, +0.14R avg, PF 1.38; out-of-sample PF 1.36; still PF 1.22 at 2.5x costs |

Rejected after testing: 4H range fade (lost in every variant), London breakout without the trend filter (break-even),
4H pullback on 1-hour bars (lost),
prior-day breakout/breakdown with the daily trend (`research/gold_breakdown_backtest.py`: strong 2024-26 but
break-even since 2007, and shorts lost).

The pullback setup was tuned on the first 60% of history and checked on the last 40% (`research/gold_pullback_backtest.py`).
The same rules on 1-hour bars lost money, so they are not used. 2.7 years of 4H data is mostly a gold bull market.

- `python -m signals` — morning report: gold briefing (levels, signals, WATCH when near a trigger) then 5 stock signals
- `python -m signals.gold_london` — 07:05 London: today's breakout pending orders, if the day qualifies
- `python -m signals.gold_watch` — 4-hourly check: alerts only on a new 4H setup or when gold moves near a daily trigger

# Insider and congressional purchases

Daily report of the top 5 setups from:
- **SEC Form 4**: open-market purchases by company insiders (filed within 2 business days of the trade)
- **US House periodic transaction reports**: stock purchases by members of Congress (disclosed up to 45 days late)

Gold-related tickers (bullion ETFs and miners) are flagged separately.

Ranking favours several people buying the same stock, larger purchases, CEO/CFO buyers, meaningful stake increases
and recent trades. Sells are ignored except as a penalty. Each signal is graded STRONG / MODERATE / WEAK;
the top 5 are always shown, even on days with no strong setups.

```bash
pip install requests          # also needs pdftotext (poppler-utils)
export SEC_CONTACT=you@example.com   # required by the SEC's fair-access policy
python -m signals                    # text report
python -m signals --json
python -m pytest tests
```

Research leads, not financial advice.
