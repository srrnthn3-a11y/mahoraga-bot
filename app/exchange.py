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
        """Total portfolio value across all assets, converted to quote_asset (e.g. USDT)."""
        try:
            balance = self.client.fetch_balance()
        except Exception as exc:
            raise ExchangeError(f"Failed to fetch balance: {exc}") from exc

        # OKX exposes a pre-computed total account equity (in USD) directly — use it when available.
        if self.client.id == "okx":
            try:
                data = balance.get("info", {}).get("data", [])
                if data and data[0].get("totalEq"):
                    return Decimal(str(data[0]["totalEq"]))
            except Exception:
                pass

        # Generic fallback: sum every non-zero asset, converting to quote_asset via its ticker price.
        total = Decimal("0")
        for asset, amount in balance.get("total", {}).items():
            if not amount:
                continue
            amount = Decimal(str(amount))
            if asset == quote_asset:
                total += amount
                continue
            try:
                ticker = self.client.fetch_ticker(f"{asset}/{quote_asset}")
                price = Decimal(str(ticker["last"]))
                total += amount * price
            except Exception:
                continue  # asset can't be priced against quote_asset — skip it
        return total

    def place_order(self, symbol: str, side: str, amount: Decimal, reduce_only: bool = False) -> dict:
        params: dict[str, Any] = {}
        if reduce_only:
            params["reduceOnly"] = True
        try:
            raw = self.client.create_order(
                symbol=symbol, type="market", side=side.lower(), amount=float(amount), params=params,
            )
            return {"order_id": str(raw.get("id", "")), "status": raw.get("status", "unknown")}
        except Exception as exc:
            raise ExchangeError(f"Order failed: {exc}") from exc

    def set_leverage(self, symbol: str, leverage: int) -> None:
        """Sets leverage for a perpetual swap symbol. No-op on exchanges/markets that don't support it."""
        try:
            self.client.set_leverage(leverage, symbol)
        except Exception as exc:
            raise ExchangeError(f"Failed to set leverage for {symbol}: {exc}") from exc

    @staticmethod
    def to_swap_symbol(spot_symbol: str) -> str:
        """Converts a spot pair like 'BTC/USDT' into ccxt's perpetual swap notation 'BTC/USDT:USDT'."""
        if ":" in spot_symbol:
            return spot_symbol  # already a swap symbol
        base, quote = spot_symbol.split("/")
        return f"{base}/{quote}:{quote}"
