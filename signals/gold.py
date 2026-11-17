"""Gold (XAU/USD): daily breakout rules (gold_agent) + 4-hour trend-pullback setup.
Prices come from Twelve Data; the API key is injected by the session's network proxy (no key in code)."""
import datetime as dt

import pandas as pd
import requests

from gold_agent.config import AgentConfig
from gold_agent.strategy import features as daily_features

from .gold_pullback import PullbackParams, clean, features as h4_features, levels, signals as h4_signals

URL = "https://api.twelvedata.com/time_series"


def _fetch(interval: str, bars: int) -> pd.DataFrame:
    return _fetch_symbol("XAU/USD", interval, bars)


def _fetch_symbol(symbol: str, interval: str, bars: int) -> pd.DataFrame:
    r = requests.get(URL, params={"symbol": symbol, "interval": interval, "outputsize": bars, "timezone": "UTC"}, timeout=30)
    j = r.json()
    if j.get("status") != "ok":
        raise RuntimeError(j.get("message", f"HTTP {r.status_code}"))
    df = pd.DataFrame(j["values"]).set_index("datetime")
    df.index = pd.to_datetime(df.index, utc=True)
    return df[["open", "high", "low", "close"]].astype(float).sort_index()


def fetch_daily(bars: int = 400) -> pd.DataFrame:
    df = _fetch("1day", bars)
    df = df[df.index.dayofweek < 5]  # the feed includes flat Saturday/Sunday bars; gold doesn't trade then
    if df.index[-1].date() >= dt.datetime.now(dt.timezone.utc).date():
        df = df.iloc[:-1]  # today's bar is still forming; the rules only use completed bars
    return df


def fetch_4h(bars: int = 500, now: pd.Timestamp | None = None) -> tuple[pd.DataFrame, float]:
    """Completed 4-hour bars plus the latest traded price."""
    df = clean(_fetch("4h", bars))
    now = now or pd.Timestamp.now(tz="UTC")
    last_price = float(df.close.iloc[-1])
    if df.index[-1] + pd.Timedelta(hours=4) > now:
        df = df.iloc[:-1]
    return df, last_price


def daily_levels(df: pd.DataFrame, cfg: AgentConfig | None = None) -> dict:
    """Levels that decide the NEXT daily close (channels include the latest completed day)."""
    cfg = cfg or AgentConfig()
    f = daily_features(df, cfg.strategy)
    b = f.iloc[-1]
    s = cfg.strategy
    return {
        "date": b.name, "close": b["close"], "prev_close": f["close"].iloc[-2], "up": bool(b["ema_fast"] > b["ema_slow"]),
        "ema_fast": b["ema_fast"], "ema_slow": b["ema_slow"], "rsi": b["rsi"], "atr": b["atr"],
        "buy_above": df["high"].iloc[-s.breakout_lookback:].max(), "sell_below": df["low"].iloc[-s.breakout_lookback:].min(),
        "exit_long_below": df["low"].iloc[-s.exit_lookback:].min(), "exit_short_above": df["high"].iloc[-s.exit_lookback:].max(),
        "signal": _daily_signal(b, cfg),
    }


def _daily_signal(b, cfg: AgentConfig) -> str | None:
    """Did the latest completed day trigger an entry? (same rule as gold_agent.strategy.decide)"""
    up = b["ema_fast"] > b["ema_slow"]
    if up and b["close"] > b["entry_hi"] and b["rsi"] < cfg.strategy.rsi_overbought:
        return "BUY"
    if not up and cfg.strategy.allow_shorts and b["close"] < b["entry_lo"] and b["rsi"] > cfg.strategy.rsi_oversold:
        return "SELL"
    return None


def h4_setup(df4: pd.DataFrame, p: PullbackParams | None = None) -> dict | None:
    """4H pullback setup on the latest completed bar, with entry/stop/target estimates."""
    p = p or PullbackParams()
    f = h4_features(df4)
    side = int(h4_signals(f, p).iloc[-1])
    if not side:
        return None
    i = len(f) - 1
    entry = float(f.close.iloc[-1])
    stop, target = levels(f, i, side, entry, p)
    return {"side": "BUY" if side > 0 else "SELL", "bar": f.index[-1], "entry": entry, "stop": stop, "target": target,
            "risk": abs(entry - stop)}


