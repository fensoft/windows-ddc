from __future__ import annotations

import json
import os
from pathlib import Path

from ddc import MonitorIdentity, SavedMonitorSelection


SCHEMA_VERSION = 2
SETTINGS_PATH = Path(os.environ.get("APPDATA") or Path.home()) / "windows-ddc" / "settings.json"


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def load_selected_monitor_key() -> SavedMonitorSelection | None:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    selected_monitor = data.get("selected_monitor")
    if not isinstance(selected_monitor, dict):
        return None

    description = _optional_string(selected_monitor.get("description"))
    if description is None:
        return None

    schema_version = data.get("schema_version")
    if schema_version == SCHEMA_VERSION:
        identity_data = selected_monitor.get("identity")
        if not isinstance(identity_data, dict):
            return None

        device_path = _optional_string(identity_data.get("device_path"))
        if device_path is None:
            return None

        manufacturer_id = _optional_string(identity_data.get("manufacturer_id"))
        serial_number = _optional_string(identity_data.get("serial_number"))
        product_code = identity_data.get("product_code")
        if isinstance(product_code, bool) or not isinstance(product_code, int) or product_code < 0:
            product_code = None

        identity = MonitorIdentity(
            device_path=device_path,
            manufacturer_id=manufacturer_id.upper() if manufacturer_id is not None else None,
            product_code=product_code,
            serial_number=serial_number.upper() if serial_number is not None else None,
        )
        return SavedMonitorSelection(description=description, identity=identity)

    if schema_version is not None:
        return None

    ordinal = selected_monitor.get("ordinal")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        return None
    return SavedMonitorSelection(description=description, legacy_ordinal=ordinal)


def save_selected_monitor_key(selection: SavedMonitorSelection) -> None:
    if selection.identity is None or not selection.identity.device_path.strip():
        raise ValueError("Cannot save a monitor selection without a stable identity.")

    identity_payload: dict[str, str | int] = {
        "device_path": selection.identity.device_path,
    }
    if selection.identity.manufacturer_id is not None:
        identity_payload["manufacturer_id"] = selection.identity.manufacturer_id
    if selection.identity.product_code is not None:
        identity_payload["product_code"] = selection.identity.product_code
    if selection.identity.serial_number is not None:
        identity_payload["serial_number"] = selection.identity.serial_number

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "selected_monitor": {
            "description": selection.description,
            "identity": identity_payload,
        },
    }
    temp_path = SETTINGS_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(SETTINGS_PATH)
