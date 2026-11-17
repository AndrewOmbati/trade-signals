import datetime as dt

from signals.house import parse_ptr
from signals.insiders import parse_form4
from signals.score import grade, score_congress, score_insiders

FORM4 = """<ownershipDocument>
 <issuer><issuerCik>1</issuerCik><issuerName>Newmont Corp</issuerName><issuerTradingSymbol>NEM</issuerTradingSymbol></issuer>
 <reportingOwner><reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
  <reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer><officerTitle>Chief Executive Officer</officerTitle></reportingOwnerRelationship></reportingOwner>
 <aff10b5One>0</aff10b5One>
 <nonDerivativeTable>
  <nonDerivativeTransaction><transactionDate><value>2026-11-13</value></transactionDate>
   <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
   <transactionAmounts><transactionShares><value>10000</value></transactionShares><transactionPricePerShare><value>52.10</value></transactionPricePerShare>
   <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
   <postTransactionAmounts><sharesOwnedFollowingTransaction><value>30000</value></sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeTransaction>
  <nonDerivativeTransaction><transactionDate><value>2026-11-13</value></transactionDate>
   <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
   <transactionAmounts><transactionShares><value>500</value></transactionShares><transactionPricePerShare><value>53</value></transactionPricePerShare>
   <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
   <postTransactionAmounts><sharesOwnedFollowingTransaction><value>29500</value></sharesOwnedFollowingTransaction></postTransactionAmounts></nonDerivativeTransaction>
 </nonDerivativeTable></ownershipDocument>"""

PTR = """
          SP          argenx SE - American Depositary     P               10/15/2026 11/09/2026        $15,001 -
                      Shares (ARGX) [ST]                                                            $50,000
                      F      S     : New
                      AT&T Inc. (T) [ST]                  P               11/03/2026 11/12/2026        $1,001 - $15,000
                      Berks Cnty PA GO UTX [GS]           S               10/08/2026 10/31/2026        $50,001 -
"""


def test_parse_form4_keeps_only_open_market_buys():
    rows = parse_form4(FORM4, "u")
    assert len(rows) == 1
    r = rows[0]
    assert r["ticker"] == "NEM" and r["value"] == 521_000 and r["roles"] == ["Chief Executive Officer"]


def test_insider_score_rewards_ceo_and_cluster():
    today = dt.date(2026, 11, 17)
    one = parse_form4(FORM4, "u")
    two = one + [{**one[0], "insider": "Roe John", "roles": ["Director"]}]
    s1, s2 = score_insiders(one, today)[0], score_insiders(two, today)[0]
    assert s2["score"] > s1["score"] + 25 and s1["gold"]
    assert grade(s2["score"]) == "STRONG"


def test_parse_ptr_wrapped_rows():
    rows = parse_ptr(PTR)
    assert [(r["ticker"], r["side"], r["amount"]) for r in rows] == [
        ("ARGX", "BUY", "$15,001 - $50,000"), ("T", "BUY", "$1,001 - $15,000")]
    assert rows[0]["owner"] == "spouse" and rows[1]["asset"] == "AT&T Inc."


def test_congress_cluster_beats_single():
    today = dt.date(2026, 11, 17)
    base = dict(side="BUY", tx_date=today - dt.timedelta(days=5), amount_mid=32_500, owner="self", url="u", asset="X")
    trades = [{**base, "ticker": "AAA", "member": "A"}, {**base, "ticker": "AAA", "member": "B"}, {**base, "ticker": "BBB", "member": "C"}]
    r = score_congress(trades, today)
    assert r[0]["ticker"] == "AAA" and r[0]["score"] > r[1]["score"] + 20


def test_gold_briefing_on_synthetic_prices():
    from gold_agent.data import synthetic
    from signals.gold import briefing
    lines = briefing(synthetic(n=400), None)
    assert lines[0].startswith("GOLD (XAU/USD)") and any("Triggers on a daily close" in l or "DAILY SIGNAL" in l for l in lines)


def test_fetch_purchases_time_budget(monkeypatch):
    import signals.insiders as ins
    monkeypatch.setenv("SEC_CONTACT", "test@example.com")
    monkeypatch.setattr(ins, "form4_filings", lambda s, d: [f"f{i}" for i in range(20)])
    monkeypatch.setattr(ins, "_one", lambda s, f: [{"ticker": f}])
    rows, note = ins.fetch_purchases(days=1, today=dt.date(2026, 11, 18), budget_s=60)
    assert len(rows) == 20 and note == "scanned all 20 Form 4 filings"
    rows, note = ins.fetch_purchases(days=1, today=dt.date(2026, 11, 18), budget_s=-1)
    assert rows == [] and "0 of 20" in note


def test_offering_and_penny_buys_are_penalised():
    today = dt.date(2026, 11, 17)
    base = parse_form4(FORM4, "u")[0]
    real = [base, {**base, "insider": "Roe John", "roles": ["Director"]}]
    ipo = [{**b, "ticker": "IPO", "owned_after": b["shares"]} for b in real]          # no prior stake
    penny = [{**b, "ticker": "PNY", "price": 1.0, "value": b["shares"] * 1.0} for b in real]
    r = {x["ticker"]: x for x in score_insiders(real + ipo + penny, today)}
    assert r["NEM"]["score"] > r["IPO"]["score"] + 40 and r["NEM"]["score"] > r["PNY"]["score"] + 15
    assert any("IPO" in w for w in r["IPO"]["why"]) and "new position" in r["IPO"]["why"]
