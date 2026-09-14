"""Market structure: swing points, trend, and break-of-structure / change-of-character events."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data import Candle


@dataclass(frozen=True)
class SwingPoint:
    index: int
    price: Decimal
    kind: str  # "HIGH" | "LOW"


@dataclass(frozen=True)
class StructureResult:
    trend: str  # BULLISH | BEARISH | UNKNOWN
    bos: str | None  # "BULLISH" | "BEARISH" | None
    choch: str | None
    last_swing_high: Decimal | None
    last_swing_low: Decimal | None
    confidence: Decimal


class StructureAnalyzer:
    def __init__(self, left: int = 2, right: int = 2) -> None:
        self.left = left
        self.right = right

    def _swings(self, candles: list[Candle]) -> list[SwingPoint]:
        points: list[SwingPoint] = []
        for i in range(self.left, len(candles) - self.right):
            window = candles[i - self.left : i] + candles[i + 1 : i + self.right + 1]
            current = candles[i]
            if all(current.high >= c.high for c in window):
                points.append(SwingPoint(i, current.high, "HIGH"))
            elif all(current.low <= c.low for c in window):
                points.append(SwingPoint(i, current.low, "LOW"))
        return points

    def analyze(self, candles: list[Candle]) -> StructureResult:
        swings = self._swings(candles)
        highs = [p for p in swings if p.kind == "HIGH"]
        lows = [p for p in swings if p.kind == "LOW"]

        if len(highs) < 2 or len(lows) < 2:
            return StructureResult("UNKNOWN", None, None, None, None, Decimal("0"))

        last_high, prev_high = highs[-1], highs[-2]
        last_low, prev_low = lows[-1], lows[-2]

        higher_high = last_high.price > prev_high.price
        higher_low = last_low.price > prev_low.price
        lower_high = last_high.price < prev_high.price
        lower_low = last_low.price < prev_low.price

        if higher_high and higher_low:
            trend = "BULLISH"
        elif lower_high and lower_low:
            trend = "BEARISH"
        else:
            trend = "UNKNOWN"

        bos = None
        choch = None
        current_price = candles[-1].close
        if trend == "BULLISH" and current_price > last_high.price:
            bos = "BULLISH"
        elif trend == "BEARISH" and current_price < last_low.price:
            bos = "BEARISH"
        elif trend == "BULLISH" and current_price < last_low.price:
            choch = "BEARISH"
        elif trend == "BEARISH" and current_price > last_high.price:
            choch = "BULLISH"

        confidence = Decimal("0.5") + Decimal(min(len(swings), 8)) / Decimal("20")
        return StructureResult(trend, bos, choch, last_high.price, last_low.price, confidence)
