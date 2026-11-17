"""London breakout (1H) and range fade (4H): tune before the cut date, test after it unchanged."""
import itertools
import sys

import pandas as pd

sys.path.insert(0, ".")
from signals.gold_pullback import clean, summary  # noqa: E402
from signals.gold_setups import FadeParams, LondonParams, fade_backtest, london_backtest  # noqa: E402

h1 = clean(pd.read_csv(sys.argv[1], index_col=0, parse_dates=True))
h4 = clean(pd.read_csv(sys.argv[2], index_col=0, parse_dates=True))
CUT = pd.Timestamp("2025-10-23", tz="UTC")
months = lambda t0, t1: (t1 - t0).days / 30.44
KEYS = ("trades", "win_%", "avg_R", "PF", "max_DD_R", "worst_streak")


def split(t, start, end):
    i, o = t[t.signal_time < CUT], t[t.signal_time >= CUT]
    si, so = summary(i, 1), summary(o, 1)
    return {"/mo_in": round(len(i) / months(start, CUT), 1), **{f"{k}_in": si.get(k) for k in ("win_%", "avg_R", "PF")},
            "/mo_out": round(len(o) / months(CUT, end), 1), **{f"{k}_out": so.get(k) for k in ("win_%", "avg_R", "PF")}}


print("== LONDON BREAKOUT (1H)")
rows = []
for rt, trend, maxw in itertools.product([1.0, 1.5, 2.0], [False, True], [0.5, 0.7]):
    t = london_backtest(h1, LondonParams(r_target=rt, trend=trend, max_w=maxw))
    rows.append({"r": rt, "trend": trend, "max_w": maxw, **split(t, h1.index[0], h1.index[-1])})
print(pd.DataFrame(rows).to_string(index=False))

print("\n== RANGE FADE (4H)")
rows = []
for adxm, rsi, stop in itertools.product([20, 25], [30, 35], [1.0, 1.5]):
    t = fade_backtest(h4, FadeParams(adx_max=adxm, rsi_lo=rsi, stop_atr=stop))
    rows.append({"adx<": adxm, "rsi": rsi, "stop_atr": stop, **split(t, h4.index[0], h4.index[-1])})
print(pd.DataFrame(rows).to_string(index=False))
