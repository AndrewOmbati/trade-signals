"""Event-driven backtest. Signals are computed on bar t's close and filled at bar t+1's open.
Stops/targets are checked intrabar against high/low (stop assumed first if both touched; gaps fill at the open)."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import AgentConfig
from .risk import DrawdownGuard, position_size
from .strategy import Action, Decision, decide, features, warmup_bars


@dataclass
class Trade:
    side: int
    units: float
    entry_time: pd.Timestamp
    entry: float
    stop: float
    target: float
    exit_time: pd.Timestamp | None = None
    exit: float | None = None
    reason: str = ""

    @property
    def pnl(self) -> float:
        return 0.0 if self.exit is None else self.side * (self.exit - self.entry) * self.units


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[Trade] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def run_backtest(df: pd.DataFrame, cfg: AgentConfig) -> BacktestResult:
    f = features(df, cfg.strategy)
    half_spread = cfg.costs.spread / 2
    cash, pos, trades = cfg.starting_equity, None, []
    guard = DrawdownGuard(cfg.risk)
    pending = None  # Decision to execute at next open
    equity_curve = []

    def close_pos(t, price, reason):
        nonlocal cash, pos
        fill = price - pos.side * half_spread
        pos.exit_time, pos.exit, pos.reason = t, fill, reason
        cash += pos.pnl - cfg.costs.commission_per_unit * pos.units
        trades.append(pos)
        pos = None

    for i, (t, bar) in enumerate(f.iterrows()):
        # 1) Execute yesterday's decision at today's open.
        if pending is not None:
            if pending.action == Action.EXIT and pos:
                close_pos(t, bar["open"], "signal: " + pending.reason)
            elif pending.action in (Action.ENTER_LONG, Action.ENTER_SHORT) and pos is None and not guard.tripped:
                side = 1 if pending.action == Action.ENTER_LONG else -1
                fill = bar["open"] + side * half_spread
                units = position_size(cash, fill, pending.stop_distance, cfg.risk)
                if units > 0:
                    cash -= cfg.costs.commission_per_unit * units
                    tgt = fill + side * pending.target_distance if pending.target_distance else np.nan
                    pos = Trade(side, units, t, fill, fill - side * pending.stop_distance, tgt)
            pending = None

        # 2) Intrabar stop / target.
        if pos:
            s = pos.side
            stop_hit = bar["low"] <= pos.stop if s > 0 else bar["high"] >= pos.stop
            tgt_hit = not np.isnan(pos.target) and (bar["high"] >= pos.target if s > 0 else bar["low"] <= pos.target)
            if stop_hit:
                gapped = bar["open"] < pos.stop if s > 0 else bar["open"] > pos.stop
                close_pos(t, bar["open"] if gapped else pos.stop, "stop loss")
            elif tgt_hit:
                gapped = bar["open"] > pos.target if s > 0 else bar["open"] < pos.target
                close_pos(t, bar["open"] if gapped else pos.target, "take profit")

        # 3) Mark to market, then decide on the close.
        eq = cash + (pos.side * (bar["close"] - pos.entry) * pos.units if pos else 0.0)
        equity_curve.append(eq)
        guard.update(eq)
        if i + 1 >= warmup_bars(cfg.strategy):
            d = decide(bar, pos.side if pos else 0, cfg.strategy, cfg.risk)
            if guard.tripped and pos:
                d = d if d.action == Action.EXIT else Decision(Action.EXIT, "drawdown kill switch")
            if d.action != Action.HOLD:
                pending = d

    if pos:
        close_pos(f.index[-1], f["close"].iloc[-1], "end of data")
        equity_curve[-1] = cash

    equity = pd.Series(equity_curve, index=f.index, name="equity")
    return BacktestResult(equity, trades, compute_stats(equity, trades, df))


def compute_stats(equity: pd.Series, trades: list[Trade], df: pd.DataFrame) -> dict:
    rets = equity.pct_change().dropna()
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    per_year = len(equity) / years
    pnls = np.array([t.pnl for t in trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    dd = equity / equity.cummax() - 1
    return {
        "start": str(equity.index[0].date()),
        "end": str(equity.index[-1].date()),
        "final_equity": round(equity.iloc[-1], 2),
        "total_return_%": round((equity.iloc[-1] / equity.iloc[0] - 1) * 100, 2),
        "cagr_%": round(((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) * 100, 2),
        "sharpe": round(rets.mean() / rets.std() * np.sqrt(per_year), 2) if rets.std() > 0 else 0.0,
        "max_drawdown_%": round(dd.min() * 100, 2),
        "trades": len(trades),
        "win_rate_%": round(len(wins) / len(pnls) * 100, 1) if len(pnls) else 0.0,
        "profit_factor": round(wins.sum() / -losses.sum(), 2) if losses.sum() < 0 else float("inf"),
        "avg_trade_$": round(pnls.mean(), 2) if len(pnls) else 0.0,
        "buy_hold_return_%": round((df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100, 2),
    }
