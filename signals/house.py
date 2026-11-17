"""US House periodic transaction reports (PTRs) from the Clerk of the House. Public, no key needed."""
import datetime as dt
import io
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import requests

BASE = "https://disclosures-clerk.house.gov/public_disc"
UA = {"User-Agent": "congress-trade-scanner/1.0"}

# A trade row: "[owner] <asset start>   P   10/15/2026 11/09/2026   $1,001 - $15,000".
# Long asset names wrap, so "(TICKER) [ST]" can sit on the same line or one of the next few.
ROW = re.compile(
    r"^\s*(?:(?P<owner>SP|JT|DC)\s+)?(?P<asset>.*?)\s+(?P<type>P|S \(partial\)|S|E)\s+"
    r"(?P<tx>\d\d/\d\d/\d{4})\s+(?P<notif>\d\d/\d\d/\d{4})\s+(?P<amount>\$[\d,]+(?:\s*-\s*\$[\d,]+)?\s*-?|Over \$[\d,]+)"
)
TICKER = re.compile(r"\((?P<ticker>[A-Z][A-Z.\-]{0,6})\)\s*\[(?P<kind>[A-Z]{2})\]")
AMOUNT_MID = {  # midpoint of the disclosure bracket, used for ranking
    1_001: 8_000, 15_001: 32_500, 50_001: 75_000, 100_001: 175_000, 250_001: 375_000,
    500_001: 750_000, 1_000_001: 3_000_000, 5_000_001: 15_000_000, 25_000_001: 40_000_000, 50_000_001: 60_000_000,
}


def filings(year: int, since: dt.date) -> list[dict]:
    z = requests.get(f"{BASE}/financial-pdfs/{year}FD.zip", headers=UA, timeout=60)
    z.raise_for_status()
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(z.content)).read(f"{year}FD.xml"))
    out = []
    for m in root.findall("Member"):
        if m.findtext("FilingType") != "P":
            continue
        d = dt.datetime.strptime(m.findtext("FilingDate"), "%m/%d/%Y").date()
        if d >= since:
            name = " ".join(x for x in (m.findtext("First"), m.findtext("Last")) if x)
            out.append({"member": name, "district": m.findtext("StateDst"), "filed": d, "doc_id": m.findtext("DocID"), "year": year})
    return out


def parse_ptr(text: str) -> list[dict]:
    trades, lines = [], text.splitlines()
    rows = [i for i, l in enumerate(lines) if ROW.search(l)]
    for n, i in enumerate(rows):
        m = ROW.search(lines[i])
        stop = min(rows[n + 1] if n + 1 < len(rows) else len(lines), i + 4)
        block = lines[i:stop]
        tk = next((TICKER.search(l) for l in block if TICKER.search(l)), None)
        if not tk or tk["kind"] != "ST":
            continue  # bonds, funds, options etc.
        asset = " ".join([m["asset"].strip()] + [l.split("(" + tk["ticker"] + ")")[0].strip() for l in block[1:] if "(" + tk["ticker"] + ")" in l])
        amount = m["amount"].strip()
        if amount.endswith("-"):  # upper bound wrapped onto the next line
            nxt = next((re.search(r"\$[\d,]+", l[len(l) // 2:]) for l in block[1:] if re.search(r"\$[\d,]+", l[len(l) // 2:])), None)
            amount = f"{amount} {nxt.group(0)}" if nxt else amount
        low = int(re.search(r"\$([\d,]+)", amount).group(1).replace(",", ""))
        trades.append({
            "ticker": tk["ticker"], "asset": TICKER.sub("", asset).strip(" -"),
            "owner": {"SP": "spouse", "JT": "joint", "DC": "child"}.get(m["owner"], "self"),
            "side": {"P": "BUY", "E": "EXCHANGE"}.get(m["type"], "SELL"),
            "tx_date": dt.datetime.strptime(m["tx"], "%m/%d/%Y").date(), "amount": amount,
            "amount_mid": AMOUNT_MID.get(low, low),
        })
    return trades


def fetch_trades(since: dt.date) -> list[dict]:
    rows = []
    for year in sorted({since.year, dt.date.today().year}):
        for f in filings(year, since):
            r = requests.get(f"{BASE}/ptr-pdfs/{f['year']}/{f['doc_id']}.pdf", headers=UA, timeout=60)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                continue  # paper filings are scanned images; skipped
            with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
                tmp.write(r.content); tmp.flush()
                text = subprocess.run(["pdftotext", "-layout", tmp.name, "-"], capture_output=True, text=True).stdout
            for t in parse_ptr(text):
                rows.append({**t, "member": f["member"], "district": f["district"], "filed": f["filed"],
                             "chamber": "House", "url": f"{BASE}/ptr-pdfs/{f['year']}/{f['doc_id']}.pdf"})
    return rows
