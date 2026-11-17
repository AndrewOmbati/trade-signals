import math

from .config import RiskConfig


def position_size(equity: float, price: float, stop_distance: float, cfg: RiskConfig) -> float:
    """Ounces to trade so that hitting the stop loses ~risk_per_trade of equity, capped by leverage."""
    if equity <= 0 or price <= 0 or stop_distance <= 0:
        return 0.0
    units = min(equity * cfg.risk_per_trade / stop_distance, equity * cfg.max_leverage / price)
    step = cfg.min_units
    units = math.floor(units / step) * step
    return round(units, 6) if units >= step else 0.0


class DrawdownGuard:
    """Kill switch: once equity falls max_drawdown below its peak, no new entries."""

    def __init__(self, cfg: RiskConfig, peak: float = 0.0):
        self.cfg, self.peak, self.tripped = cfg, peak, False

    def update(self, equity: float) -> bool:
        self.peak = max(self.peak, equity)
        if self.peak and equity < self.peak * (1 - self.cfg.max_drawdown):
            self.tripped = True
        return self.tripped
