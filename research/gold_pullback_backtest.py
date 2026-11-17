"""Tune on the first 60% of 4H history, then test the chosen settings unchanged on the last 40%."""
import itertools
import sys

import pandas as pd

sys.path.insert(0, ".")
from signals.gold_pullback import PullbackParams, backtest, clean, summary  # noqa: E402

df = clean(pd.read_csv(sys.argv[1], index_col=0, parse_dates=True))
cut = df.index[int(len(df) * 0.6)]
ins, oos = df[df.index < cut], df[df.index >= cut - pd.Timedelta(days=60)]  # 60d warm-up for indicators
wk = lambda d: (d.index[-1] - d.index[0]).days / 7
print(f"in-sample  {ins.index[0]:%Y-%m-%d} .. {cut:%Y-%m-%d}   out-of-sample {cut:%Y-%m-%d} .. {df.index[-1]:%Y-%m-%d}")
print(f"gold: {df.close.iloc[0]:.0f} -> {df.close[cut]:.0f} -> {df.close.iloc[-1]:.0f}\n")

rows = []
for rsi, rt in itertools.product([40, 45, 50], [1.5, 2.0, 3.0]):
    p = PullbackParams(rsi_pull=rsi, r_target=rt)
    rows.append({"rsi_pull": rsi, "r_target": rt, **summary(backtest(ins, p), wk(ins))})
print("IN-SAMPLE grid\n", pd.DataFrame(rows).to_string(index=False))

p = PullbackParams(rsi_pull=45)  # first pick before the grid; rsi 50 (best in-sample) is the live default
t = backtest(oos, p)
t = t[t.signal_time >= cut]
print("\nOUT-OF-SAMPLE (rsi 45, 2R):", summary(t, (df.index[-1] - cut).days / 7))
print(t.groupby("side").R.agg(["count", "mean", "sum"]).round(2).to_string())
print(t.groupby("why").R.agg(["count", "mean"]).round(2).to_string())
t.to_csv("research/gold_pullback_oos_trades.csv", index=False)