def h4_trend(df4: pd.DataFrame) -> str:
    f = h4_features(df4).iloc[-1]
    if f.ema50 > f.ema200 and f.close > f.ema200:
        return "UP"
    if f.ema50 < f.ema200 and f.close < f.ema200:
        return "DOWN"
    return "MIXED"


def _fmt_setup(s: dict) -> str:
    return (f"{s['side']} near ${s['entry']:,.2f} | stop ${s['stop']:,.2f} | target ${s['target']:,.2f} "
            f"(risk ${s['risk']:,.0f}/oz, 2:1)")


def briefing(df: pd.DataFrame, df4: pd.DataFrame | None = None, cfg: AgentConfig | None = None) -> list[str]:
    cfg = cfg or AgentConfig()
    L = daily_levels(df, cfg)
    stop, tgt = cfg.risk.atr_stop_mult * L["atr"], cfg.risk.atr_target_mult * L["atr"]
    chg = L["close"] / L["prev_close"] - 1
    lines = [
        f"GOLD (XAU/USD) close {L['date']:%a %d %b}: ${L['close']:,.2f} ({chg:+.2%})",
        f"   - Daily trend: {'UP' if L['up'] else 'DOWN'} (50-day ${L['ema_fast']:,.0f} vs 200-day ${L['ema_slow']:,.0f}), "
        f"RSI {L['rsi']:.0f}, daily range ~${L['atr']:,.0f}",
    ]
    if L["signal"]:
        side = 1 if L["signal"] == "BUY" else -1
        lines.append(f"   - DAILY SIGNAL: {L['signal']} at today's open. Stop ~${L['close'] - side * stop:,.2f}, "
                     f"target ~${L['close'] + side * tgt:,.2f}")
    else:
        lines.append(f"   - Daily setup: none. Triggers on a daily close above ${L['buy_above']:,.2f} (BUY, needs uptrend) "
                     f"or below ${L['sell_below']:,.2f} (SELL, needs downtrend)")
        near = _near(L, L["close"])
        if near:
            lines.append(f"   - WATCH: {near}")
    lines.append(f"   - Open daily trades: exit longs on a close below ${L['exit_long_below']:,.2f}, "
                 f"shorts above ${L['exit_short_above']:,.2f}")
    if df4 is not None:
        s = h4_setup(df4)
        lines.append(f"   - 4H trend: {h4_trend(df4)}. " + (f"4H SETUP (bar {s['bar']:%a %H:%M} UTC): {_fmt_setup(s)}"
                                                           if s else "No 4H pullback setup on the latest bar."))
    return lines


def _near(L: dict, price: float) -> str | None:
    """Heads-up when price is within half a daily range of the trend-direction trigger (or through it)."""
    zone = 0.5 * L["atr"]
    if L["up"] and price >= L["buy_above"] - zone:
        what = "ABOVE" if price > L["buy_above"] else f"${L['buy_above'] - price:,.0f} below"
        return f"gold ${price:,.2f} is {what} the BUY trigger ${L['buy_above']:,.2f}. A daily close above it = BUY signal."
    if not L["up"] and price <= L["sell_below"] + zone:
        what = "BELOW" if price < L["sell_below"] else f"${price - L['sell_below']:,.0f} above"
        return f"gold ${price:,.2f} is {what} the SELL trigger ${L['sell_below']:,.2f}. A daily close below it = SELL signal."
    return None


def watch(df: pd.DataFrame, df4: pd.DataFrame, price: float) -> list[str]:
    """Intraday check run every 4 hours. Returns alert lines, or [] when there's nothing new to say.
    Only NEW events alert: a 4H setup on the bar that just closed, or price entering the trigger zone during it."""
    L = daily_levels(df)
    out = []
    s = h4_setup(df4)
    if s:
        out.append(f"GOLD 4H SETUP: {_fmt_setup(s)}. Valid for the next 4H bar; skip if price has run past the target.")
    now_near = _near(L, float(df4.close.iloc[-1]))
    was_near = _near(L, float(df4.close.iloc[-2])) if len(df4) > 1 else None
    if now_near and not was_near:
        out.append(f"GOLD HEADS-UP: {now_near} New York close is 5pm ET.")
    if out:
        out.append(f"Live ~${price:,.2f}. Research leads, not financial advice.")
    return out
