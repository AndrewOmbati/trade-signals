"""Daily signal report: top setups from SEC insider purchases and House trades, gold-related ones flagged."""
import argparse
import datetime as dt
import json
import sys

from . import gold as goldmod, house, insiders
from .score import grade, score_congress, score_insiders


def build(days_congress: int, days_insider: int, top: int, today: dt.date) -> dict:
    notes, ranked = [], []
    try:
        buys, cov = insiders.fetch_purchases(days_insider, today)
        ranked += score_insiders(buys, today)
        if "time limit" in cov:
            notes.append(cov)
    except Exception as e:  # keep going with the other source
        notes.append(f"Insider data unavailable: {e}")
    try:
        ranked += score_congress(house.fetch_trades(today - dt.timedelta(days=days_congress)), today)
    except Exception as e:
        notes.append(f"House data unavailable: {e}")
    ranked.sort(key=lambda x: -x["score"])
    gold = [r for r in ranked if r.get("gold")]
    try:
        gold_lines = goldmod.briefing(goldmod.fetch_daily())
    except Exception as e:
        gold_lines = [f"GOLD: price data unavailable today ({e})"]
    return {"date": str(today), "gold_briefing": gold_lines, "top": ranked[: max(top, 5)], "gold": gold[:3],
            "notes": notes, "candidates": len(ranked)}


def render(rep: dict) -> str:
    out = rep["gold_briefing"] + ["", f"STOCK SIGNALS ({rep['candidates']} candidates screened from insider and Congress filings)", ""]
    for i, s in enumerate(rep["top"], 1):
        out.append(f"{i}. {s['ticker']} - {s['asset'][:40]} | {s['source']} | {grade(s['score'])} ({s['score']})")
        out += [f"   - {w}" for w in s["why"]] + [f"   {s['links'][0]}", ""]
    out.append("Gold-related insider/Congress trades: " + ("; ".join(f"{g['ticker']} ({g['source']}, {grade(g['score'])})" for g in rep["gold"])
                                   if rep["gold"] else "none in today's filings"))
    out += [f"Note: {n}" for n in rep["notes"]]
    out.append("Research leads, not financial advice. Congress trades are disclosed up to 45 days late.")
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(prog="signals")
    p.add_argument("--congress-days", type=int, default=30)
    p.add_argument("--insider-days", type=int, default=1, help="business days of Form 4 filings to scan")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    rep = build(a.congress_days, a.insider_days, a.top, dt.date.today())
    print(json.dumps(rep, default=str, indent=2) if a.json else render(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
