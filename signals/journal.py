"""Daily analyst ideas: validate, record, and grade them against real prices.

    python -m signals.journal add ideas.json     # validate today's ideas and append them to journal/ideas.jsonl
    python -m signals.journal grade              # grade every recorded idea with cached 1H bars; print the track record
"""
import json
import sys
from pathlib import Path

import pandas as pd

IDEAS = Path("journal/ideas.jsonl")
CACHE = Path("journal/.h1_cache.json")
FIELDS = {"symbol", "side", "entry_type", "entry", "stop", "target", "grade", "basis", "thesis", "invalidation", "catalyst"}


def validate(ideas: list[dict], context: dict) -> list[str]:
    """Return a list of problems (empty = OK)."""
    errs = []
    if len(ideas) < 5:
        errs.append(f"need at least 5 ideas, got {len(ideas)}")
    if not any(i.get("symbol") == "XAU/USD" for i in ideas):
        errs.append("include at least one XAU/USD idea")
    mk = {m["symbol"]: m for m in context.get("markets", [])}
    for n, i in enumerate(ideas, 1):
        tag = f"idea {n} ({i.get('symbol')})"
        missing = FIELDS - i.keys()
        if missing:
            errs.append(f"{tag}: missing {sorted(missing)}"); continue
        if i["symbol"] not in mk:
            errs.append(f"{tag}: no chart context for this symbol"); continue
        if i["side"] not in ("BUY", "SELL") or i["entry_type"] not in ("market", "limit", "stop") or i["grade"] not in ("A", "B", "C"):
            errs.append(f"{tag}: side BUY/SELL, entry_type market/limit/stop, grade A/B/C"); continue
        s = 1 if i["side"] == "BUY" else -1
        e, st, tg = float(i["entry"]), float(i["stop"]), float(i["target"])
        price, atr = mk[i["symbol"]]["price"], mk[i["symbol"]]["daily"]["atr14"]
        if not (s * (e - st) > 0 and s * (tg - e) > 0):
            errs.append(f"{tag}: for a {i['side']} the stop must be {'below' if s > 0 else 'above'} entry and the target beyond it")
            continue
        rr = abs(tg - e) / abs(e - st)
        if rr < 1.5:
            errs.append(f"{tag}: reward:risk {rr:.2f} < 1.5")
        if not 0.2 * atr <= abs(e - st) <= 2.5 * atr:
            errs.append(f"{tag}: stop distance {abs(e - st):.5g} should be 0.2-2.5 daily ATR ({atr:.5g})")
        if abs(e - price) > 1.5 * atr:
            errs.append(f"{tag}: entry {e} is more than 1.5 daily ATR from price {price}")
        if i["entry_type"] == "limit" and s * (price - e) < 0:
            errs.append(f"{tag}: a {i['side']} limit must be {'below' if s > 0 else 'above'} current price")
        if i["entry_type"] == "stop" and s * (e - price) < 0:
            errs.append(f"{tag}: a {i['side']} stop entry must be {'above' if s > 0 else 'below'} current price")
    return errs


def add(path: str, context_path: str) -> int:
    ideas = json.loads(Path(path).read_text())
    ctx = json.loads(Path(context_path).read_text())
    errs = validate(ideas, ctx)
    if errs:
        print("REJECTED:\n- " + "\n- ".join(errs))
        return 1
    created = ctx["generated_utc"]
    day = created[:10]
    existing = [json.loads(l) for l in IDEAS.read_text().splitlines()] if IDEAS.exists() else []
    if any(x["created_utc"][:10] == day for x in existing):
        print(f"REJECTED: ideas for {day} are already recorded")
        return 1
    mk = {m["symbol"]: m["price"] for m in ctx["markets"]}
    with IDEAS.open("a") as fh:
        for n, i in enumerate(ideas, 1):
            rec = {"id": f"{day}-{n}", "created_utc": created, "price_at_creation": mk[i["symbol"]],
                   "expires_hours": int(i.get("expires_hours", 24)), **{k: i[k] for k in sorted(FIELDS)}}
            fh.write(json.dumps(rec) + "\n")
    print(f"recorded {len(ideas)} ideas for {day}")
    return 0


def _bars(cache: dict, sym: str) -> pd.DataFrame:
    c = cache[sym]
    return pd.DataFrame({k: c[k] for k in ("open", "high", "low", "close")}, index=pd.to_datetime(c["index"], utc=True))


