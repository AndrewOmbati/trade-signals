"""Two more gold setups (research): London-open breakout (1H) and range fade (4H). R = profit / initial risk."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from gold_agent import indicators as ind


# ---------------------------------------------------------------- London open breakout (1H bars)
# Research result (research/gold_setups2_backtest.py): only the trend-filtered version has an edge.
@dataclass
class LondonParams:
    min_w: float = 0.15       # Asian range width, as a fraction of daily ATR
    max_w: float = 0.50
    buffer: float = 0.05      # entry this many ATRs beyond the range
    r_target: float = 2.0
    trend: bool = True        # only trade in the direction of the daily trend (prior close vs 50-day EMA)
    cost: float = 0.60


def london_context(h1: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """1H bars in London time plus yesterday's daily ATR / 50-day EMA / close, indexed by London date."""
    df = h1.tz_convert("Europe/London")
    day = df.index.normalize()
    daily = df.groupby(day).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
    daily = daily[daily.index.dayofweek < 5]
    return df, ind.atr(daily, 14).shift(), ind.ema(daily["close"], 50).shift(), daily["close"].shift()


def london_plan(g: pd.DataFrame, d: pd.Timestamp, datr, dema, dclose, p: LondonParams) -> dict | None:
    """Pending orders for London date `d`, from its 00:00-07:00 bars. None if the day doesn't qualify."""
    if d.dayofweek >= 5 or d not in datr.index or np.isnan(datr[d]) or np.isnan(dema[d]):
        return None
    asia = g[g.index.hour < 7]
    if len(asia) < 5:
        return None
    hi, lo, atr = asia.high.max(), asia.low.min(), datr[d]
    w = hi - lo
    if not (p.min_w * atr <= w <= p.max_w * atr):
        return {"skip": f"overnight range ${w:,.0f} is {'too narrow' if w < p.min_w * atr else 'too wide'} "
                        f"vs daily range ~${atr:,.0f}", "hi": hi, "lo": lo}
    up_ok = not p.trend or dclose[d] > dema[d]
    dn_ok = not p.trend or dclose[d] < dema[d]
    plan = {"hi": hi, "lo": lo, "atr": atr, "orders": []}
    if up_ok:
        e = hi + p.buffer * atr
        plan["orders"].append({"side": 1, "entry": e, "stop": lo, "target": e + p.r_target * (e - lo)})
    if dn_ok:
        e = lo - p.buffer * atr
        plan["orders"].append({"side": -1, "entry": e, "stop": hi, "target": e - p.r_target * (hi - e)})
    return plan


def london_backtest(h1: pd.DataFrame, p: LondonParams) -> pd.DataFrame:
    df, datr, dema, dclose = london_context(h1)
    trades = []
    for d, g in df.groupby(df.index.normalize()):
        plan = london_plan(g, d, datr, dema, dclose, p)
        if not plan or "skip" in plan:
            continue
        sess = g[(g.index.hour >= 7) & (g.index.hour < 20)]
        if sess.empty:
            continue
        orders = {o["side"]: o for o in plan["orders"]}
        side = entry = None
        for t, b in sess[sess.index.hour < 12].iterrows():
            hit_l = 1 in orders and b.high >= orders[1]["entry"]
            hit_s = -1 in orders and b.low <= orders[-1]["entry"]
            if hit_l and hit_s:
                break  # both sides in one bar: ambiguous, skip the day
            if hit_l or hit_s:
                side = 1 if hit_l else -1
                o = orders[side]
                entry = max(b.open, o["entry"]) if side > 0 else min(b.open, o["entry"])
                t0 = t
                break
        if side is None:
            continue
        stop = o["stop"]
        risk = abs(entry - stop)
        target = entry + side * p.r_target * risk
        rest = sess[sess.index >= t0]
        exit_px, why, tx = rest.close.iloc[-1], "time", rest.index[-1]
        for t, b in rest.iterrows():
            if (b.low <= stop) if side > 0 else (b.high >= stop):  # stop checked first (conservative)
                exit_px, why, tx = stop, "stop", t; break
            if (b.high >= target) if side > 0 else (b.low <= target):
                exit_px, why, tx = target, "target", t; break
        trades.append({"signal_time": t0.tz_convert("UTC"), "exit_time": tx.tz_convert("UTC"), "side": side,
                       "entry": entry, "stop": stop, "target": target, "exit": exit_px, "why": why,
                       "R": (side * (exit_px - entry) - p.cost) / risk, "risk": risk})
    return pd.DataFrame(trades)


