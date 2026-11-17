"""Run at 07:05 London on weekdays: prints 'NO ALERT ...' or today's London-breakout pending orders."""
import sys

from .gold import _fetch
from .gold_pullback import clean
from .gold_setups import london_today


def main() -> int:
    h1 = clean(_fetch("1h", 2000))  # ~2.5 months: enough for the 50-day EMA and 14-day ATR
    lines = london_today(h1)
    print("\n".join(lines) if lines else "NO ALERT (no London breakout plan today: range size or trend filter)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
