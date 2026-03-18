import copy
import json
import os
import threading
import time
from datetime import datetime


_DIR = os.path.dirname(os.path.abspath(__file__))

_DEFAULT_SERVICE_CONFIG = {
    'schedule_type': 'interval',
    'schedule_interval_minutes': 1440,
    'schedule_cron': None,
    'enabled': False,
    'running': False,
    'last_run': None,
    'last_status': None,
    'notify_mode': 'none',
    'notify_recipients': [],
}

_DEFAULT_CONFIG = {
    'on-time-performance': {'label': 'On-Time Performance',  **copy.deepcopy(_DEFAULT_SERVICE_CONFIG)},
    'tax-system-health':   {'label': 'Tax System Health',    **copy.deepcopy(_DEFAULT_SERVICE_CONFIG)},
    'vendor-tracker':      {'label': 'Vendor Tracker',       **copy.deepcopy(_DEFAULT_SERVICE_CONFIG)},
    'wip-update':          {'label': 'WIP Update',           **copy.deepcopy(_DEFAULT_SERVICE_CONFIG)},
}

# New fields added after initial release — backfilled on read.
_FIELD_DEFAULTS = {
    'schedule_type':     'interval',
    'schedule_cron':     None,
    'notify_mode':       'none',
    'notify_recipients': [],
}
_FIELDS_TO_REMOVE = ['last_log']

_DEFAULT_SERVICE_LOG = {
    'log_stats':   {'total_runs': 0,   'last_run':   None},
    'logs':        [],
    'error_stats': {'total_errors': 0, 'last_error': None},
    'errors':      [],
}


# ============================================================================
# ServicesConfig — manages services_config.json
# Mirrors RIM InventoryData class.
# ============================================================================

class ServicesConfig:
    """Manages per-service schedule, enable, and notification config."""

    def __init__(self):
        self.filepath = os.path.join(_DIR, 'services_config.json')
        self.lock = threading.Lock()
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                if content:
                    json.loads(content)
                    return
            except (json.JSONDecodeError, IOError):
                pass
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(_DEFAULT_CONFIG, f, indent=2)

    def _read(self) -> dict:
        with self.lock:
            for attempt in range(10):
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # Backfill new fields and drop stale ones.
                    changed = False
                    for svc in data.values():
                        for key, default in _FIELD_DEFAULTS.items():
                            if key not in svc:
                                svc[key] = default
                                changed = True
                        for key in _FIELDS_TO_REMOVE:
                            if key in svc:
                                del svc[key]
                                changed = True
                    if changed:
                        self._write_unlocked(data)
                    return data
                except (IOError, json.JSONDecodeError):
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise

    def _write(self, data: dict) -> None:
        with self.lock:
            self._write_unlocked(data)

    def _write_unlocked(self, data: dict) -> None:
        """Write without acquiring the lock — caller must hold it."""
        temp = self.filepath + '.tmp'
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(temp, self.filepath)

    # ----------------------------- Public API -------------------------------- #

    def get_all(self) -> dict:
        """Return the full config dict."""
        return self._read()

    def get(self, service_name: str) -> dict:
        """Return config for one service."""
        return self._read().get(service_name, {})

    def set_running(self, service_name: str, running: bool) -> None:
        """Mark a service as running or not."""
        data = self._read()
        data[service_name]['running'] = running
        self._write(data)

    def save_result(self, service_name: str, success: bool) -> None:
        """Persist the outcome of a completed run."""
        data = self._read()
        data[service_name]['running']     = False
        data[service_name]['last_run']    = datetime.now().isoformat()
        data[service_name]['last_status'] = 'success' if success else 'error'
        self._write(data)

    def update(self, service_name: str, fields: dict) -> dict:
        """Merge arbitrary fields into a service's config. Returns updated config."""
        data = self._read()
        data[service_name].update(fields)
        self._write(data)
        return data[service_name]


# ============================================================================
# ServicesLog — manages services_log.json
# Mirrors RIM Logger class.
# ============================================================================

class ServicesLog:
    """Manages per-service run history (logs + errors) in services_log.json."""

    def __init__(self):
        self.filepath = os.path.join(_DIR, 'services_log.json')
        self.lock = threading.Lock()
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                if content:
                    json.loads(content)
                    return
            except (json.JSONDecodeError, IOError):
                pass
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=2)

    def _read(self) -> dict:
        with self.lock:
            for attempt in range(10):
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except (IOError, json.JSONDecodeError):
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise

    def _write(self, data: dict) -> None:
        with self.lock:
            temp = self.filepath + '.tmp'
            with open(temp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            os.replace(temp, self.filepath)

    # ----------------------------- Public API -------------------------------- #

    def append_run(self, service_name: str, status: str, triggered_by: str, log_data: dict) -> None:
        """Append a run record to logs (all runs) and errors (error runs only)."""
        data = self._read()
        if service_name not in data:
            data[service_name] = copy.deepcopy(_DEFAULT_SERVICE_LOG)

        svc       = data[service_name]
        timestamp = datetime.now().isoformat()
        run_id    = svc['log_stats']['total_runs'] + 1

        entry = {
            'id':           run_id,
            'timestamp':    timestamp,
            'status':       status,
            'triggered_by': triggered_by,
            'log_data':     log_data,
        }

        if status == 'success':
            svc['logs'].insert(0, entry)
            svc['logs'] = svc['logs'][:10]
            svc['log_stats']['total_runs'] = run_id
            svc['log_stats']['last_run']   = timestamp

        if status == 'error':
            err_id = svc['error_stats']['total_errors'] + 1
            svc['errors'].insert(0, {**entry, 'id': err_id})
            svc['errors'] = svc['errors'][:10]
            svc['error_stats']['total_errors'] = err_id
            svc['error_stats']['last_error']   = timestamp

        self._write(data)

    def get_logs(self, service_name: str, limit: int = 50) -> dict:
        """Return logs and errors for one service, each capped at limit."""
        data = self._read()
        svc  = data.get(service_name, copy.deepcopy(_DEFAULT_SERVICE_LOG))
        return {
            'logs':        svc['logs'][:limit],
            'log_stats':   svc['log_stats'],
            'errors':      svc['errors'][:limit],
            'error_stats': svc['error_stats'],
        }

    def clear_logs(self, service_name: str) -> int:
        """Clear all run records for a service. Returns count cleared."""
        data  = self._read()
        count = len(data.get(service_name, {}).get('logs', []))
        if service_name in data:
            data[service_name]['logs']      = []
            data[service_name]['log_stats'] = {'total_runs': 0, 'last_run': None}
        self._write(data)
        return count

    def clear_errors(self, service_name: str) -> int:
        """Clear error records for a service. Returns count cleared."""
        data  = self._read()
        count = len(data.get(service_name, {}).get('errors', []))
        if service_name in data:
            data[service_name]['errors']      = []
            data[service_name]['error_stats'] = {'total_errors': 0, 'last_error': None}
        self._write(data)
        return count
