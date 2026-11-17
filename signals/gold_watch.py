"""Run every 4 hours on weekdays: prints 'NO ALERT' or the alert text for a push notification."""
import sys

from . import gold


def main() -> int:
    df = gold.fetch_daily()
    df4, price = gold.fetch_4h()
    lines = gold.watch(df, df4, price)
    print("\n".join(lines) if lines else f"NO ALERT (gold ~${price:,.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
