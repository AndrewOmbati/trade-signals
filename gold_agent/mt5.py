"""MetaTrader 5 data + execution via the official `MetaTrader5` package (Windows, MT5 terminal installed and logged in).

The agent thinks in troy ounces; MT5 trades lots. Conversion uses the symbol's contract size (usually 100 oz per lot
for XAUUSD, but brokers differ, so it is always read from symbol_info).
"""
import logging
import os

import pandas as pd

from .broker import Broker

log = logging.getLogger("gold_agent.mt5")
MAGIC = 20261117  # tags orders from this agent so it never touches your manual trades


def _mt5():
    try:
        import MetaTrader5 as mt5
    except ImportError as e:
        raise SystemExit("pip install MetaTrader5  (Windows only, needs the MT5 terminal)") from e
    return mt5


def connect():
    mt5 = _mt5()
    kw = {}
    if os.getenv("MT5_LOGIN"):
        kw = dict(login=int(os.environ["MT5_LOGIN"]), password=os.environ["MT5_PASSWORD"], server=os.environ["MT5_SERVER"])
    if os.getenv("MT5_PATH"):
        kw["path"] = os.environ["MT5_PATH"]
    if not mt5.initialize(**kw):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    return mt5


def load_mt5(symbol: str = "XAUUSD", timeframe: str = "D1", count: int = 3000) -> pd.DataFrame:
    mt5 = connect()
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"symbol {symbol!r} not found; check your broker's name for gold (e.g. XAUUSD, GOLD, XAUUSD.m)")
    tf = getattr(mt5, f"TIMEFRAME_{timeframe.upper()}")
    rates = mt5.copy_rates_from_pos(symbol, tf, 1, count)  # start at 1: skip the still-forming bar
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"no rates for {symbol}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["open", "high", "low", "close", "volume"]].astype(float)


class MT5Broker(Broker):
    def __init__(self, symbol: str = "XAUUSD", deviation: int = 50):
        self.mt5, self.symbol, self.deviation = connect(), symbol, deviation
        self.mt5.symbol_select(symbol, True)
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol {symbol!r} not available")
        self.info = info
        self.contract = info.trade_contract_size or 100.0

    def is_real_account(self) -> bool:
        return self.mt5.account_info().trade_mode == self.mt5.ACCOUNT_TRADE_MODE_REAL

    def equity(self):
        return float(self.mt5.account_info().equity)

    def _positions(self):
        return [p for p in (self.mt5.positions_get(symbol=self.symbol) or []) if p.magic == MAGIC]

    def position(self):
        return sum((p.volume if p.type == self.mt5.POSITION_TYPE_BUY else -p.volume) * self.contract for p in self._positions())

    def _filling(self):
        fm = self.info.filling_mode
        if fm & 1:
            return self.mt5.ORDER_FILLING_FOK
        if fm & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def _lots(self, units: float) -> float:
        step, vmin, vmax = self.info.volume_step, self.info.volume_min, self.info.volume_max
        lots = int(abs(units) / self.contract / step + 1e-9) * step
        return round(min(lots, vmax), 8) if lots >= vmin else 0.0

    def _send(self, req):
        res = self.mt5.order_send(req)
        if res is None or res.retcode != self.mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"order rejected: {getattr(res, 'retcode', None)} {getattr(res, 'comment', self.mt5.last_error())}")
        return res

    def market_order(self, units, price, stop, target):
        lots = self._lots(units)
        if lots == 0:
            log.warning("size %.2f oz is below the broker minimum of %s lot (%.0f oz); skipping",
                        abs(units), self.info.volume_min, self.info.volume_min * self.contract)
            return 0.0
        buy = units > 0
        tick = self.mt5.symbol_info_tick(self.symbol)
        px = tick.ask if buy else tick.bid
        # Re-anchor stop/target on the live price, keeping the strategy's distances.
        sl_d, tp_d = abs(price - stop), (abs(target - price) if target else 0.0)
        d = self.info.digits
        req = {
            "action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": lots,
            "type": self.mt5.ORDER_TYPE_BUY if buy else self.mt5.ORDER_TYPE_SELL, "price": px,
            "sl": round(px - sl_d if buy else px + sl_d, d),
            "tp": round(px + tp_d if buy else px - tp_d, d) if tp_d else 0.0,
            "deviation": self.deviation, "magic": MAGIC, "comment": "gold_agent",
            "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling(),
        }
        self._send(req)
        return (lots if buy else -lots) * self.contract

    def close(self, price, reason):
        for p in self._positions():
            buy = p.type == self.mt5.POSITION_TYPE_BUY
            tick = self.mt5.symbol_info_tick(self.symbol)
            self._send({
                "action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": p.volume, "position": p.ticket,
                "type": self.mt5.ORDER_TYPE_SELL if buy else self.mt5.ORDER_TYPE_BUY,
                "price": tick.bid if buy else tick.ask, "deviation": self.deviation, "magic": MAGIC,
                "comment": f"gold_agent: {reason}"[:31], "type_time": self.mt5.ORDER_TIME_GTC, "type_filling": self._filling(),
            })
