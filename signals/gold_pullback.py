"""4-hour gold trend-pullback setup.

Long:  4H uptrend (EMA50 > EMA200, close > EMA200); within the last `look` bars price dipped to the EMA20 while
       RSI fell below `rsi_pull`; the trigger bar closes above the previous bar's high and above the EMA20.
Short: mirror image.
Entry next bar open. Stop beyond the recent 5-bar extreme (at least 1 ATR). Target = `r_target` x risk.
Time stop after `max_bars` bars (30 x 4h = 5 trading days).
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from gold_agent import indicators as ind


@dataclass
class PullbackParams:
    rsi_pull: float = 50.0
    look: int = 3
    r_target: float = 2.0
    max_bars: int = 30
    cost: float = 0.60  # spread + slippage per round trip, $/oz


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the flat weekend placeholder bars some feeds include for XAU/USD."""
    dow, hr = df.index.dayofweek, df.index.hour
    weekend = (dow == 5) | ((dow == 6) & (hr < 20))
    return df[~weekend]


def features(df: pd.DataFrame) -> pd.DataFrame:
    f = df.copy()
    f["ema20"], f["ema50"], f["ema200"] = (ind.ema(df["close"], n) for n in (20, 50, 200))
    f["rsi"] = ind.rsi(df["close"], 14)
    f["atr"] = ind.atr(df, 14)
    return f


def signals(f: pd.DataFrame, p: PullbackParams) -> pd.Series:
    """+1 long setup, -1 short setup, 0 none, evaluated on each completed bar."""
    up = (f.ema50 > f.ema200) & (f.close > f.ema200)
    dn = (f.ema50 < f.ema200) & (f.close < f.ema200)
    touch_lo = (f.low <= f.ema20).rolling(p.look).max().astype(bool)
    touch_hi = (f.high >= f.ema20).rolling(p.look).max().astype(bool)
    rsi_lo = f.rsi.rolling(p.look).min() < p.rsi_pull
    rsi_hi = f.rsi.rolling(p.look).max() > 100 - p.rsi_pull
    long_ = up & touch_lo & rsi_lo & (f.close > f.high.shift()) & (f.close > f.ema20)
    short = dn & touch_hi & rsi_hi & (f.close < f.low.shift()) & (f.close < f.ema20)
    return pd.Series(np.where(long_, 1, np.where(short, -1, 0)), index=f.index)


def levels(f: pd.DataFrame, i: int, side: int, entry: float, p: PullbackParams) -> tuple[float, float]:
    atr = f.atr.iloc[i]
    if side > 0:
        stop = min(f.low.iloc[i - 4: i + 1].min() - 0.2 * atr, entry - atr)
    else:
        stop = max(f.high.iloc[i - 4: i + 1].max() + 0.2 * atr, entry + atr)
    risk = abs(entry - stop)
    return stop, entry + side * p.r_target * risk


def backtest(df: pd.DataFrame, p: PullbackParams) -> pd.DataFrame:
    f = features(df)
    sig = signals(f, p)
    o, h, l, c = (f[k].to_numpy() for k in ("open", "high", "low", "close"))
    trades, i, n = [], 210, len(f)
    while i < n - 1:
        side = sig.iloc[i]
        if side == 0:
            i += 1
            continue
        e = i + 1
        entry = o[e]
        stop, target = levels(f, i, side, entry, p)
        risk = abs(entry - stop)
        exit_px, j, why = None, e, "time"
        for j in range(e, min(e + p.max_bars, n)):
            hit_stop = l[j] <= stop if side > 0 else h[j] >= stop
            hit_tgt = h[j] >= target if side > 0 else l[j] <= target
            if hit_stop:  # assume the worse outcome when both are touched in one bar
                exit_px = (min(o[j], stop) if side > 0 else max(o[j], stop)); why = "stop"; break
            if hit_tgt:
                exit_px = (max(o[j], target) if side > 0 else min(o[j], target)); why = "target"; break
        if exit_px is None:
            exit_px = c[j]
        pnl = side * (exit_px - entry) - p.cost
        trades.append({"signal_time": f.index[i], "entry_time": f.index[e], "exit_time": f.index[j], "side": side,
                       "entry": entry, "stop": stop, "target": target, "exit": exit_px, "why": why,
                       "R": pnl / risk, "risk": risk})
        i = j + 1  # one position at a time
    return pd.DataFrame(trades)


def summary(t: pd.DataFrame, weeks: float) -> dict:
    if t.empty:
        return {"trades": 0}
    r = t.R
    eq = r.cumsum()
    streak = max((len(g) for g in "".join("L" if x < 0 else "W" for x in r).split("W")), default=0)
    return {"trades": len(t), "per_week": round(len(t) / weeks, 2), "win_%": round((r > 0).mean() * 100, 1),
            "avg_R": round(r.mean(), 2), "total_R": round(r.sum(), 1),
            "PF": round(r[r > 0].sum() / -r[r < 0].sum(), 2) if (r < 0).any() else float("inf"),
            "max_DD_R": round((eq - eq.cummax()).min(), 1), "worst_streak": streak,
            "longs": int((t.side > 0).sum()), "shorts": int((t.side < 0).sum())}
