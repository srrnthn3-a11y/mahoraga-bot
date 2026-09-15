"""
Entry point run by the GitHub Actions schedule every 15 minutes.

For each account in accounts.json:
  1. Load API credentials from environment variables (set from GitHub Secrets)
  2. Fetch market snapshot
  3. Detect regime, analyze structure
  4. Ask Mahoraga for a trade decision
  5. Validate through the risk engine
  6. If approved and not blocked by control.json kill switch, place the order
  7. Update journal + dashboard state (committed back to the repo by the workflow)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data import RegimeDetector
from app.structure import StructureAnalyzer
from app.exchange import ExchangeAdapter, ExchangeError
from app.risk import RiskEngine, RiskSettings, RiskState
from app import mahoraga
from app import state as state_store

ROOT = Path(__file__).resolve().parent.parent


def load_accounts() -> list[dict]:
    with open(ROOT / "accounts.json") as f:
        return json.load(f)["accounts"]


def load_control() -> dict:
    control_path = ROOT / "control.json"
    if not control_path.exists():
        return {"kill_switch": False}
    with open(control_path) as f:
        return json.load(f)


def env_for(account_id: str, suffix: str) -> str | None:
    return os.environ.get(f"{account_id.upper()}_{suffix}")


def run_account(account: dict, global_kill_switch: bool) -> None:
    account_id = account["account_id"]
    symbol = account.get("symbol", "BTC/USDT")
    timeframe = account.get("timeframe", "15m")

    api_key = env_for(account_id, "API_KEY")
    api_secret = env_for(account_id, "API_SECRET")
    api_passphrase = env_for(account_id, "API_PASSPHRASE")

    if not api_key or not api_secret:
        state_store.update_dashboard(account_id, {
            "name": account.get("name", account_id), "status": "missing_credentials",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        return

    try:
        adapter = ExchangeAdapter(
            exchange_id=account["exchange_id"], api_key=api_key, api_secret=api_secret,
            api_passphrase=api_passphrase, mode=account.get("mode", "paper"),
        )
        snapshot = adapter.fetch_snapshot(symbol, timeframe=timeframe, limit=100)
        equity = adapter.fetch_equity(account.get("quote_asset", "USDT"))
    except ExchangeError as exc:
        state_store.update_dashboard(account_id, {
            "name": account.get("name", account_id), "status": "connection_error", "error": str(exc),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        return

    regime = RegimeDetector().detect(snapshot.candles)
    structure = StructureAnalyzer().analyze(snapshot.candles)
    current_price = snapshot.latest.close if snapshot.latest else Decimal("0")

    settings = RiskSettings.from_dict(account.get("risk", {}))
    stop_buffer = Decimal(str(account.get("risk", {}).get("stop_buffer_percent", "0.3")))
    trade, decision_reason = mahoraga.decide(regime, structure, current_price, settings.min_rrr, stop_buffer)

    risk_state = RiskState.from_dict(state_store.load_risk_state(account_id))
    risk_state.kill_switch = global_kill_switch or account.get("kill_switch", False)
    engine = RiskEngine(settings, risk_state)

    order_result = None
    if trade:
        trade.symbol = symbol
        risk_result = engine.validate(trade, equity)
        if risk_result.approved:
            try:
                side = "buy" if trade.side == "LONG" else "sell"
                order_result = adapter.place_order(symbol, side, risk_result.position_size)
                risk_state.open_positions += 1
            except ExchangeError as exc:
                order_result = {"error": str(exc)}
        decision_reason = risk_result.reason if not risk_result.approved else decision_reason

    state_store.save_risk_state(account_id, risk_state.to_dict())
    state_store.append_journal(account_id, {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol, "regime": regime.regime, "trend": structure.trend,
        "decision": decision_reason, "order": order_result, "equity": str(equity),
    })
    state_store.update_dashboard(account_id, {
        "name": account.get("name", account_id), "status": "ok", "mode": account.get("mode", "paper"),
        "symbol": symbol, "equity": str(equity), "regime": regime.regime,
        "trend": structure.trend, "last_decision": decision_reason,
        "open_positions": risk_state.open_positions,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def main() -> None:
    control = load_control()
    accounts = load_accounts()
    for account in accounts:
        run_account(account, control.get("kill_switch", False))

    dashboard = state_store.load_json("dashboard.json", {"accounts": {}})
    dashboard["updated_at"] = datetime.now(timezone.utc).isoformat()
    state_store.save_json("dashboard.json", dashboard)


if __name__ == "__main__":
    main()
