"""SEC Form 4 insider transactions from EDGAR. The SEC requires a declared contact in the User-Agent:
set the SEC_CONTACT environment variable (an email address)."""
import datetime as dt
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


class _RateLimiter:
    """Shared across threads: at most `rate` requests per second (the SEC allows 10)."""

    def __init__(self, rate: float = 8.0):
        self.gap, self.next, self.lock = 1.0 / rate, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.gap
        time.sleep(max(0.0, t - now))


_limit = _RateLimiter()


def _get(s: requests.Session, url: str) -> requests.Response:
    r = None
    for attempt in range(4):
        _limit.wait()
        try:
            r = s.get(url, timeout=30)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 503):
            time.sleep(2 ** attempt)
            continue
        return r
    if r is None:
        raise requests.ConnectionError(url)
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


def _one(s: requests.Session, f: str) -> list[dict]:
    try:
        r = _get(s, f"{ARCHIVES}/{f}")
    except requests.RequestException:
        return []
    m = re.search(r"<XML>\s*(.*?)\s*</XML>", r.text, re.S) if r.ok else None
    if not m:
        return []
    try:
        return parse_form4(m.group(1), f"{ARCHIVES}/{f}")
    except (ET.ParseError, ValueError):
        return []


def fetch_purchases(days: int = 1, today: dt.date | None = None, budget_s: float = 480, workers: int = 8) -> tuple[list[dict], str]:
    """Purchases from Form 4s filed on the last `days` business days.
    Stops after `budget_s` seconds so a scheduled run always finishes; returns (rows, coverage note)."""
    s, today = _session(), today or dt.date.today()
    files, d, seen = [], today - dt.timedelta(days=1), 0
    while seen < days:
        if d.weekday() < 5:
            seen += 1
            files += form4_filings(s, d)
        d -= dt.timedelta(days=1)
    files = sorted(set(files))
    deadline = time.monotonic() + budget_s
    skipped = 0
    lock = threading.Lock()

    def task(f):
        nonlocal skipped
        if time.monotonic() > deadline:
            with lock:
                skipped += 1
            return []
        return _one(s, f)

    rows = []
    with ThreadPoolExecutor(workers) as ex:
        for got in ex.map(task, files):
            rows += got
    if skipped:
        return rows, f"insider scan hit its time limit: {len(files) - skipped} of {len(files)} Form 4 filings checked"
    return rows, f"scanned all {len(files)} Form 4 filings"
