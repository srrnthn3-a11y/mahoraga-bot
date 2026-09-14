"""Generic exchange adapter built on ccxt — works with any ccxt-supported exchange."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import ccxt

from app.data import Candle, MarketSnapshot


class ExchangeError(Exception):
    pass


class ExchangeAdapter:
    def __init__(
        self,
        exchange_id: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str | None = None,
        mode: str = "paper",
    ) -> None:
        if not hasattr(ccxt, exchange_id):
            raise ExchangeError(f"ccxt does not support exchange '{exchange_id}'.")

        self.mode = mode
        config: dict[str, Any] = {"apiKey": api_key, "secret": api_secret, "enableRateLimit": True}
        if api_passphrase:
            config["password"] = api_passphrase

        self.client = getattr(ccxt, exchange_id)(config)
        self.uses_native_sandbox = False
        if mode == "paper" and hasattr(self.client, "set_sandbox_mode"):
            try:
                self.client.set_sandbox_mode(True)
                self.uses_native_sandbox = True
            except Exception:
                pass

    def fetch_snapshot(self, symbol: str, timeframe: str = "15m", limit: int = 100) -> MarketSnapshot:
        try:
            raw = self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as exc:
            raise ExchangeError(f"Failed to fetch OHLCV for {symbol}: {exc}") from exc

        candles = [
            Candle(c[0], Decimal(str(c[1])), Decimal(str(c[2])), Decimal(str(c[3])), Decimal(str(c[4])), Decimal(str(c[5])))
            for c in raw
        ]
        return MarketSnapshot(symbol=symbol, timeframe=timeframe, candles=candles)

    def fetch_equity(self, quote_asset: str = "USDT") -> Decimal:
        try:
            balance = self.client.fetch_balance()
        except Exception as exc:
            raise ExchangeError(f"Failed to fetch balance: {exc}") from exc
        total = balance.get("total", {}).get(quote_asset)
        return Decimal(str(total)) if total else Decimal("0")

    def place_order(self, symbol: str, side: str, amount: Decimal) -> dict:
        try:
            raw = self.client.create_order(symbol=symbol, type="market", side=side.lower(), amount=float(amount))
            return {"order_id": str(raw.get("id", "")), "status": raw.get("status", "unknown")}
        except Exception as exc:
            raise ExchangeError(f"Order failed: {exc}") from exc
