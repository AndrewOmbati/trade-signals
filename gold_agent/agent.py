"""The live/paper agent: each cycle it pulls fresh bars, evaluates the latest completed bar and acts through a broker."""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from .broker import Broker
from .config import AgentConfig
from .risk import DrawdownGuard, position_size
from .strategy import Action, Decision, decide, features

log = logging.getLogger("gold_agent")


class GoldAgent:
    def __init__(self, cfg: AgentConfig, broker: Broker, fetch: Callable[[], pd.DataFrame], journal: str = "journal.jsonl"):
        self.cfg, self.broker, self.fetch, self.journal = cfg, broker, fetch, journal
        self.guard = DrawdownGuard(cfg.risk)

    def step(self) -> dict:
        df = self.fetch()
        bar = features(df, self.cfg.strategy).iloc[-1]
        price = float(bar["close"])

        stop_msg = self.broker.on_bar(bar)
        equity, pos = self.broker.equity(), self.broker.position()
        self.guard.update(equity)

        d = decide(bar, pos, self.cfg.strategy, self.cfg.risk)
        if self.guard.tripped:
            d = Decision(Action.EXIT, "drawdown kill switch") if pos else Decision(Action.HOLD, "kill switch active: no new trades")

        executed = None
        if d.action == Action.EXIT and pos:
            self.broker.close(price, d.reason)
            executed = f"closed {pos:+.2f} oz"
        elif d.action in (Action.ENTER_LONG, Action.ENTER_SHORT) and not pos:
            side = 1 if d.action == Action.ENTER_LONG else -1
            units = position_size(equity, price, d.stop_distance, self.cfg.risk)
            if units > 0:
                stop = price - side * d.stop_distance
                target = price + side * d.target_distance if d.target_distance else None
                filled = self.broker.market_order(side * units, price, stop, target)
                executed = None if not filled else f"opened {filled:+.2f} oz @~{price:.2f}, stop {stop:.2f}" + (f", target {target:.2f}" if target else "")

        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bar": str(bar.name), "price": round(price, 2), "rsi": round(float(bar["rsi"]), 1),
            "atr": round(float(bar["atr"]), 2), "equity": round(self.broker.equity(), 2),
            "position": self.broker.position(), "action": d.action.value, "reason": d.reason,
            "executed": executed, "stop_event": stop_msg,
        }
        with open(self.journal, "a") as fh:
            fh.write(json.dumps(record) + "\n")
        log.info("%s | %s | %s", d.action.value, d.reason, executed or "no order")
        return record

    def run(self, interval_s: int, max_cycles: int | None = None):
        n = 0
        while max_cycles is None or n < max_cycles:
            try:
                self.step()
            except Exception:
                log.exception("cycle failed; will retry next interval")
            n += 1
            if max_cycles is None or n < max_cycles:
                time.sleep(interval_s)
