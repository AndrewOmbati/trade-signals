import json

import pandas as pd

from signals import journal

CTX = {"generated_utc": "2026-11-18 07:10:00+00:00",
       "markets": [{"symbol": "XAU/USD", "price": 3850.0, "daily": {"atr14": 80.0}},
                   {"symbol": "EUR/USD", "price": 1.1000, "daily": {"atr14": 0.0070}}]}


def idea(**kw):
    base = {"symbol": "XAU/USD", "side": "SELL", "entry_type": "limit", "entry": 3870.0, "stop": 3900.0, "target": 3810.0,
            "grade": "B", "basis": "discretionary", "thesis": "t", "invalidation": "i", "catalyst": "c"}
    return {**base, **kw}


def test_validate_rules():
    good = [idea()] * 4 + [idea(symbol="EUR/USD", side="BUY", entry_type="market", entry=1.1, stop=1.096, target=1.107)]
    assert journal.validate(good, CTX) == []
    assert any("at least 5" in e for e in journal.validate(good[:4], CTX))
    assert any("stop must be above" in e for e in journal.validate([idea(stop=3840.0)] + good[1:], CTX))
    assert any("reward:risk" in e for e in journal.validate([idea(target=3850.0)] + good[1:], CTX))
    assert any("limit must be above" in e for e in journal.validate([idea(entry=3840.0, stop=3870.0, target=3780.0)] + good[1:], CTX))
    assert any("XAU/USD" in e for e in journal.validate([idea(symbol="EUR/USD", side="BUY", entry_type="market", entry=1.1, stop=1.096, target=1.107)] * 5, CTX))


def bars(rows):
    idx = pd.date_range("2026-11-18 08:00", periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def rec(**kw):
    return {**idea(**kw), "created_utc": "2026-11-18 07:10:00+00:00", "price_at_creation": 3850.0, "expires_hours": 24}


def test_grade_limit_fill_then_target():
    b = bars([(3850, 3872, 3848, 3865), (3865, 3866, 3830, 3835), (3835, 3836, 3805, 3809)])
    g = journal.grade_one(rec(), b)
    assert g["status"] == "win" and g["R"] == 2.0


def test_grade_stop_first_and_expiry():
    b = bars([(3850, 3905, 3848, 3890)])  # fills at 3870 and hits the 3900 stop in the same bar
    assert journal.grade_one(rec(), b)["status"] == "loss"
    never = bars([(3850, 3860, 3840, 3850)] * 30)
    assert journal.grade_one(rec(), never)["status"] == "expired"
    assert journal.grade_one(rec(), never.iloc[:3])["status"] == "pending"


def test_add_and_grade_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "journal").mkdir()
    monkeypatch.setattr(journal, "IDEAS", tmp_path / "journal/ideas.jsonl")
    monkeypatch.setattr(journal, "CACHE", tmp_path / "journal/.h1_cache.json")
    ideas = [idea()] * 5
    (tmp_path / "i.json").write_text(json.dumps(ideas)); (tmp_path / "c.json").write_text(json.dumps(CTX))
    assert journal.add(str(tmp_path / "i.json"), str(tmp_path / "c.json")) == 0
    assert journal.add(str(tmp_path / "i.json"), str(tmp_path / "c.json")) == 1  # same day twice
    b = bars([(3850, 3872, 3848, 3865), (3865, 3866, 3805, 3809)])
    (tmp_path / "journal/.h1_cache.json").write_text(json.dumps(
        {"XAU/USD": {**{k: b[k].tolist() for k in ("open", "high", "low", "close")}, "index": [str(t) for t in b.index]}}))
    assert journal.grade() == 0


def test_grade_empty_journal(tmp_path, monkeypatch):
    f = tmp_path / "ideas.jsonl"
    f.write_text("")
    monkeypatch.setattr(journal, "IDEAS", f)
    assert journal.grade() == 0
