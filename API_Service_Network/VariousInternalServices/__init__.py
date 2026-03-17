import json
import os

_CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'services_config.json')

_DEFAULT_CONFIG = {
    "on-time-performance": {"label": "On-Time Performance", "schedule_interval_minutes": 1440, "enabled": False, "running": False, "last_run": None, "last_status": None, "last_log": None},
    "tax-system-health":   {"label": "Tax System Health",   "schedule_interval_minutes": 1440, "enabled": False, "running": False, "last_run": None, "last_status": None, "last_log": None},
    "vendor-tracker":      {"label": "Vendor Tracker",      "schedule_interval_minutes": 1440, "enabled": False, "running": False, "last_run": None, "last_status": None, "last_log": None},
    "wip-update":          {"label": "WIP Update",          "schedule_interval_minutes": 1440, "enabled": False, "running": False, "last_run": None, "last_status": None, "last_log": None},
}


def load_services_config() -> dict:
    if not os.path.exists(_CONFIG_FILE):
        save_services_config(_DEFAULT_CONFIG)
        return _DEFAULT_CONFIG
    with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_services_config(config: dict) -> None:
    with open(_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)
