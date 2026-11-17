"""Trend-following breakout strategy for gold.

Entry (on a completed bar):
  long  : close breaks above the prior N-bar high, fast EMA > slow EMA, RSI not overbought
  short : close breaks below the prior N-bar low,  fast EMA < slow EMA, RSI not oversold
Exit:
  - protective stop at entry -/+ k*ATR, optional take-profit
  - trailing exit when close crosses the shorter Donchian channel the other way
  - trend flip (fast/slow EMA cross against the position)
"""
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from .config import RiskConfig, StrategyConfig
from . import indicators as ind


class Action(str, Enum):
    HOLD = "HOLD"
    ENTER_LONG = "ENTER_LONG"
    ENTER_SHORT = "ENTER_SHORT"
    EXIT = "EXIT"


@dataclass
class Decision:
    action: Action
    reason: str
    stop_distance: float = 0.0     # in price units, for sizing and stop placement
    target_distance: float = 0.0


def features(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = df.copy()
    out["ema_fast"] = ind.ema(df["close"], cfg.fast_ema)
    out["ema_slow"] = ind.ema(df["close"], cfg.slow_ema)
    out["rsi"] = ind.rsi(df["close"], cfg.rsi_period)
    out["atr"] = ind.atr(df, cfg.atr_period)
    out["entry_hi"], out["entry_lo"] = ind.donchian(df, cfg.breakout_lookback)
    out["exit_hi"], out["exit_lo"] = ind.donchian(df, cfg.exit_lookback)
    return out


def warmup_bars(cfg: StrategyConfig) -> int:
    return max(cfg.slow_ema, cfg.breakout_lookback, cfg.exit_lookback, cfg.atr_period, cfg.rsi_period) + 1


def decide(row: pd.Series, position: float, cfg: StrategyConfig, risk: RiskConfig) -> Decision:
    """position > 0 long, < 0 short, 0 flat. `row` is the latest *completed* bar's features."""
    if row[["ema_fast", "ema_slow", "rsi", "atr", "entry_hi", "exit_hi"]].isna().any():
        return Decision(Action.HOLD, "warming up")

    close, up = row["close"], row["ema_fast"] > row["ema_slow"]

    if position > 0:
        if close < row["exit_lo"]:
            return Decision(Action.EXIT, f"close {close:.2f} < {cfg.exit_lookback}-bar low {row['exit_lo']:.2f}")
        if not up:
            return Decision(Action.EXIT, "trend flipped down (EMA cross)")
        return Decision(Action.HOLD, "long, trend intact")

    if position < 0:
        if close > row["exit_hi"]:
            return Decision(Action.EXIT, f"close {close:.2f} > {cfg.exit_lookback}-bar high {row['exit_hi']:.2f}")
        if up:
            return Decision(Action.EXIT, "trend flipped up (EMA cross)")
        return Decision(Action.HOLD, "short, trend intact")

    stop = risk.atr_stop_mult * row["atr"]
    target = risk.atr_target_mult * row["atr"]
    if up and close > row["entry_hi"]:
        if row["rsi"] >= cfg.rsi_overbought:
            return Decision(Action.HOLD, f"breakout up but RSI {row['rsi']:.0f} overbought")
        return Decision(Action.ENTER_LONG, f"breakout above {row['entry_hi']:.2f} in uptrend", stop, target)
    if cfg.allow_shorts and not up and close < row["entry_lo"]:
        if row["rsi"] <= cfg.rsi_oversold:
            return Decision(Action.HOLD, f"breakdown but RSI {row['rsi']:.0f} oversold")
        return Decision(Action.ENTER_SHORT, f"breakdown below {row['entry_lo']:.2f} in downtrend", stop, target)
    return Decision(Action.HOLD, "no setup")
