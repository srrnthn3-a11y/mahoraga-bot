"""
Mahoraga strategy: a library of concepts, cascaded in priority order, so the
bot keeps looking for a valid setup instead of sitting idle when the "ideal"
one isn't present.

Priority order (highest conviction first):
  1. BOS matching this regime's top pick     — strongest: fresh break, trusted context
  2. CHoCH matching this regime's top pick    — fresh reversal, trusted context
  3. BOS / CHoCH as a secondary signal        — real break, just not this regime's favorite
  4. Extreme range breakout                   — price already beyond the last swing extreme
  5. Range mean-reversion                     — price sitting near the edge of recent range
  6. Trend continuation                       — clear trend, no fresh break, ride it anyway
  7. Midpoint momentum bias                   — last resort: which side of the range midpoint

Every concept still has to produce a real stop (beyond a real swing point) and
still must clear the account's minimum RRR through RiskEngine before anything
executes — more concepts means more chances to find a legitimate setup, not
permission to skip the risk math.
"""

from __future__ import annotations

from decimal import Decimal

from app.data import RegimeResult
from app.structure import StructureResult
from app.risk import TradeRequest

REGIME_TRUST = {
    # Which structural signal is the *top pick* per regime.
    "TRENDING": ("bos",),
    "RANGING": ("choch",),
    "VOLATILE": ("bos", "choch"),
    "UNCERTAIN": ("bos", "choch"),
}

MIN_REGIME_CONFIDENCE = Decimal("0.35")
RANGE_EDGE_THRESHOLD = Decimal("0.3")  # within 30% of range edge counts as "near the edge"


def _range_position(structure: StructureResult, current_price: Decimal) -> Decimal | None:
    if structure.last_swing_high is None or structure.last_swing_low is None:
        return None
    range_size = structure.last_swing_high - structure.last_swing_low
    if range_size <= 0:
        return None
    return (current_price - structure.last_swing_low) / range_size


def _concept_primary(regime: RegimeResult, structure: StructureResult, price: Decimal) -> tuple[str | None, str | None]:
    trusted = REGIME_TRUST.get(regime.regime, ())
    if "bos" in trusted and structure.bos:
        return structure.bos, "BOS"
    if "choch" in trusted and structure.choch:
        return structure.choch, "CHoCH"
    return None, None


def _concept_secondary(regime: RegimeResult, structure: StructureResult, price: Decimal) -> tuple[str | None, str | None]:
    if structure.bos:
        return structure.bos, "BOS (secondary)"
    if structure.choch:
        return structure.choch, "CHoCH (secondary)"
    return None, None


def _concept_extreme_breakout(regime: RegimeResult, structure: StructureResult, price: Decimal) -> tuple[str | None, str | None]:
    if structure.last_swing_high is not None and price > structure.last_swing_high:
        return "BULLISH", "Extreme range breakout (above last swing high)"
    if structure.last_swing_low is not None and price < structure.last_swing_low:
        return "BEARISH", "Extreme range breakdown (below last swing low)"
    return None, None


def _concept_mean_reversion(regime: RegimeResult, structure: StructureResult, price: Decimal) -> tuple[str | None, str | None]:
    position = _range_position(structure, price)
    if position is None:
        return None, None
    if position >= (Decimal("1") - RANGE_EDGE_THRESHOLD):
        return "BEARISH", "Range mean-reversion (near range high)"
    if position <= RANGE_EDGE_THRESHOLD:
        return "BULLISH", "Range mean-reversion (near range low)"
    return None, None


def _concept_trend_continuation(regime: RegimeResult, structure: StructureResult, price: Decimal) -> tuple[str | None, str | None]:
    if structure.trend in ("BULLISH", "BEARISH"):
        return structure.trend, "Trend continuation"
    return None, None


def _concept_midpoint_bias(regime: RegimeResult, structure: StructureResult, price: Decimal) -> tuple[str | None, str | None]:
    position = _range_position(structure, price)
    if position is None:
        return None, None
    return ("BULLISH" if position >= Decimal("0.5") else "BEARISH"), "Midpoint momentum bias"


# Tried in this order — first concept that produces a direction wins.
STRATEGY_CASCADE = [
    _concept_primary,
    _concept_secondary,
    _concept_extreme_breakout,
    _concept_mean_reversion,
    _concept_trend_continuation,
    _concept_midpoint_bias,
]


def _build_trade(
    direction: str, structure: StructureResult, current_price: Decimal,
    min_rrr: Decimal, stop_buffer_percent: Decimal, concept: str, regime_name: str,
) -> tuple[TradeRequest | None, str]:
    buffer = current_price * stop_buffer_percent / Decimal("100")
    reason = f"Mahoraga: {regime_name} regime, {concept} ({direction.lower()})."

    if direction == "BULLISH":
        entry = current_price
        stop_loss = structure.last_swing_low - buffer
        stop_distance = entry - stop_loss
        if stop_distance <= 0:
            return None, "Invalid stop distance for long setup."
        take_profit = entry + stop_distance * min_rrr
        return TradeRequest("", "LONG", entry, stop_loss, take_profit, reason), reason

    entry = current_price
    stop_loss = structure.last_swing_high + buffer
    stop_distance = stop_loss - entry
    if stop_distance <= 0:
        return None, "Invalid stop distance for short setup."
    take_profit = entry - stop_distance * min_rrr
    return TradeRequest("", "SHORT", entry, stop_loss, take_profit, reason), reason


def decide(
    regime: RegimeResult,
    structure: StructureResult,
    current_price: Decimal,
    min_rrr: Decimal,
    stop_buffer_percent: Decimal = Decimal("0.3"),
) -> tuple[TradeRequest | None, str]:
    """Returns (TradeRequest or None, human-readable reason)."""

    if regime.confidence < MIN_REGIME_CONFIDENCE:
        return None, f"Regime confidence {regime.confidence:.2f} too low to act."

    if structure.last_swing_high is None or structure.last_swing_low is None:
        return None, "Insufficient swing data to place stop-loss."

    for concept_fn in STRATEGY_CASCADE:
        direction, concept = concept_fn(regime, structure, current_price)
        if direction:
            return _build_trade(direction, structure, current_price, min_rrr, stop_buffer_percent, concept, regime.regime)

    return None, f"No concept matched current {regime.regime} conditions."
