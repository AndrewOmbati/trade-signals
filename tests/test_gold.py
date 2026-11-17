import pandas as pd

from gold_agent.data import synthetic
from signals import gold
from signals.gold_pullback import PullbackParams, backtest, clean, summary


def h4(n=600, seed=5):
    d = synthetic(n=n, seed=seed)
    d.index = pd.date_range("2026-01-05 00:00", periods=n, freq="4h", tz="UTC")
    return clean(d)


def test_daily_levels_include_latest_day():
    df = synthetic(n=400)
    L = gold.daily_levels(df)
    assert L["buy_above"] == df.high.iloc[-20:].max() and L["sell_below"] == df.low.iloc[-20:].min()
    assert L["exit_long_below"] == df.low.iloc[-10:].min()


def test_near_trigger_only_in_trend_direction():
    L = {"up": False, "atr": 60.0, "buy_above": 4100.0, "sell_below": 3800.0}
    assert "SELL trigger" in gold._near(L, 3825.0)          # within half a range
    assert "BELOW" in gold._near(L, 3790.0)                 # through it
    assert gold._near(L, 3900.0) is None                    # too far
    assert gold._near(L, 4090.0) is None                    # near BUY level but trend is down


def test_watch_alerts_only_on_new_events(monkeypatch):
    L = {"up": False, "atr": 60.0, "buy_above": 4100.0, "sell_below": 3800.0}
    monkeypatch.setattr(gold, "daily_levels", lambda df: L)
    monkeypatch.setattr(gold, "h4_setup", lambda df4: None)
    idx = pd.date_range("2026-11-17", periods=2, freq="4h", tz="UTC")
    entering = pd.DataFrame({"close": [3900.0, 3820.0]}, index=idx)
    staying = pd.DataFrame({"close": [3825.0, 3820.0]}, index=idx)
    assert any("HEADS-UP" in l for l in gold.watch(None, entering, 3819.0))
    assert gold.watch(None, staying, 3819.0) == []


def test_watch_reports_4h_setup(monkeypatch):
    monkeypatch.setattr(gold, "daily_levels", lambda df: {"up": True, "atr": 60.0, "buy_above": 5000.0, "sell_below": 3000.0})
    monkeypatch.setattr(gold, "h4_setup", lambda df4: {"side": "BUY", "bar": pd.Timestamp("2026-11-17 12:00", tz="UTC"),
                                                       "entry": 4000.0, "stop": 3970.0, "target": 4060.0, "risk": 30.0})
    df4 = pd.DataFrame({"close": [3990.0, 4000.0]}, index=pd.date_range("2026-11-17", periods=2, freq="4h", tz="UTC"))
    out = gold.watch(None, df4, 4001.0)
    assert out[0].startswith("GOLD 4H SETUP: BUY") and "stop $3,970.00" in out[0]


def test_pullback_backtest_runs_and_respects_one_position():
    t = backtest(h4(), PullbackParams())
    s = summary(t, 10)
    assert s["trades"] == len(t)
    if len(t) > 1:
        assert (t.entry_time.iloc[1:].values > t.exit_time.iloc[:-1].values).all()


def test_briefing_with_4h():
    lines = gold.briefing(synthetic(n=400), h4())
    assert lines[0].startswith("GOLD (XAU/USD)") and any(l.strip().startswith("- 4H trend") for l in lines)
