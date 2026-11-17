"""Chart context for the daily analyst: trend, momentum, volatility and key levels per market, plus the tested
gold systems' current status. Prints JSON (for the analyst) and caches the 1H bars for the idea grader."""
import json
import sys
import time

import pandas as pd

from gold_agent import indicators as ind

from . import gold
from .gold_pullback import clean

SYMBOLS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]
CACHE = "journal/.h1_cache.json"  # scratch, not committed


def _get(symbol: str, interval: str, n: int) -> pd.DataFrame:
    for attempt in range(3):
        try:
            return clean(gold._fetch_symbol(symbol, interval, n))
        except RuntimeError as e:
            if "credits" in str(e).lower() or "limit" in str(e).lower():
                time.sleep(62)  # free plan: 8 requests/minute
                continue
            raise
    raise RuntimeError(f"{symbol} {interval}: rate limited")


def swings(df: pd.DataFrame, k: int = 2, last: int = 60) -> tuple[list[float], list[float]]:
    """Recent swing highs/lows (fractals: higher/lower than k bars on each side)."""
    d = df.iloc[-last:]
    hs = [d.high.iloc[i] for i in range(k, len(d) - k) if d.high.iloc[i] == d.high.iloc[i - k:i + k + 1].max()]
    ls = [d.low.iloc[i] for i in range(k, len(d) - k) if d.low.iloc[i] == d.low.iloc[i - k:i + k + 1].min()]
    return hs[-4:], ls[-4:]


def describe(symbol: str, d1: pd.DataFrame, h4: pd.DataFrame, h1: pd.DataFrame) -> dict:
    dp = 2 if symbol.startswith("XAU") or "JPY" in symbol else 5
    r = lambda x: round(float(x), dp)
    c = d1.close
    e50, e200 = ind.ema(c, 50).iloc[-1], ind.ema(c, 200).iloc[-1]
    h4c = h4.close
    h4e50, h4e200 = ind.ema(h4c, 50).iloc[-1], ind.ema(h4c, 200).iloc[-1]
    sh, sl = swings(h4)
    price = float(h1.close.iloc[-1])
    prev = d1.iloc[-1]
    return {
        "symbol": symbol, "price": r(price), "as_of_utc": str(h1.index[-1]),
        "daily": {"trend": "UP" if e50 > e200 else "DOWN", "ema50": r(e50), "ema200": r(e200),
                  "rsi14": round(float(ind.rsi(c, 14).iloc[-1]), 1), "atr14": r(ind.atr(d1, 14).iloc[-1]),
                  "prev_day": {"high": r(prev.high), "low": r(prev.low), "close": r(prev.close)},
                  "week_high": r(d1.high.iloc[-5:].max()), "week_low": r(d1.low.iloc[-5:].min()),
                  "20d_high": r(d1.high.iloc[-20:].max()), "20d_low": r(d1.low.iloc[-20:].min()),
                  "change_5d_pct": round(float(c.iloc[-1] / c.iloc[-6] - 1) * 100, 2)},
        "h4": {"trend": "UP" if h4e50 > h4e200 and h4c.iloc[-1] > h4e200 else "DOWN" if h4e50 < h4e200 and h4c.iloc[-1] < h4e200 else "MIXED",
               "ema50": r(h4e50), "ema200": r(h4e200), "rsi14": round(float(ind.rsi(h4c, 14).iloc[-1]), 1),
               "atr14": r(ind.atr(h4, 14).iloc[-1]), "swing_highs": [r(x) for x in sh], "swing_lows": [r(x) for x in sl]},
        "h1": {"ema20": r(ind.ema(h1.close, 20).iloc[-1]), "ema50": r(ind.ema(h1.close, 50).iloc[-1]),
               "rsi14": round(float(ind.rsi(h1.close, 14).iloc[-1]), 1),
               "last_24h_high": r(h1.high.iloc[-24:].max()), "last_24h_low": r(h1.low.iloc[-24:].min())},
    }


def main() -> int:
    out, cache = {"generated_utc": str(pd.Timestamp.now(tz="UTC")), "markets": [], "errors": []}, {}
    for sym in SYMBOLS:
        try:
            d1 = _get(sym, "1day", 300)
            d1 = d1[d1.index.date < pd.Timestamp.now(tz="UTC").date()]  # completed days only
            h4 = _get(sym, "4h", 400)
            h1 = _get(sym, "1h", 500)
            info = describe(sym, d1, h4, h1)
            if sym == "XAU/USD":
                from .gold_setups import london_today
                info["tested_systems"] = gold.briefing(d1, h4.iloc[:-1]) + (london_today(h1) or ["London breakout: no plan today"])
            out["markets"].append(info)
            cache[sym] = {**{k: h1[k].tolist() for k in ("open", "high", "low", "close")}, "index": [str(t) for t in h1.index]}
        except Exception as e:  # keep going with the other markets
            out["errors"].append(f"{sym}: {e}")
    with open(CACHE, "w") as fh:
        json.dump(cache, fh)
    text = json.dumps(out, indent=1, default=str)
    with open("journal/context.json", "w") as fh:
        fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
