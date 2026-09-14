"""
Mahoraga strategy: adapts to market regime instead of trading one fixed setup.

- Reads current regime (trending / ranging / volatile)
- Selects which structural signals to trust for that regime
- Reads structure (trend, BOS, CHoCH) to decide direction
- Builds a TradeRequest with stop beyond the last swing and take-profit
  set to satisfy the minimum RRR — final approval still goes through RiskEngine
"""

from __future__ import annotations

from decimal import Decimal

from app.data import RegimeResult
from app.structure import StructureResult
from app.risk import TradeRequest

REGIME_TRUST = {
    # Which structural signals Mahoraga trusts, per regime.
    "TRENDING": ("bos",),
    "RANGING": ("choch",),
    "VOLATILE": (),  # too noisy — sit out
    "UNCERTAIN": (),
}


def decide(
    regime: RegimeResult,
    structure: StructureResult,
    current_price: Decimal,
    min_rrr: Decimal,
    stop_buffer_percent: Decimal = Decimal("0.3"),
) -> tuple[TradeRequest | None, str]:
    """Returns (TradeRequest or None, human-readable reason)."""

    trusted_signals = REGIME_TRUST.get(regime.regime, ())
    if not trusted_signals:
        return None, f"Regime '{regime.regime}' is not tradeable for Mahoraga right now."

    if regime.confidence < Decimal("0.5"):
        return None, f"Regime confidence {regime.confidence:.2f} too low to act."

    direction = None
    if "bos" in trusted_signals and structure.bos:
        direction = structure.bos
    elif "choch" in trusted_signals and structure.choch:
        direction = structure.choch

    if not direction:
        return None, "No trusted structural signal present."

    if structure.last_swing_high is None or structure.last_swing_low is None:
        return None, "Insufficient swing data to place stop-loss."

    buffer = current_price * stop_buffer_percent / Decimal("100")

    if direction == "BULLISH":
        entry = current_price
        stop_loss = structure.last_swing_low - buffer
        stop_distance = entry - stop_loss
        if stop_distance <= 0:
            return None, "Invalid stop distance for long setup."
        take_profit = entry + stop_distance * min_rrr
        trade = TradeRequest(
            symbol="", side="LONG", entry=entry, stop_loss=stop_loss, take_profit=take_profit,
            reason=f"Mahoraga: {regime.regime} regime, bullish {['BOS' if 'bos' in trusted_signals and structure.bos else 'CHoCH'][0]}.",
        )
    else:  # BEARISH
        entry = current_price
        stop_loss = structure.last_swing_high + buffer
        stop_distance = stop_loss - entry
        if stop_distance <= 0:
            return None, "Invalid stop distance for short setup."
        take_profit = entry - stop_distance * min_rrr
        trade = TradeRequest(
            symbol="", side="SHORT", entry=entry, stop_loss=stop_loss, take_profit=take_profit,
            reason=f"Mahoraga: {regime.regime} regime, bearish {['BOS' if 'bos' in trusted_signals and structure.bos else 'CHoCH'][0]}.",
        )

    return trade, trade.reason
