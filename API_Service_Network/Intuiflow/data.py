import copy
import json
import os
import threading
import time
from datetime import datetime


_DIR = os.path.dirname(os.path.abspath(__file__))

_DEFAULT_PIPELINE_CONFIG = {
    'schedule_type':                        'interval',
    'schedule_interval_minutes':            1440,
    'schedule_cron':                        None,
    'enabled':                              False,
    'running':                              False,
    'last_run':                             None,
    'last_status':                          None,
    'notify_mode':                          'none',
    'notify_recipients':                    [],
    'short_inv_notify_enabled':             False,
    'short_inv_notify_recipients':          [],
    'def_locations_notify_enabled':         False,
    'def_locations_notify_recipients':      [],
}

_DEFAULT_MODULE_CONFIG = {
    'running':           False,
    'last_run':          None,
    'last_status':       None,
    'notify_mode':       'none',
    'notify_recipients': [],
}

_DEFAULT_MODULE_CONFIG_SHORT_INV = {
    'running':                              False,
    'last_run':                             None,
    'last_status':                          None,
    'notify_mode':                          'none',
    'notify_recipients':                    [],
    'short_inv_notify_enabled':             False,
    'short_inv_notify_recipients':          [],
    'def_locations_notify_enabled':         False,
    'def_locations_notify_recipients':      [],
}

_DEFAULT_CONFIG = {
    'full-sync':             {'label': 'Full Sync',             **copy.deepcopy(_DEFAULT_PIPELINE_CONFIG)},
    'partial-sync':          {'label': 'Partial Sync',          **copy.deepcopy(_DEFAULT_PIPELINE_CONFIG)},
    'upload-fb-files':       {'label': 'Upload FB Files',       **copy.deepcopy(_DEFAULT_MODULE_CONFIG)},
    'update-work-orders':    {'label': 'Update Work Orders',    **copy.deepcopy(_DEFAULT_MODULE_CONFIG)},
    'close-work-orders':     {'label': 'Close Work Orders',     **copy.deepcopy(_DEFAULT_MODULE_CONFIG_SHORT_INV)},
    'import-pending-orders': {'label': 'Import Pending Orders', **copy.deepcopy(_DEFAULT_MODULE_CONFIG)},
}

_DEFAULT_ENTRY_LOG = {
    'log_stats':   {'total_runs': 0,   'last_run':   None},
    'logs':        [],
    'error_stats': {'total_errors': 0, 'last_error': None},
    'errors':      [],
}


# ============================================================================
# IntuiflowConfig — manages intuiflow_config.json
# Mirrors VariousInternalServices/data.py ServicesConfig.
# ============================================================================

class IntuiflowConfig:
    """Manages per-pipeline/module schedule, enable, and notification config."""

    def __init__(self):
        self.filepath = os.path.join(_DIR, 'intuiflow_config.json')
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
                    # Backfill missing fields and drop stale ones using _DEFAULT_CONFIG as authority.
                    changed = False
                    for key, entry in data.items():
                        default = _DEFAULT_CONFIG.get(key)
                        if default is None:
                            continue
                        for field, default_val in default.items():
                            if field not in entry:
                                entry[field] = copy.deepcopy(default_val)
                                changed = True
                        stale = [f for f in list(entry.keys()) if f not in default]
                        for field in stale:
                            del entry[field]
                            changed = True
                    if changed:
                        self._write_unlocked(data)
                    return data
                except (IOError, json.JSONDecodeError):
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise

    def _write(self, data:dict) -> None:
        with self.lock:
            self._write_unlocked(data)

    def _write_unlocked(self, data:dict) -> None:
        """Write without acquiring the lock — caller must hold it."""
        temp = self.filepath + '.tmp'
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(temp, self.filepath)

    # ----------------------------- Public API -------------------------------- #

    def get_all(self) -> dict:
        """Return the full config dict."""
        return self._read()

    def get(self, name:str) -> dict:
        """Return config for one pipeline or module."""
        return self._read().get(name, {})

    def set_running(self, name:str, running:bool) -> None:
        """Mark a pipeline or module as running or not."""
        data = self._read()
        data[name]['running'] = running
        self._write(data)

    def save_result(self, name:str, success:bool) -> None:
        """Persist the outcome of a completed run."""
        data = self._read()
        data[name]['running']     = False
        data[name]['last_run']    = datetime.now().isoformat()
        data[name]['last_status'] = 'success' if success else 'error'
        self._write(data)

    def update(self, name:str, fields:dict) -> dict:
        """Merge arbitrary fields into a pipeline/module config. Returns updated config."""
        data = self._read()
        data[name].update(fields)
        self._write(data)
        return data[name]


# ============================================================================
# IntuiflowLog — manages intuiflow_log.json
# Mirrors VariousInternalServices/data.py ServicesLog.
# ============================================================================

class IntuiflowLog:
    """Manages per-pipeline/module run history (logs + errors) in intuiflow_log.json."""

    def __init__(self):
        self.filepath = os.path.join(_DIR, 'intuiflow_log.json')
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

    def append_run(self, name: str, status: str, triggered_by: str, log_data: dict) -> None:
        """Append a run record to logs (all runs) and errors (error runs only)."""
        data = self._read()
        if name not in data:
            data[name] = copy.deepcopy(_DEFAULT_ENTRY_LOG)

        entry_data = data[name]
        timestamp  = datetime.now().isoformat()
        run_id     = entry_data['log_stats']['total_runs'] + 1

        entry = {
            'id':           run_id,
            'timestamp':    timestamp,
            'status':       status,
            'triggered_by': triggered_by,
            'log_data':     log_data,
        }

        if status == 'success':
            entry_data['logs'].insert(0, entry)
            entry_data['logs'] = entry_data['logs'][:10]
            entry_data['log_stats']['total_runs'] = run_id
            entry_data['log_stats']['last_run']   = timestamp

        if status == 'error':
            err_id = entry_data['error_stats']['total_errors'] + 1
            entry_data['errors'].insert(0, {**entry, 'id': err_id})
            entry_data['errors'] = entry_data['errors'][:10]
            entry_data['error_stats']['total_errors'] = err_id
            entry_data['error_stats']['last_error']   = timestamp

        self._write(data)

    def get_logs(self, name: str, limit: int = 50) -> dict:
        """Return logs and errors for one pipeline or module, each capped at limit."""
        data       = self._read()
        entry_data = data.get(name, copy.deepcopy(_DEFAULT_ENTRY_LOG))
        return {
            'logs':        entry_data['logs'][:limit],
            'log_stats':   entry_data['log_stats'],
            'errors':      entry_data['errors'][:limit],
            'error_stats': entry_data['error_stats'],
        }

    def clear_logs(self, name: str) -> int:
        """Clear all run records for a pipeline or module. Returns count cleared."""
        data  = self._read()
        count = len(data.get(name, {}).get('logs', []))
        if name in data:
            data[name]['logs']      = []
            data[name]['log_stats'] = {'total_runs': 0, 'last_run': None}
        self._write(data)
        return count

    def clear_errors(self, name: str) -> int:
        """Clear error records for a pipeline or module. Returns count cleared."""
        data  = self._read()
        count = len(data.get(name, {}).get('errors', []))
        if name in data:
            data[name]['errors']      = []
            data[name]['error_stats'] = {'total_errors': 0, 'last_error': None}
        self._write(data)
        return count
