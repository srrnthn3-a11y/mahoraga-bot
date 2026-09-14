"""Market data models and regime detection (trending / ranging / volatile)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    timeframe: str
    candles: list[Candle]

    @property
    def latest(self) -> Candle | None:
        return self.candles[-1] if self.candles else None


@dataclass(frozen=True)
class RegimeResult:
    regime: str  # TRENDING | RANGING | VOLATILE | UNCERTAIN
    confidence: Decimal
    reason: str


def _true_range(prev_close: Decimal, candle: Candle) -> Decimal:
    return max(
        candle.high - candle.low,
        abs(candle.high - prev_close),
        abs(candle.low - prev_close),
    )


class RegimeDetector:
    """
    Classifies market regime from recent candles using:
    - ATR (average true range) relative to price, for volatility
    - net directional move vs total path traveled, for trend strength
    """

    def __init__(self, lookback: int = 20) -> None:
        self.lookback = lookback

    def detect(self, candles: list[Candle]) -> RegimeResult:
        if len(candles) < self.lookback + 1:
            return RegimeResult("UNCERTAIN", Decimal("0"), "Not enough candles.")

        window = candles[-self.lookback :]
        trs = [
            _true_range(window[i - 1].close, window[i])
            for i in range(1, len(window))
        ]
        atr = sum(trs) / Decimal(len(trs))
        avg_price = sum(c.close for c in window) / Decimal(len(window))
        volatility_ratio = atr / avg_price if avg_price else Decimal("0")

        net_move = abs(window[-1].close - window[0].close)
        total_path = sum(abs(window[i].close - window[i - 1].close) for i in range(1, len(window)))
        efficiency = net_move / total_path if total_path else Decimal("0")

        if volatility_ratio > Decimal("0.02"):
            return RegimeResult(
                "VOLATILE", min(Decimal("0.9"), volatility_ratio * 20),
                f"ATR/price ratio {volatility_ratio:.4f} indicates high volatility.",
            )
        if efficiency > Decimal("0.5"):
            return RegimeResult(
                "TRENDING", min(Decimal("0.9"), efficiency),
                f"Price efficiency {efficiency:.2f} indicates directional trend.",
            )
        if efficiency < Decimal("0.25"):
            return RegimeResult(
                "RANGING", min(Decimal("0.9"), Decimal("1") - efficiency),
                f"Price efficiency {efficiency:.2f} indicates choppy/ranging conditions.",
            )
        return RegimeResult("UNCERTAIN", Decimal("0.4"), "Mixed signals between trend and range.")
