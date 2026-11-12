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
    'onedrive-shortcuts':  {'label': 'OneDrive Shortcuts',   **copy.deepcopy(_DEFAULT_SERVICE_CONFIG), 'syncs': []},
}

# New fields added after initial release — backfilled on read.
_FIELD_DEFAULTS = {
    'schedule_type':     'interval',
    'schedule_cron':     None,
    'notify_mode':       'none',
    'notify_recipients': [],
}
_FIELDS_TO_REMOVE = ['last_log']

# Service-specific extra fields — backfilled only on their own key (never added to other services).
_PER_KEY_DEFAULTS = {
    'onedrive-shortcuts': {'syncs': []},
}

# Services added after initial release — added to an existing services_config.json on read
# (the live file is gitignored, so deployments would otherwise never pick up a new service).
_KEYS_TO_ADD = ['onedrive-shortcuts']

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
                    # Backfill new services, new fields, and drop stale ones.
                    changed = False
                    for key in _KEYS_TO_ADD:
                        if key not in data:
                            data[key] = copy.deepcopy(_DEFAULT_CONFIG[key])
                            changed = True
                    for key, extras in _PER_KEY_DEFAULTS.items():
                        if key in data:
                            for field, default in extras.items():
                                if field not in data[key]:
                                    data[key][field] = copy.deepcopy(default)
                                    changed = True
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


# ============================================================================
# ShortcutState — manages onedrive_shortcuts_state.json
# Tracks every OneDrive shortcut the OneDrive Shortcuts service created (or found
# already present) so removal only ever deletes service-tracked items, plus a queue
# of removals for deleted/edited syncs. Not user-editable config.
# ============================================================================

def sync_fingerprint(sync: dict) -> str:
    """
    Identity of what a sync points at. If this changes between saves (site URL, library, or
    shortcut-name override), the old shortcuts are queued for removal and new ones created.
    """
    site = (sync.get('site_url') or '').strip().rstrip('/').lower()
    library = (sync.get('library_name') or '').strip().lower()
    name = (sync.get('shortcut_name') or '').strip().lower()
    return f'{site}|{library}|{name}'


_DEFAULT_SHORTCUT_STATE = {'syncs': {}, 'pending_removals': []}


