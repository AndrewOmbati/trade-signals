from dataclasses import dataclass, field


@dataclass
class StrategyConfig:
    fast_ema: int = 50
    slow_ema: int = 200
    breakout_lookback: int = 20      # Donchian channel for entries
    exit_lookback: int = 10          # Donchian channel for trailing exits
    rsi_period: int = 14
    rsi_overbought: float = 75.0     # skip long entries when stretched
    rsi_oversold: float = 25.0       # skip short entries when stretched
    atr_period: int = 14
    allow_shorts: bool = True


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01     # fraction of equity risked per trade
    atr_stop_mult: float = 2.5       # initial stop distance in ATRs
    atr_target_mult: float = 5.0     # take-profit distance in ATRs (0 = none)
    max_leverage: float = 3.0        # cap notional / equity
    max_drawdown: float = 0.20       # kill switch: stop trading past this drawdown
    min_units: float = 0.01          # smallest tradable size (ounces)


@dataclass
class CostConfig:
    spread: float = 0.30             # USD per ounce, round trip half applied each side
    commission_per_unit: float = 0.0


@dataclass
class AgentConfig:
    symbol: str = "XAU_USD"
    starting_equity: float = 10_000.0
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostConfig = field(default_factory=CostConfig)
