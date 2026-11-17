"""Execution backends. PaperBroker is the default; OandaBroker talks to OANDA's v20 REST API (practice by default)."""
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path

import requests


class Broker(ABC):
    @abstractmethod
    def equity(self) -> float: ...

    @abstractmethod
    def position(self) -> float:
        """Signed units (ounces): + long, - short, 0 flat."""

    @abstractmethod
    def market_order(self, units: float, price: float, stop: float, target: float | None) -> float:
        """Returns the signed units actually filled (0 if the order was skipped)."""

    @abstractmethod
    def close(self, price: float, reason: str) -> None: ...

    def on_bar(self, bar) -> str | None:
        """Hook for simulated brokers to process stops on a new bar. Real brokers handle this server-side."""
        return None


class PaperBroker(Broker):
    """Simulated account persisted to a JSON file so the agent can be restarted (e.g. from cron)."""

    def __init__(self, state_file: str = "paper_state.json", starting_equity: float = 10_000.0, spread: float = 0.30):
        self.path, self.half_spread = Path(state_file), spread / 2
        if self.path.exists():
            self.s = json.loads(self.path.read_text())
        else:
            self.s = {"cash": starting_equity, "units": 0.0, "entry": 0.0, "stop": None, "target": None, "last_price": 0.0, "log": []}
            self._save()

    def _save(self):
        self.path.write_text(json.dumps(self.s, indent=2))

    def equity(self):
        return self.s["cash"] + self.s["units"] * (self.s["last_price"] - self.s["entry"])

    def position(self):
        return self.s["units"]

    def market_order(self, units, price, stop, target):
        side = 1 if units > 0 else -1
        fill = price + side * self.half_spread
        self.s.update(units=units, entry=fill, stop=stop, target=target, last_price=price)
        self.s["log"].append({"event": "open", "units": units, "fill": fill, "stop": stop, "target": target})
        self._save()
        return units

    def close(self, price, reason):
        u = self.s["units"]
        if not u:
            return
        fill = price - (1 if u > 0 else -1) * self.half_spread
        pnl = u * (fill - self.s["entry"])
        self.s["cash"] += pnl
        self.s["log"].append({"event": "close", "units": u, "fill": fill, "pnl": round(pnl, 2), "reason": reason})
        self.s.update(units=0.0, entry=0.0, stop=None, target=None, last_price=price)
        self._save()

    def on_bar(self, bar):
        self.s["last_price"] = float(bar["close"])
        u = self.s["units"]
        msg = None
        if u:
            long = u > 0
            stop, tgt = self.s["stop"], self.s["target"]
            if stop is not None and (bar["low"] <= stop if long else bar["high"] >= stop):
                self.close(stop, "stop loss"); msg = f"stop hit at {stop:.2f}"
            elif tgt is not None and (bar["high"] >= tgt if long else bar["low"] <= tgt):
                self.close(tgt, "take profit"); msg = f"target hit at {tgt:.2f}"
        self._save()
        return msg


class OandaBroker(Broker):
    """OANDA v20. Uses the practice server unless OANDA_ENV=live. Stops/targets are attached to the order server-side."""

    def __init__(self, instrument: str = "XAU_USD"):
        self.live = os.getenv("OANDA_ENV", "practice") == "live"
        host = "api-fxtrade.oanda.com" if self.live else "api-fxpractice.oanda.com"
        self.base = f"https://{host}/v3/accounts/{os.environ['OANDA_ACCOUNT_ID']}"
        self.h = {"Authorization": f"Bearer {os.environ['OANDA_API_KEY']}", "Content-Type": "application/json"}
        self.instrument = instrument

    def _req(self, method, path, **kw):
        r = requests.request(method, self.base + path, headers=self.h, timeout=30, **kw)
        r.raise_for_status()
        return r.json()

    def equity(self):
        return float(self._req("GET", "/summary")["account"]["NAV"])

    def position(self):
        try:
            p = self._req("GET", f"/positions/{self.instrument}")["position"]
        except requests.HTTPError:
            return 0.0
        return float(p["long"]["units"]) + float(p["short"]["units"])

    def market_order(self, units, price, stop, target):
        order = {
            "type": "MARKET", "instrument": self.instrument, "units": f"{units:.2f}",
            "timeInForce": "FOK", "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": f"{stop:.2f}"},
        }
        if target:
            order["takeProfitOnFill"] = {"price": f"{target:.2f}"}
        self._req("POST", "/orders", json={"order": order})
        return units

    def close(self, price, reason):
        u = self.position()
        if u:
            side = "longUnits" if u > 0 else "shortUnits"
            self._req("PUT", f"/positions/{self.instrument}/close", json={side: "ALL"})
