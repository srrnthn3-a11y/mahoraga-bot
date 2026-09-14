"""Risk management: position sizing, RRR enforcement, daily loss / exposure caps, kill switch."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class RiskSettings:
    risk_percent: Decimal = Decimal("1.0")
    min_rrr: Decimal = Decimal("3.0")
    max_daily_loss_percent: Decimal = Decimal("3.0")
    max_consecutive_losses: int = 3
    max_open_positions: int = 3
    max_exposure_percent: Decimal = Decimal("50.0")

    @staticmethod
    def from_dict(data: dict) -> "RiskSettings":
        defaults = RiskSettings()
        return RiskSettings(
            risk_percent=Decimal(str(data.get("risk_percent", defaults.risk_percent))),
            min_rrr=Decimal(str(data.get("min_rrr", defaults.min_rrr))),
            max_daily_loss_percent=Decimal(str(data.get("max_daily_loss_percent", defaults.max_daily_loss_percent))),
            max_consecutive_losses=int(data.get("max_consecutive_losses", defaults.max_consecutive_losses)),
            max_open_positions=int(data.get("max_open_positions", defaults.max_open_positions)),
            max_exposure_percent=Decimal(str(data.get("max_exposure_percent", defaults.max_exposure_percent))),
        )


@dataclass
class TradeRequest:
    symbol: str
    side: str  # LONG | SHORT
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    reason: str = ""


@dataclass
class RiskResult:
    approved: bool
    reason: str
    risk_amount: Decimal = Decimal("0")
    position_size: Decimal = Decimal("0")
    rrr: Decimal = Decimal("0")


@dataclass
class RiskState:
    kill_switch: bool = False
    daily_loss_percent: Decimal = Decimal("0")
    consecutive_losses: int = 0
    open_positions: int = 0
    exposure_percent: Decimal = Decimal("0")

    @staticmethod
    def from_dict(data: dict) -> "RiskState":
        return RiskState(
            kill_switch=bool(data.get("kill_switch", False)),
            daily_loss_percent=Decimal(str(data.get("daily_loss_percent", "0"))),
            consecutive_losses=int(data.get("consecutive_losses", 0)),
            open_positions=int(data.get("open_positions", 0)),
            exposure_percent=Decimal(str(data.get("exposure_percent", "0"))),
        )

    def to_dict(self) -> dict:
        return {
            "kill_switch": self.kill_switch,
            "daily_loss_percent": str(self.daily_loss_percent),
            "consecutive_losses": self.consecutive_losses,
            "open_positions": self.open_positions,
            "exposure_percent": str(self.exposure_percent),
        }


class RiskEngine:
    def __init__(self, settings: RiskSettings, state: RiskState) -> None:
        self.settings = settings
        self.state = state

    def validate(self, trade: TradeRequest, account_equity: Decimal) -> RiskResult:
        if self.state.kill_switch:
            return RiskResult(False, "Kill switch is active.")
        if account_equity <= 0:
            return RiskResult(False, "Invalid account equity.")

        side = trade.side.upper()
        if side == "LONG":
            if trade.stop_loss >= trade.entry:
                return RiskResult(False, "Long stop-loss must be below entry.")
            if trade.take_profit <= trade.entry:
                return RiskResult(False, "Long take-profit must be above entry.")
        elif side == "SHORT":
            if trade.stop_loss <= trade.entry:
                return RiskResult(False, "Short stop-loss must be above entry.")
            if trade.take_profit >= trade.entry:
                return RiskResult(False, "Short take-profit must be below entry.")
        else:
            return RiskResult(False, "Invalid trade side.")

        stop_distance = abs(trade.entry - trade.stop_loss)
        reward_distance = abs(trade.take_profit - trade.entry)
        rrr = reward_distance / stop_distance

        if rrr < self.settings.min_rrr:
            return RiskResult(False, f"RRR {rrr:.2f} below minimum {self.settings.min_rrr:.2f}.", rrr=rrr)
        if self.state.daily_loss_percent >= self.settings.max_daily_loss_percent:
            return RiskResult(False, "Maximum daily loss reached.", rrr=rrr)
        if self.state.consecutive_losses >= self.settings.max_consecutive_losses:
            return RiskResult(False, "Maximum consecutive losses reached.", rrr=rrr)
        if self.state.open_positions >= self.settings.max_open_positions:
            return RiskResult(False, "Maximum open positions reached.", rrr=rrr)

        risk_amount = account_equity * self.settings.risk_percent / Decimal("100")
        position_size = risk_amount / stop_distance
        exposure = self.state.exposure_percent + position_size * trade.entry / account_equity * Decimal("100")
        if exposure > self.settings.max_exposure_percent:
            return RiskResult(False, "Maximum exposure exceeded.", risk_amount, position_size, rrr)

        return RiskResult(True, "Trade approved.", risk_amount, position_size, rrr)
