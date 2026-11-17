"""SEC Form 4 insider transactions from EDGAR. The SEC requires a declared contact in the User-Agent:
set the SEC_CONTACT environment variable (an email address)."""
import datetime as dt
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

ARCHIVES = "https://www.sec.gov/Archives"


def _session() -> requests.Session:
    contact = os.environ.get("SEC_CONTACT")
    if not contact:
        raise RuntimeError("SEC_CONTACT is not set; the SEC refuses requests without a contact address")
    s = requests.Session()
    s.headers["User-Agent"] = f"signals-scanner {contact}"
    return s


def _get(s: requests.Session, url: str) -> requests.Response:
    for attempt in range(4):
        r = s.get(url, timeout=30)
        time.sleep(0.12)  # stay under the SEC's 10 requests/second limit
        if r.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        return r
    return r


def form4_filings(s: requests.Session, day: dt.date) -> list[str]:
    q = (day.month - 1) // 3 + 1
    r = _get(s, f"{ARCHIVES}/edgar/daily-index/{day.year}/QTR{q}/form.{day:%Y%m%d}.idx")
    if r.status_code == 404:
        return []  # weekend / holiday
    r.raise_for_status()
    files = []
    for line in r.text.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 5 and parts[0] == "4":
            files.append(parts[-1])
    return sorted(set(files))


def _v(node, path):
    el = node.find(path) if node is not None else None
    return (el.text or "").strip() if el is not None and el.text else ""


def parse_form4(xml_text: str, url: str = "") -> list[dict]:
    """Open-market purchases (transaction code P) from one Form 4 ownershipDocument."""
    root = ET.fromstring(xml_text)
    ticker = _v(root, "issuer/issuerTradingSymbol").upper()
    if not ticker or ticker in ("NONE", "N/A"):
        return []
    company = _v(root, "issuer/issuerName")
    owners, roles = [], set()
    for ro in root.findall("reportingOwner"):
        owners.append(_v(ro, "reportingOwnerId/rptOwnerName"))
        rel = ro.find("reportingOwnerRelationship")
        flag = lambda tag: _v(rel, tag).lower() in ("1", "true")
        if flag("isOfficer"):
            roles.add(_v(rel, "officerTitle") or "Officer")
        if flag("isDirector"):
            roles.add("Director")
        if flag("isTenPercentOwner"):
            roles.add("10% owner")
    plan = _v(root, "aff10b5One").lower() in ("1", "true")
    out = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        if _v(t, "transactionCoding/transactionCode") != "P" or _v(t, "transactionAmounts/transactionAcquiredDisposedCode/value") != "A":
            continue
        try:
            shares = float(_v(t, "transactionAmounts/transactionShares/value"))
            price = float(_v(t, "transactionAmounts/transactionPricePerShare/value") or 0)
            after = float(_v(t, "postTransactionAmounts/sharesOwnedFollowingTransaction/value") or 0)
        except ValueError:
            continue
        if price <= 0:
            continue
        out.append({
            "ticker": ticker, "company": company, "insider": " / ".join(owners), "roles": sorted(roles),
            "tx_date": dt.date.fromisoformat(_v(t, "transactionDate/value")[:10]), "shares": shares, "price": price,
            "value": shares * price, "owned_after": after, "plan_10b5_1": plan, "url": url,
        })
    return out


def fetch_purchases(days: int = 2, today: dt.date | None = None) -> list[dict]:
    """Purchases from Form 4s filed on the last `days` business days."""
    s, today = _session(), today or dt.date.today()
    rows, d, seen = [], today - dt.timedelta(days=1), 0
    while seen < days:
        if d.weekday() < 5:
            seen += 1
            for f in form4_filings(s, d):
                r = _get(s, f"{ARCHIVES}/{f}")
                m = re.search(r"<XML>\s*(.*?)\s*</XML>", r.text, re.S) if r.ok else None
                if not m:
                    continue
                try:
                    rows += parse_form4(m.group(1), f"{ARCHIVES}/{f}")
                except ET.ParseError:
                    continue
        d -= dt.timedelta(days=1)
    return rows
