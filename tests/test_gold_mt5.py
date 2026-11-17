"""Exercises MT5Broker against a fake MetaTrader5 module (the real one is Windows-only)."""
import sys
import types
from types import SimpleNamespace as NS

import numpy as np
import pytest


@pytest.fixture
def fake_mt5(monkeypatch):
    m = types.ModuleType("MetaTrader5")
    m.TRADE_ACTION_DEAL, m.ORDER_TYPE_BUY, m.ORDER_TYPE_SELL = 1, 0, 1
    m.POSITION_TYPE_BUY, m.POSITION_TYPE_SELL = 0, 1
    m.ORDER_FILLING_FOK, m.ORDER_FILLING_IOC, m.ORDER_FILLING_RETURN = 0, 1, 2
    m.ORDER_TIME_GTC, m.TRADE_RETCODE_DONE, m.ACCOUNT_TRADE_MODE_REAL = 0, 10009, 2
    m.TIMEFRAME_D1 = 16408
    m.sent, m.positions = [], []
    m.initialize = lambda **kw: True
    m.last_error = lambda: (0, "ok")
    m.symbol_select = lambda s, on: True
    m.symbol_info = lambda s: NS(trade_contract_size=100.0, volume_step=0.01, volume_min=0.01, volume_max=50.0,
                                 digits=2, filling_mode=2)
    m.symbol_info_tick = lambda s: NS(bid=2000.0, ask=2000.3)
    m.account_info = lambda: NS(equity=10_000.0, trade_mode=0)
    m.positions_get = lambda symbol: m.positions

    def order_send(req):
        m.sent.append(req)
        return NS(retcode=10009, comment="done")
    m.order_send = order_send
    rates = np.array([(1_700_000_000 + i * 86400, 2000.0 + i, 2005.0 + i, 1995.0 + i, 2001.0 + i, 100, 30, 0) for i in range(5)],
                     dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
                            ("tick_volume", "i8"), ("spread", "i4"), ("real_volume", "i8")])
    m.copy_rates_from_pos = lambda s, tf, start, n: rates
    monkeypatch.setitem(sys.modules, "MetaTrader5", m)
    return m


def test_load_mt5(fake_mt5):
    from gold_agent.mt5 import load_mt5
    df = load_mt5("XAUUSD", "D1", 5)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"] and len(df) == 5
    assert str(df.index.tz) == "UTC"


def test_buy_converts_ounces_to_lots_and_sets_sl_tp(fake_mt5):
    from gold_agent.mt5 import MAGIC, MT5Broker
    b = MT5Broker("XAUUSD")
    filled = b.market_order(2.57, price=1990.0, stop=1940.0, target=2090.0)  # 2.57 oz -> 0.02 lot
    req = fake_mt5.sent[-1]
    assert req["volume"] == 0.02 and filled == pytest.approx(2.0)
    assert req["type"] == fake_mt5.ORDER_TYPE_BUY and req["price"] == 2000.3
    assert req["sl"] == pytest.approx(1950.3) and req["tp"] == pytest.approx(2100.3)   # distances kept, re-anchored
    assert req["magic"] == MAGIC and req["type_filling"] == fake_mt5.ORDER_FILLING_IOC


def test_sell_and_below_min_lot(fake_mt5):
    from gold_agent.mt5 import MT5Broker
    b = MT5Broker("XAUUSD")
    b.market_order(-3.0, 2000.0, 2050.0, None)
    req = fake_mt5.sent[-1]
    assert req["type"] == fake_mt5.ORDER_TYPE_SELL and req["price"] == 2000.0 and req["sl"] == 2050.0 and req["tp"] == 0.0
    n = len(fake_mt5.sent)
    assert b.market_order(0.5, 2000.0, 1950.0, None) == 0.0 and len(fake_mt5.sent) == n  # < 1 oz min: skipped


def test_position_ignores_manual_trades_and_close(fake_mt5):
    from gold_agent.mt5 import MAGIC, MT5Broker
    fake_mt5.positions = [NS(ticket=1, type=0, volume=0.03, magic=MAGIC), NS(ticket=2, type=1, volume=1.0, magic=0)]
    b = MT5Broker("XAUUSD")
    assert b.position() == pytest.approx(3.0)
    b.close(2000.0, "test")
    req = fake_mt5.sent[-1]
    assert req["position"] == 1 and req["type"] == fake_mt5.ORDER_TYPE_SELL and req["volume"] == 0.03


def test_rejected_order_raises(fake_mt5):
    from gold_agent.mt5 import MT5Broker
    fake_mt5.order_send = lambda req: NS(retcode=10019, comment="no money")
    with pytest.raises(RuntimeError, match="no money"):
        MT5Broker("XAUUSD").market_order(5.0, 2000.0, 1950.0, None)
