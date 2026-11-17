"""Turn raw disclosures into ranked setups. Purchases only: research finds sells carry little information
(people sell for taxes, diversification, a house), while buys with their own money are deliberate."""
import datetime as dt
import math
import re
from collections import defaultdict


def score_congress(trades: list[dict], today: dt.date) -> list[dict]:
    buys = [t for t in trades if t["side"] == "BUY"]
    by_ticker = defaultdict(list)
    for t in buys:
        by_ticker[t["ticker"]].append(t)
    sells = defaultdict(int)
    for t in trades:
        if t["side"] == "SELL":
            sells[t["ticker"]] += 1

    out = []
    for tk, ts in by_ticker.items():
        members = {t["member"] for t in ts}
        dollars = sum(t["amount_mid"] for t in ts)
        newest = max(t["tx_date"] for t in ts)
        age = (today - newest).days
        s = 0.0
        s += 25 * (len(members) - 1)                       # several members buying the same stock
        s += 10 * math.log10(max(dollars, 1_000) / 1_000)  # size: $8k -> 9, $75k -> 19, $750k -> 29
        s += 8 if any(t["owner"] in ("self", "joint") for t in ts) else 0
        s += max(0, 20 - age / 2)                          # fresher trade, less of the move already gone
        s -= 10 * sells[tk]                                # other members selling the same name
        why = [f"{len(members)} member(s) bought" + (f": {', '.join(sorted(members))}" if len(members) <= 3 else ""),
               f"~${dollars:,.0f} total disclosed", f"latest trade {newest:%b %d} ({age}d ago)"]
        if sells[tk]:
            why.append(f"{sells[tk]} sell(s) by other members")
        out.append({"ticker": tk, "asset": ts[0]["asset"], "source": "Congress", "score": round(s, 1),
                    "why": why, "links": sorted({t["url"] for t in ts})[:2], "gold": tk in GOLD_TICKERS})
    return sorted(out, key=lambda x: -x["score"])


def grade(score: float) -> str:
    return "STRONG" if score >= 55 else "MODERATE" if score >= 35 else "WEAK"


# Gold-related tickers: bullion ETFs and the larger miners / royalty companies.
GOLD_TICKERS = {"GLD", "IAU", "GLDM", "SGOL", "BAR", "PHYS", "GDX", "GDXJ", "RING", "NEM", "GOLD", "B", "AEM", "KGC",
                "AU", "GFI", "AGI", "RGLD", "FNV", "WPM", "OR", "EGO", "IAG", "NGD", "HMY", "BTG", "CDE", "SSRM", "SAND"}


def score_insiders(buys: list[dict], today: dt.date) -> list[dict]:
    by = defaultdict(list)
    for b in buys:
        by[b["ticker"]].append(b)
    out = []
    for tk, bs in by.items():
        people = {b["insider"] for b in bs}
        value = sum(b["value"] for b in bs)
        roles = {r for b in bs for r in b["roles"]}
        top = any(re.search(r"\b(CEO|Chief Executive|CFO|Chief Financial|President|Chair)", r, re.I) for r in roles)
        # How much each buyer added relative to what they already held. Buyers who held ~nothing before are
        # usually taking part in an IPO, spin-off or private placement, not choosing to buy on the open market.
        priors = [b["owned_after"] - b["shares"] for b in bs]
        new_pos = sum(1 for p in priors if p <= 0.05 * max(b["owned_after"] for b in bs)) / len(bs)
        pct = max((b["shares"] / p for b, p in zip(bs, priors) if p > 0), default=0)
        price = bs[-1]["price"]
        age = (today - max(b["tx_date"] for b in bs)).days
        s = 30 * (len(people) - 1)                          # cluster buying: several insiders at once
        s += 10 * math.log10(max(value, 10_000) / 10_000)    # $10k -> 0, $100k -> 10, $1m -> 20
        s += 15 if top else 5 if roles - {"10% owner"} else 0
        s += min(15, 15 * pct)                               # grew an existing stake meaningfully
        s += max(0, 10 - age)
        s -= 15 if all(b["plan_10b5_1"] for b in bs) else 0  # pre-scheduled plan buys carry less information
        flags = []
        if new_pos >= 0.5:
            s = s * 0.3 - 10
            flags.append("most buyers had no prior stake: likely IPO/offering/placement purchase, not open-market conviction")
        if price < 2:
            s -= 20
            flags.append("penny stock (< $2)")
        stake = "new position" if pct == 0 else f"stake increase up to {pct:.0%}"
        why = [f"{len(people)} insider(s) bought" + (f": {', '.join(sorted(people))[:80]}" if len(people) <= 3 else ""),
               f"${value:,.0f} at ~${price:,.2f}", f"roles: {', '.join(sorted(roles)) or 'n/a'}", stake,
               f"latest buy {max(b['tx_date'] for b in bs):%b %d}"] + [f"CAUTION: {f}" for f in flags]
        out.append({"ticker": tk, "asset": bs[0]["company"], "source": "Insider", "score": round(s, 1), "why": why,
                    "links": [bs[0]["url"]], "gold": tk in GOLD_TICKERS})
    return sorted(out, key=lambda x: -x["score"])
