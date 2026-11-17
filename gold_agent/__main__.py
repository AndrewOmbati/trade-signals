import argparse
import json
import logging
import os
import sys

from .config import AgentConfig
from . import data


def load_data(args):
    if args.source == "csv":
        df = data.load_csv(args.csv)
        df[["open", "high", "low", "close"]] /= args.price_scale
        return df
    if args.source == "yahoo":
        df = data.load_yahoo(args.ticker, args.period, args.interval)
        # Yahoo includes the still-forming bar; the live agent must only act on completed bars.
        return df.iloc[:-1] if args.cmd == "trade" else df
    if args.source == "mt5":
        from .mt5 import load_mt5
        return load_mt5(args.symbol, args.timeframe, args.bars)
    if args.source == "oanda":
        return data.load_oanda("XAU_USD", args.granularity)
    return data.synthetic()


def main(argv=None):
    p = argparse.ArgumentParser(prog="gold_agent", description="Gold (XAU/USD) trading agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("backtest", "trade"):
        s = sub.add_parser(name)
        s.add_argument("--source", choices=["synthetic", "csv", "yahoo", "oanda", "mt5"], default="synthetic")
        s.add_argument("--csv"); s.add_argument("--ticker", default="GC=F")
        s.add_argument("--period", default="10y"); s.add_argument("--interval", default="1d")
        s.add_argument("--granularity", default="D")
        s.add_argument("--symbol", default="XAUUSD", help="MT5 symbol name (brokers vary: XAUUSD, GOLD, XAUUSD.m)")
        s.add_argument("--timeframe", default="D1", help="MT5 timeframe: M15, H1, H4, D1 ...")
        s.add_argument("--bars", type=int, default=3000, help="MT5 bars to load")
        s.add_argument("--price-scale", type=float, default=1.0, help="divide CSV prices by this (some datasets store x100)")
        s.add_argument("--equity", type=float, default=10_000.0)
        s.add_argument("--risk", type=float, default=0.01, help="fraction of equity risked per trade")
        s.add_argument("--no-shorts", action="store_true")
    b = sub.choices["backtest"]
    b.add_argument("--trades", action="store_true", help="print the trade list")
    b.add_argument("--plot", help="save equity curve PNG to this path")
    t = sub.choices["trade"]
    t.add_argument("--broker", choices=["paper", "oanda", "mt5"], default="paper")
    t.add_argument("--state", default="paper_state.json")
    t.add_argument("--loop", type=int, default=0, help="seconds between cycles (0 = run once, e.g. from cron)")
    t.add_argument("--i-understand-this-is-real-money", dest="live_ok", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = AgentConfig(starting_equity=args.equity)
    cfg.risk.risk_per_trade = args.risk
    cfg.strategy.allow_shorts = not args.no_shorts

    if args.cmd == "backtest":
        from .backtest import run_backtest
        res = run_backtest(load_data(args), cfg)
        print(json.dumps(res.stats, indent=2))
        if args.trades:
            for tr in res.trades:
                print(f"{tr.entry_time.date()} {'LONG ' if tr.side > 0 else 'SHORT'} {tr.units:7.2f}oz "
                      f"{tr.entry:9.2f} -> {tr.exit:9.2f} {tr.exit_time.date()}  pnl {tr.pnl:9.2f}  ({tr.reason})")
        if args.plot:
            import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(10, 4)); res.equity.plot(ax=ax, title="Gold agent equity")
            fig.tight_layout(); fig.savefig(args.plot, dpi=120)
        return 0

    from .agent import GoldAgent
    from .broker import OandaBroker, PaperBroker
    if args.broker == "mt5":
        from .mt5 import MT5Broker
        broker = MT5Broker(args.symbol)
        if broker.is_real_account() and not args.live_ok:
            sys.exit("Refusing to trade a REAL MT5 account without --i-understand-this-is-real-money (use a demo account first)")
    elif args.broker == "oanda":
        if os.getenv("OANDA_ENV") == "live" and not args.live_ok:
            sys.exit("Refusing to trade a live OANDA account without --i-understand-this-is-real-money")
        broker = OandaBroker()
    else:
        broker = PaperBroker(args.state, args.equity, cfg.costs.spread)
    agent = GoldAgent(cfg, broker, lambda: load_data(args))
    if args.loop:
        agent.run(args.loop)
    else:
        print(json.dumps(agent.step(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
