"""Live spot availability overlay; never rewrites the frozen research universe."""
import threading
import time


class SpotCatalog:
    def __init__(self):
        self.statuses = {}
        self.checked_at = None
        self.last_error = None
        self.last_attempt = None
        self.lock = threading.Lock()

    def refresh(self, fetch, *, now=None, force=False):
        now = time.time() if now is None else now
        if not self.lock.acquire(blocking=False):
            return False
        try:
            if not force and self.last_attempt is not None and now-self.last_attempt < 3600:
                return False
            self.last_attempt = now
            try:
                data = fetch()
                rows = data["symbols"]
                if not isinstance(rows, list) or not rows:
                    raise ValueError("empty_spot_catalog")
                statuses = {}
                for row in rows:
                    symbol, status = row["symbol"], row["status"]
                    if (not isinstance(symbol, str) or not symbol or symbol in statuses
                            or not isinstance(status, str) or not status):
                        raise ValueError("invalid_spot_catalog")
                    statuses[symbol] = ("SPOT_DISABLED" if status == "TRADING"
                                        and row.get("isSpotTradingAllowed") is False else status)
                self.statuses = statuses
                self.checked_at = now
                self.last_error = None
                return True
            except Exception as exc:
                # Keep last known statuses. An API failure is not a delisting.
                self.last_error = type(exc).__name__
                return False
        finally:
            self.lock.release()

    def eligible(self, symbol):
        # Missing/unknown is not proof of unavailability; normal candle checks
        # still apply. Only an explicit non-TRADING status excludes a symbol.
        return self.statuses.get(symbol, "TRADING") == "TRADING"

    def select(self, symbols):
        statuses = self.statuses
        return [s for s in dict.fromkeys(symbols) if statuses.get(s, "TRADING") == "TRADING"]

    def snapshot(self, symbols):
        statuses = self.statuses
        symbols = list(dict.fromkeys(symbols))
        return {"checked_at_epoch": self.checked_at, "last_error": self.last_error,
                "known_symbols": len(statuses), "configured_symbols": len(symbols),
                "eligible_symbols": len(self.select(symbols)),
                "excluded": {s: statuses[s] for s in symbols
                             if s in statuses and statuses[s] != "TRADING"}}
