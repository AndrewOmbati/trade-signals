import json

import numpy as np
import pandas as pd
import pytest

from gold_agent import data
from gold_agent.agent import GoldAgent
from gold_agent.backtest import run_backtest
from gold_agent.broker import PaperBroker
from gold_agent.config import AgentConfig, RiskConfig
from gold_agent.risk import DrawdownGuard, position_size
from gold_agent.strategy import Action, decide, features


@pytest.fixture(scope="module")
def df():
    return data.synthetic(n=1500, seed=3)


def test_no_lookahead(df):
    """Features up to bar t must not change when future bars are appended."""
    cfg = AgentConfig().strategy
    full = features(df, cfg)
    part = features(df.iloc[:900], cfg)
    pd.testing.assert_frame_equal(full.iloc[:900], part, check_freq=False)


def test_position_size_risk_and_leverage_caps():
    r = RiskConfig(risk_per_trade=0.01, max_leverage=3.0)
    assert position_size(10_000, 2000, 50, r) == pytest.approx(2.0)       # $100 risk / $50 stop
    assert position_size(10_000, 2000, 0.5, r) == pytest.approx(15.0)     # leverage cap 3x
    assert position_size(10_000, 2000, 0, r) == 0.0


def test_drawdown_guard():
    g = DrawdownGuard(RiskConfig(max_drawdown=0.2))
    assert not g.update(100) and not g.update(85)
    assert g.update(79)


def test_backtest_losses_bounded(df):
    res = run_backtest(df, AgentConfig())
    assert res.stats["trades"] > 0
    # No single loss should greatly exceed the 1% risk budget (allowing for gaps/spread).
    worst = min(t.pnl for t in res.trades)
    assert worst > -0.03 * res.equity.max()
    assert np.isfinite(res.equity).all()


def test_decide_exits_long_on_channel_break(df):
    cfg = AgentConfig()
    row = features(df, cfg.strategy).iloc[-1].copy()
    row["exit_lo"] = row["close"] + 1
    assert decide(row, 1.0, cfg.strategy, cfg.risk).action == Action.EXIT


def test_paper_agent_cycle(tmp_path, df):
    cfg = AgentConfig()
    broker = PaperBroker(str(tmp_path / "s.json"), 10_000, cfg.costs.spread)
    journal = tmp_path / "j.jsonl"
    # Replay bar by bar as if live.
    actions = []
    for end in range(400, 700):
        agent = GoldAgent(cfg, broker, lambda e=end: df.iloc[:e], str(journal))
        actions.append(agent.step()["action"])
    assert {"ENTER_LONG", "ENTER_SHORT"} & set(actions)
    lines = journal.read_text().splitlines()
    assert len(lines) == 300 and json.loads(lines[-1])["equity"] > 0
