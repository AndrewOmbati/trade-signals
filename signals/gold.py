"""Daily gold (XAU/USD) briefing using the gold_agent trend-breakout rules.
Prices come from Twelve Data; the API key is injected by the session's network proxy (no key in code)."""
import datetime as dt

import pandas as pd
import requests

from gold_agent.config import AgentConfig
from gold_agent.strategy import Action, decide, features

URL = "https://api.twelvedata.com/time_series"


def fetch_daily(bars: int = 400) -> pd.DataFrame:
    r = requests.get(URL, params={"symbol": "XAU/USD", "interval": "1day", "outputsize": bars, "timezone": "UTC"}, timeout=30)
    j = r.json()
    if j.get("status") != "ok":
        raise RuntimeError(j.get("message", f"HTTP {r.status_code}"))
    df = pd.DataFrame(j["values"]).set_index("datetime")
    df.index = pd.to_datetime(df.index, utc=True)
    df = df[["open", "high", "low", "close"]].astype(float).sort_index()
    if df.index[-1].date() >= dt.datetime.now(dt.timezone.utc).date():
        df = df.iloc[:-1]  # today's bar is still forming; the rules only use completed bars
    return df


def briefing(df: pd.DataFrame, cfg: AgentConfig | None = None) -> list[str]:
    cfg = cfg or AgentConfig()
    f = features(df, cfg.strategy)
    b, prev = f.iloc[-1], f.iloc[-2]
    chg = b["close"] / prev["close"] - 1
    up = b["ema_fast"] > b["ema_slow"]
    d = decide(b, 0, cfg.strategy, cfg.risk)
    stop, tgt = cfg.risk.atr_stop_mult * b["atr"], cfg.risk.atr_target_mult * b["atr"]
    lines = [
        f"GOLD (XAU/USD) close {b.name:%a %d %b}: ${b['close']:,.2f} ({chg:+.2%})",
        f"   - Trend: {'UP' if up else 'DOWN'} (50-day avg ${b['ema_fast']:,.0f} vs 200-day ${b['ema_slow']:,.0f}), RSI {b['rsi']:.0f}, daily range ~${b['atr']:,.0f}",
        f"   - Breakout levels: buy above ${b['entry_hi']:,.2f} | sell below ${b['entry_lo']:,.2f}",
    ]
    if d.action in (Action.ENTER_LONG, Action.ENTER_SHORT):
        side = 1 if d.action == Action.ENTER_LONG else -1
        lines.append(f"   - SIGNAL: {'BUY' if side > 0 else 'SELL'} ({d.reason}). Stop ~${b['close'] - side * stop:,.2f}, "
                     f"target ~${b['close'] + side * tgt:,.2f}")
    else:
        lines.append(f"   - No new trade today ({d.reason}).")
    lines.append(f"   - If already long: exit on a close below ${b['exit_lo']:,.2f}. If short: exit above ${b['exit_hi']:,.2f}.")
    return lines