class ShortcutState:
    """
    State file layout:
        {"syncs": {"<sync_id>": {"fingerprint", "name", "force_removals": bool,
                                 "items": {"<userId>": {"upn", "item_id", "name", "tracked_at"}}}},
         "pending_removals": [{"sync_id", "name", "reason", "queued_at",
                               "items": {"<userId>": {"upn", "item_id", ...}}}]}
    Every public method is an atomic read-modify-write under one lock.
    """

    def __init__(self):
        self.filepath = os.path.join(_DIR, 'onedrive_shortcuts_state.json')
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
            json.dump(_DEFAULT_SHORTCUT_STATE, f, indent=2)

    def _read_unlocked(self) -> dict:
        for attempt in range(10):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for key, default in _DEFAULT_SHORTCUT_STATE.items():
                    data.setdefault(key, copy.deepcopy(default))
                return data
            except (IOError, json.JSONDecodeError):
                if attempt < 9:
                    time.sleep(0.1)
                else:
                    raise

    def _write_unlocked(self, data: dict) -> None:
        temp = self.filepath + '.tmp'
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(temp, self.filepath)

    @staticmethod
    def _empty_sync(sync: dict) -> dict:
        return {'fingerprint': sync_fingerprint(sync), 'name': sync.get('name', ''),
                'force_removals': False, 'items': {}}

    # ----------------------------- Public API -------------------------------- #

    def get_all(self) -> dict:
        with self.lock:
            return self._read_unlocked()

    def get_sync(self, sync_id: str) -> dict:
        """Returns a copy of one sync's state (empty shape if untracked)."""
        with self.lock:
            st = self._read_unlocked()['syncs'].get(sync_id)
        return copy.deepcopy(st) if st else {'fingerprint': None, 'name': '', 'force_removals': False, 'items': {}}

    def summary(self) -> dict:
        """UI summary: per-sync tracked counts + force flags, and the pending-removal queue (counts only)."""
        with self.lock:
            data = self._read_unlocked()
        return {
            'syncs': {sid: {'tracked': len(st.get('items', {})), 'force_removals': bool(st.get('force_removals'))}
                      for sid, st in data['syncs'].items()},
            'pending_removals': [{'name': p.get('name'), 'reason': p.get('reason'), 'count': len(p.get('items', {})),
                                  'queued_at': p.get('queued_at')} for p in data['pending_removals']],
        }

    def reconcile_with_config(self, syncs: list) -> list:
        """
        Aligns state with the saved sync list. Deleted syncs, and syncs whose fingerprint changed,
        have their tracked items moved to pending_removals. New syncs get an empty state entry.
        :return: [{"name", "count", "reason"}] for each removal that was queued.
        """
        queued = []
        with self.lock:
            data = self._read_unlocked()
            current = {s['id']: s for s in syncs if s.get('id')}
            now = datetime.now().isoformat()

            for sid, st in list(data['syncs'].items()):
                sync = current.get(sid)
                if sync is None:
                    reason = 'deleted'
                elif st.get('fingerprint') != sync_fingerprint(sync):
                    reason = 'edited'
                else:
                    st['name'] = sync.get('name', st.get('name', ''))
                    continue

                if st.get('items'):
                    data['pending_removals'].append({
                        'sync_id': sid, 'name': st.get('name', ''), 'reason': reason,
                        'queued_at': now, 'items': st['items'],
                    })
                    queued.append({'name': st.get('name', ''), 'count': len(st['items']), 'reason': reason})

                if reason == 'deleted':
                    del data['syncs'][sid]
                else:
                    data['syncs'][sid] = self._empty_sync(sync)

            for sid, sync in current.items():
                if sid not in data['syncs']:
                    data['syncs'][sid] = self._empty_sync(sync)

            self._write_unlocked(data)
        return queued

    def save_sync_items(self, sync: dict, items: dict) -> None:
        """
        Replaces a sync's tracked items after a run. If the sync was deleted or edited while the
        run was in progress (fingerprint no longer matches), the items are queued for removal
        instead so nothing the run created is left untracked.
        """
        with self.lock:
            data = self._read_unlocked()
            st = data['syncs'].get(sync['id'])
            if st is not None and st.get('fingerprint') == sync_fingerprint(sync):
                st['items'] = items
                st['name'] = sync.get('name', st.get('name', ''))
            elif items:
                data['pending_removals'].append({
                    'sync_id': sync['id'], 'name': sync.get('name', ''), 'reason': 'edited during run',
                    'queued_at': datetime.now().isoformat(), 'items': items,
                })
            self._write_unlocked(data)

    def set_force_removals(self, sync_id: str, value: bool) -> bool:
        """Sets the one-shot 'allow removals past the guard' flag. Returns False if the sync is unknown."""
        with self.lock:
            data = self._read_unlocked()
            st = data['syncs'].get(sync_id)
            if st is None:
                return False
            st['force_removals'] = bool(value)
            self._write_unlocked(data)
            return True

    def get_pending_removals(self) -> list:
        with self.lock:
            return copy.deepcopy(self._read_unlocked()['pending_removals'])

    def take_pending_removals(self) -> list:
        """Atomically returns and clears the removal queue. Re-queue failures with requeue_removals()."""
        with self.lock:
            data = self._read_unlocked()
            pending = data['pending_removals']
            data['pending_removals'] = []
            self._write_unlocked(data)
            return pending

    def requeue_removals(self, entries: list) -> None:
        """Puts removal entries (with only their still-undeleted items) back on the queue."""
        entries = [e for e in entries if e.get('items')]
        if not entries:
            return
        with self.lock:
            data = self._read_unlocked()
            data['pending_removals'] = entries + data['pending_removals']
            self._write_unlocked(data)
