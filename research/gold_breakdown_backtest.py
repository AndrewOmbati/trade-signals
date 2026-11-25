"""Trend breakdown (prior-day breakout) for gold: in a daily downtrend, SELL STOP just below the previous day's low;
in an uptrend, BUY STOP just above the previous day's high. Order lives for one UTC day.

    python research/gold_breakdown_backtest.py h1.csv d1.csv

1H bars resolve the intraday path (stop checked before target, the fill bar can only stop out).
Settings are chosen on the first 60% of the 1H history and then run unchanged on the last 40%, then on daily bars
since 2007 (coarser: on the entry day only the stop can be hit, so it is pessimistic). R = profit / initial risk,
after $0.60/oz costs.

Result (Nov 2026): REJECTED. Every 1H setting was profitable 2023-2026, but that window is almost all gold bull market
(135 of 149 trades long). On daily bars, which give nearly the same result as 1H over the same years, the chosen
setting is break-even since 2007 (790 trades, PF 1.02, worst drawdown -51R) and lost in 2007-12, 2013-18 and
2019-23. Shorts lost over the full history (219 trades, -0.09R avg).
"""
import itertools
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from gold_agent import indicators as ind  # noqa: E402
from signals.gold_pullback import clean, summary  # noqa: E402


@dataclass
class P:
    trend: str = "both"      # "ema50": prior close vs 50-day EMA; "both": also 50-day vs 200-day EMA
    stop: str = "pdh"        # "pdh": beyond the previous day's opposite extreme; "atr": 1 daily ATR from entry
    r: float = 2.0           # target in R
    hold: int = 3            # max days in the trade (exit at the close of the last day)
    buffer: float = 0.05     # entry this many daily ATRs beyond the prior-day extreme
    cost: float = 0.60
    sides: str = "both"      # "both", "short", "long"


def daily_from(h1: pd.DataFrame) -> pd.DataFrame:
    d = h1.groupby(h1.index.normalize()).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                             close=("close", "last"))
    return d[d.index.dayofweek < 5]


def plans(d: pd.DataFrame, p: P) -> pd.DataFrame:
    """Per day: the pending order built from the previous completed day (no look-ahead)."""
    prev = pd.DataFrame({"hi": d.high, "lo": d.low, "c": d.close, "atr": ind.atr(d, 14),
                         "e50": ind.ema(d.close, 50), "e200": ind.ema(d.close, 200)}).shift()
    dn = prev.c < prev.e50
    up = prev.c > prev.e50
    if p.trend == "both":
        dn &= prev.e50 < prev.e200
        up &= prev.e50 > prev.e200
    side = np.where(dn, -1, np.where(up, 1, 0))
    if p.sides == "short":
        side = np.where(side < 0, -1, 0)
    elif p.sides == "long":
        side = np.where(side > 0, 1, 0)
    entry = np.where(side < 0, prev.lo - p.buffer * prev.atr, prev.hi + p.buffer * prev.atr)
    if p.stop == "pdh":
        stop = np.where(side < 0, prev.hi, prev.lo)
    else:
        stop = entry - side * prev.atr
    out = pd.DataFrame({"side": side, "entry": entry, "stop": stop, "atr": prev.atr}, index=d.index)
    return out[(out.side != 0) & prev.e200.notna()]


def run(bars: pd.DataFrame, d: pd.DataFrame, p: P) -> pd.DataFrame:
    """bars: the path (1H or daily). Days in `d` define the order windows."""
    pl = plans(d, p)
    day_of = bars.index.normalize()
    o, h, l, c = (bars[k].to_numpy() for k in ("open", "high", "low", "close"))
    days = list(d.index)
    pos = {dd: i for i, dd in enumerate(days)}
    trades, busy_until = [], None
    for dd, row in pl.iterrows():
        if busy_until is not None and dd <= busy_until:
            continue
        idx = np.flatnonzero(day_of == dd)
        if not len(idx):
            continue
        s, e0, st = int(row.side), row.entry, row.stop
        fill = None
        for i in idx:
            if (l[i] <= e0) if s < 0 else (h[i] >= e0):
                fill = i
                entry = min(o[i], e0) if s < 0 else max(o[i], e0)
                break
        if fill is None:
            continue
        risk = abs(entry - st)
        if s * (entry - st) <= 0 or risk < 0.2 * row.atr:
            continue  # gapped through the stop, or a stop too tight to be real
        tgt = entry + s * p.r * risk
        last_day = days[min(pos[dd] + p.hold - 1, len(days) - 1)]
        end = np.flatnonzero(day_of <= last_day)[-1]
        exit_px, why, j = c[end], "time", end
        for j in range(fill, end + 1):
            if (h[j] >= st) if s < 0 else (l[j] <= st):
                exit_px, why = (max(o[j], st) if s < 0 else min(o[j], st)) if j > fill else st, "stop"
                break
            if j > fill and ((l[j] <= tgt) if s < 0 else (h[j] >= tgt)):
                exit_px, why = (min(o[j], tgt) if s < 0 else max(o[j], tgt)), "target"
                break
        else:
            j = end
        trades.append({"signal_time": bars.index[fill], "exit_time": bars.index[j], "side": s, "entry": entry,
                       "stop": st, "target": tgt, "exit": exit_px, "why": why, "risk": risk,
                       "R": (s * (exit_px - entry) - p.cost) / risk})
        busy_until = bars.index[j].normalize()
    return pd.DataFrame(trades)


