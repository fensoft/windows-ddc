from __future__ import annotations

import json
import os
from pathlib import Path

from ddc import SelectionKey


SETTINGS_PATH = Path(os.environ.get("APPDATA") or Path.home()) / "windows-ddc" / "settings.json"


def load_selected_monitor_key() -> SelectionKey | None:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None

    selected_monitor = data.get("selected_monitor")
    if not isinstance(selected_monitor, dict):
        return None

    description = selected_monitor.get("description")
    ordinal = selected_monitor.get("ordinal")
    if not isinstance(description, str) or not isinstance(ordinal, int):
        return None

    description = description.strip()
    if not description or ordinal < 1:
        return None

    return description, ordinal


def save_selected_monitor_key(selection_key: SelectionKey) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "selected_monitor": {
            "description": selection_key[0],
            "ordinal": selection_key[1],
        }
    }
    temp_path = SETTINGS_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(SETTINGS_PATH)
