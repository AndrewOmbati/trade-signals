"""Market data sources. All return a DataFrame indexed by UTC timestamp with open/high/low/close/volume."""
import os

import numpy as np
import pandas as pd

COLS = ["open", "high", "low", "close", "volume"]


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)
    if "volume" not in df:
        df["volume"] = 0.0
    df = df[COLS].astype(float).dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    return df.sort_index()


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    ts = next(c for c in df.columns if c.lower() in ("date", "datetime", "time", "timestamp"))
    return _normalise(df.set_index(ts))


def load_yahoo(ticker: str = "GC=F", period: str = "10y", interval: str = "1d") -> pd.DataFrame:
    import yfinance as yf  # optional dependency

    df = yf.download(ticker, period=period, interval=interval, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return _normalise(df)


def load_oanda(instrument: str = "XAU_USD", granularity: str = "D", count: int = 3000) -> pd.DataFrame:
    import requests

    host = "api-fxpractice.oanda.com" if os.getenv("OANDA_ENV", "practice") == "practice" else "api-fxtrade.oanda.com"
    r = requests.get(
        f"https://{host}/v3/instruments/{instrument}/candles",
        headers={"Authorization": f"Bearer {os.environ['OANDA_API_KEY']}"},
        params={"granularity": granularity, "count": min(count, 5000), "price": "M"},
        timeout=30,
    )
    r.raise_for_status()
    rows = [
        {"time": c["time"], **{k: float(c["mid"][k[0]]) for k in ("open", "high", "low", "close")}, "volume": c["volume"]}
        for c in r.json()["candles"]
        if c["complete"]
    ]
    return _normalise(pd.DataFrame(rows).set_index("time"))


def synthetic(n: int = 2500, start_price: float = 1800.0, seed: int = 7) -> pd.DataFrame:
    """Regime-switching random walk that looks roughly like daily gold. For testing only."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.normal(0.0003, 0.0015, n // 120 + 1), 120)[:n]
    vol = np.repeat(rng.uniform(0.006, 0.015, n // 90 + 1), 90)[:n]
    rets = drift + vol * rng.standard_t(5, n) / np.sqrt(5 / 3)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.r_[start_price, close[:-1]] * (1 + rng.normal(0, 0.001, n))
    span = np.abs(rng.normal(0, vol, n)) * close
    high = np.maximum(open_, close) + span * 0.6
    low = np.minimum(open_, close) - span * 0.6
    idx = pd.bdate_range("2017-01-02", periods=n, tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 0.0}, index=idx)