def grade_one(idea: dict, bars: pd.DataFrame, max_hold_h: int = 120) -> dict:
    """Simulate on 1H bars after creation: fill (market/limit/stop) within expires_hours, then stop vs target
    (stop wins if both in one bar), time exit after max_hold_h. Status: pending, expired, open, win, loss, time."""
    s = 1 if idea["side"] == "BUY" else -1
    e, st, tg = float(idea["entry"]), float(idea["stop"]), float(idea["target"])
    t0 = pd.Timestamp(idea["created_utc"])
    after = bars[bars.index >= t0.floor("h") + pd.Timedelta(hours=1)]
    deadline = t0 + pd.Timedelta(hours=idea["expires_hours"])
    fill_t = None
    if idea["entry_type"] == "market":
        fill_t, e = t0, float(idea["price_at_creation"])
    else:
        for t, b in after[after.index < deadline].iterrows():
            touched = (b.low <= e if s > 0 else b.high >= e) if idea["entry_type"] == "limit" else (b.high >= e if s > 0 else b.low <= e)
            if touched:
                fill_t = t
                if idea["entry_type"] == "stop":
                    e = max(b.open, e) if s > 0 else min(b.open, e)  # gap through a stop entry fills worse
                break
        if fill_t is None:
            return {"status": "expired" if (after.index.max() if len(after) else t0) >= deadline else "pending", "R": None}
    risk = abs(e - st)
    live = after[after.index >= fill_t.floor("h")]
    for t, b in live.iterrows():
        if (b.low <= st) if s > 0 else (b.high >= st):
            return {"status": "loss", "R": round((s * (st - e)) / risk, 2), "filled": str(fill_t), "closed": str(t)}
        if (b.high >= tg) if s > 0 else (b.low <= tg):
            return {"status": "win", "R": round((s * (tg - e)) / risk, 2), "filled": str(fill_t), "closed": str(t)}
        if t >= fill_t + pd.Timedelta(hours=max_hold_h):
            return {"status": "time", "R": round(s * (b.close - e) / risk, 2), "filled": str(fill_t), "closed": str(t)}
    last = live.close.iloc[-1] if len(live) else e
    return {"status": "open", "R": round(s * (last - e) / risk, 2), "filled": str(fill_t)}


def grade() -> int:
    if not IDEAS.exists():
        print("TRACK RECORD: no ideas recorded yet")
        return 0
    cache = json.loads(CACHE.read_text())
    rows = []
    for line in IDEAS.read_text().splitlines():
        i = json.loads(line)
        g = grade_one(i, _bars(cache, i["symbol"])) if i["symbol"] in cache else {"status": "no data", "R": None}
        rows.append({**i, **g})
    df = pd.DataFrame(rows)
    done = df[df.status.isin(["win", "loss", "time"])]
    lines = [f"TRACK RECORD ({len(df)} ideas since {df.created_utc.min()[:10]}): "
             f"{(df.status == 'win').sum()} won, {(df.status == 'loss').sum()} lost, {(df.status == 'time').sum()} timed out, "
             f"{(df.status == 'open').sum()} open, {(df.status == 'expired').sum()} never filled, {(df.status == 'pending').sum()} pending"]
    if len(done):
        lines.append(f"   closed trades: avg {done.R.mean():+.2f}R, total {done.R.sum():+.1f}R, win rate {(done.R > 0).mean():.0%}")
        for g, d in done.groupby("grade"):
            lines.append(f"   grade {g}: {len(d)} closed, avg {d.R.mean():+.2f}R, total {d.R.sum():+.1f}R")
        for b, d in done.groupby("basis"):
            lines.append(f"   {b}: {len(d)} closed, avg {d.R.mean():+.2f}R")
    recent = df[df.status.isin(["win", "loss", "time", "expired"])].tail(5)
    for _, r in recent.iterrows():
        lines.append(f"   {r.id} {r.symbol} {r.side} ({r.grade}): {r.status}" + (f" {r.R:+.2f}R" if r.R is not None and r.R == r.R else ""))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "add" and len(sys.argv) >= 3:
        sys.exit(add(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "journal/context.json"))
    if cmd == "grade":
        sys.exit(grade())
    print(__doc__)
    sys.exit(2)
