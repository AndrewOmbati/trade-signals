# Trade signals: insider and congressional purchases

Daily report of the top 5 setups from:
- **SEC Form 4**: open-market purchases by company insiders (filed within 2 business days of the trade)
- **US House periodic transaction reports**: stock purchases by members of Congress (disclosed up to 45 days late)

Gold-related tickers (bullion ETFs and miners) are flagged separately.

Ranking favours several people buying the same stock, larger purchases, CEO/CFO buyers, meaningful stake increases
and recent trades. Sells are ignored except as a penalty. Each signal is graded STRONG / MODERATE / WEAK;
the top 5 are always shown, even on days with no strong setups.

```bash
pip install requests          # also needs pdftotext (poppler-utils)
export SEC_CONTACT=you@example.com   # required by the SEC's fair-access policy
python -m signals                    # text report
python -m signals --json
python -m pytest tests
```

Research leads, not financial advice.
