"""Loads/saves JSON state files — these live in the repo and get committed after each run,
since GitHub Actions runs are ephemeral (no persistent server / database)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_DIR = Path(__file__).resolve().parent.parent / "state"


def _path(name: str) -> Path:
    STATE_DIR.mkdir(exist_ok=True)
    return STATE_DIR / name


def load_json(name: str, default: Any) -> Any:
    path = _path(name)
    if not path.exists():
        return default
    with open(path, "r") as f:
        return json.load(f)


def save_json(name: str, data: Any) -> None:
    path = _path(name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_risk_state(account_id: str) -> dict:
    all_states = load_json("risk_state.json", {})
    return all_states.get(account_id, {})


def save_risk_state(account_id: str, state: dict) -> None:
    all_states = load_json("risk_state.json", {})
    all_states[account_id] = state
    save_json("risk_state.json", all_states)


def append_journal(account_id: str, entry: dict) -> None:
    journal = load_json("journal.json", [])
    entry_with_account = {"account_id": account_id, **entry}
    journal.append(entry_with_account)
    save_json("journal.json", journal[-500:])  # keep last 500 entries


def update_dashboard(account_id: str, info: dict) -> None:
    dashboard = load_json("dashboard.json", {"accounts": {}, "updated_at": None})
    dashboard["accounts"][account_id] = info
    save_json("dashboard.json", dashboard)