def stats(t: pd.DataFrame, t0, t1) -> dict:
    s = summary(t, max((t1 - t0).days / 7, 1))
    return {k: s.get(k) for k in ("trades", "per_week", "win_%", "avg_R", "total_R", "PF", "max_DD_R", "worst_streak",
                                  "longs", "shorts")}


if __name__ == "__main__":
    h1 = clean(pd.read_csv(sys.argv[1], index_col=0, parse_dates=True))
    d1 = pd.read_csv(sys.argv[2], index_col=0, parse_dates=True)
    d1 = d1[(d1.index.dayofweek < 5) & (d1.index >= "2006-01-01")]
    dh = daily_from(h1)
    cut = dh.index[int(len(dh) * 0.6)]
    print(f"1H: {h1.index[0]:%Y-%m-%d} .. {h1.index[-1]:%Y-%m-%d}; tune before {cut:%Y-%m-%d}, test after")
    print(f"gold {dh.close.iloc[200]:.0f} -> {dh.close[cut]:.0f} -> {dh.close.iloc[-1]:.0f}\n")

    rows = []
    for tr, stp, r, hold in itertools.product(["ema50", "both"], ["pdh", "atr"], [1.5, 2.0, 3.0], [1, 3, 5]):
        p = P(trend=tr, stop=stp, r=r, hold=hold)
        t = run(h1, dh, p)
        i, o = t[t.signal_time < cut], t[t.signal_time >= cut]
        si, so = stats(i, dh.index[200], cut), stats(o, cut, dh.index[-1])
        rows.append({"trend": tr, "stop": stp, "r": r, "hold": hold, "n_in": si["trades"], "avgR_in": si["avg_R"],
                     "PF_in": si["PF"], "n_out": so["trades"], "avgR_out": so["avg_R"], "PF_out": so["PF"]})
    g = pd.DataFrame(rows)
    print("GRID (in-sample = tuning period; out-of-sample shown for reference, not used to choose)")
    print(g.sort_values("avgR_in", ascending=False).to_string(index=False))
    print(f"\nout-of-sample: {(g.avgR_out > 0).sum()} of {len(g)} settings positive; "
          f"median PF {g.PF_out.median():.2f}")

    best = g.sort_values("avgR_in", ascending=False).iloc[0]
    p = P(trend=best.trend, stop=best.stop, r=best.r, hold=int(best.hold))
    print(f"\nCHOSEN on in-sample only: {p}")
    t = run(h1, dh, p)
    o = t[t.signal_time >= cut]
    print("  1H out-of-sample:", stats(o, cut, dh.index[-1]))
    print(o.groupby("side").R.agg(["count", "mean", "sum"]).round(2).to_string())
    for sd in ("short", "long"):
        q = P(**{**p.__dict__, "sides": sd})
        print(f"  1H full period, {sd}s only:", stats(run(h1, dh, q), dh.index[200], dh.index[-1]))
    for k in (1.0, 2.5):
        q = P(**{**p.__dict__, "cost": 0.60 * k})
        print(f"  1H out-of-sample at {k}x costs:", stats(run(h1, dh, q).query("signal_time >= @cut"), cut, dh.index[-1]))
    td = run(d1, d1, p)
    print("\nDAILY BARS 2007-2026 (pessimistic path):", stats(td, d1.index[200], d1.index[-1]))
    td["year"] = td.signal_time.dt.year
    print(td.groupby("year").R.agg(["count", "sum"]).round(1).T.to_string())
    print("\nlast 10 trades (1H):")
    print(t.tail(10)[["signal_time", "side", "entry", "stop", "target", "exit", "why", "R"]].to_string(index=False))
