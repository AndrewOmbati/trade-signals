# Trade signals: gold first, plus insider and congressional purchases

## Gold (XAU/USD)
Two setups, prices from Twelve Data:

| Setup | Timeframe | How often | Backtest |
|---|---|---|---|
| Trend breakout (`gold_agent`) | daily | ~5 a year | 2007-2026: 96 trades, 44% win, PF 1.67; since 2021 PF 2.1 |
| Trend pullback (`signals/gold_pullback.py`) | 4-hour | ~3 a month | Mar 2024-Nov 2026: 93 trades, 50% win, +0.27R avg, PF 1.58; out-of-sample PF 1.78 |

The pullback setup was tuned on the first 60% of history and checked on the last 40% (`research/gold_pullback_backtest.py`).
The same rules on 1-hour bars lost money, so they are not used. 2.7 years of 4H data is mostly a gold bull market.

- `python -m signals` — morning report: gold briefing (levels, signals, WATCH when near a trigger) then 5 stock signals
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