def london_today(h1: pd.DataFrame, now: pd.Timestamp | None = None, p: LondonParams | None = None) -> list[str]:
    """Alert text for today's London session, or [] when there is no trade plan."""
    p = p or LondonParams()
    now = (now or pd.Timestamp.now(tz="UTC")).tz_convert("Europe/London")
    df, datr, dema, dclose = london_context(h1)
    d = now.normalize()
    g = df[(df.index >= d) & (df.index < d + pd.Timedelta(hours=7))]  # completed overnight bars only
    plan = london_plan(g, d, datr, dema, dclose, p)
    if not plan or "skip" in plan or not plan["orders"]:
        return []
    out = [f"GOLD LONDON BREAKOUT {d:%a %d %b}: overnight range ${plan['lo']:,.2f} - ${plan['hi']:,.2f}"]
    for o in plan["orders"]:
        verb = "BUY STOP" if o["side"] > 0 else "SELL STOP"
        out.append(f"   {verb} ${o['entry']:,.2f} | stop ${o['stop']:,.2f} | target ${o['target']:,.2f} "
                   f"(risk ${abs(o['entry'] - o['stop']):,.0f}/oz, 2:1)")
    out.append("   Cancel if not filled by 12:00 London. Close any open trade by 20:00 London. "
               "Research leads, not financial advice.")
    return out


# ---------------------------------------------------------------- Range fade (4H bars)
def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up, dn = df.high.diff(), -df.low.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = ind.atr(df, n)
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


@dataclass
class FadeParams:
    adx_max: float = 20.0
    rsi_lo: float = 30.0      # long when RSI below this (short when above 100 - rsi_lo)
    band_k: float = 2.0
    stop_atr: float = 1.0
    max_bars: int = 12        # 2 trading days of 4H bars
    cost: float = 0.60


def fade_features(df: pd.DataFrame, p: FadeParams) -> pd.DataFrame:
    f = df.copy()
    f["mid"] = df.close.rolling(20).mean()
    sd = df.close.rolling(20).std()
    f["lo_band"], f["hi_band"] = f.mid - p.band_k * sd, f.mid + p.band_k * sd
    f["rsi"], f["atr"], f["adx"] = ind.rsi(df.close, 14), ind.atr(df, 14), adx(df)
    return f


def fade_signals(f: pd.DataFrame, p: FadeParams) -> pd.Series:
    calm = f.adx < p.adx_max
    long_ = calm & (f.close < f.lo_band) & (f.rsi < p.rsi_lo)
    short = calm & (f.close > f.hi_band) & (f.rsi > 100 - p.rsi_lo)
    return pd.Series(np.where(long_, 1, np.where(short, -1, 0)), index=f.index)


def fade_backtest(df: pd.DataFrame, p: FadeParams) -> pd.DataFrame:
    f = fade_features(df, p)
    sig = fade_signals(f, p)
    o, h, l, c = (f[k].to_numpy() for k in ("open", "high", "low", "close"))
    trades, i, n = [], 60, len(f)
    while i < n - 1:
        side = sig.iloc[i]
        if not side:
            i += 1
            continue
        e = i + 1
        entry = o[e]
        stop = entry - side * p.stop_atr * f.atr.iloc[i]
        target = f.mid.iloc[i]
        if side * (target - entry) <= 0:  # already back at the mean
            i += 1
            continue
        risk = abs(entry - stop)
        exit_px, why, j = None, "time", e
        for j in range(e, min(e + p.max_bars, n)):
            if (l[j] <= stop) if side > 0 else (h[j] >= stop):
                exit_px, why = (min(o[j], stop) if side > 0 else max(o[j], stop)), "stop"; break
            if (h[j] >= target) if side > 0 else (l[j] <= target):
                exit_px, why = (max(o[j], target) if side > 0 else min(o[j], target)), "target"; break
        if exit_px is None:
            exit_px = c[j]
        trades.append({"signal_time": f.index[i], "exit_time": f.index[j], "side": side, "entry": entry, "stop": stop,
                       "target": target, "exit": exit_px, "why": why,
                       "R": (side * (exit_px - entry) - p.cost) / risk, "risk": risk})
        i = j + 1
    return pd.DataFrame(trades)
