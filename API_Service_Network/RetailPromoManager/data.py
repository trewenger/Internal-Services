import json
import os
import time
from datetime import datetime
import threading


class PromoData:
    """Manages promo code configs in promo_data.json"""

    def __init__(self):
        promo_dir = os.path.dirname(os.path.abspath(__file__))
        self.filepath = os.path.join(promo_dir, 'promo_data.json')
        self.lock = threading.Lock()
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    content = f.read().strip()
                    if content:
                        json.loads(content)
                        return
            except (json.JSONDecodeError, IOError):
                pass
        with open(self.filepath, 'w') as f:
            json.dump({'promo_codes': {}}, f, indent=2)

    def _read_data(self):
        with self.lock:
            for attempt in range(10):
                try:
                    with open(self.filepath, 'r') as f:
                        return json.load(f)
                except (IOError, json.JSONDecodeError):
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise

    def _write_data(self, data):
        with self.lock:
            for attempt in range(10):
                try:
                    temp = self.filepath + '.tmp'
                    with open(temp, 'w') as f:
                        json.dump(data, f, indent=2)
                    os.replace(temp, self.filepath)
                    break
                except IOError:
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise

    def get_all(self):
        return self._read_data().get('promo_codes', {})

    def get(self, name):
        return self.get_all().get(name)

    def add(self, name, config):
        data = self._read_data()
        if name in data['promo_codes']:
            raise ValueError(f'Promo code "{name}" already exists.')
        data['promo_codes'][name] = config
        self._write_data(data)

    def update(self, name, fields):
        """Update specified fields on an existing promo. Always refreshes last_modified."""
        data = self._read_data()
        if name not in data['promo_codes']:
            return False
        data['promo_codes'][name].update(fields)
        data['promo_codes'][name]['last_modified'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        self._write_data(data)
        return True

    def set_status(self, name, status):
        """Atomically update status and last_modified."""
        data = self._read_data()
        if name not in data['promo_codes']:
            return False
        data['promo_codes'][name]['status'] = status
        data['promo_codes'][name]['last_modified'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        self._write_data(data)
        return True


class PromoLogger:
    """Manages promo action and error logs in promo_log.json"""

    MAX_LOGS = 200
    MAX_ERRORS = 200

    def __init__(self):
        promo_dir = os.path.dirname(os.path.abspath(__file__))
        self.filepath = os.path.join(promo_dir, 'promo_log.json')
        self.lock = threading.Lock()
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    content = f.read().strip()
                    if content:
                        json.loads(content)
                        return
            except (json.JSONDecodeError, IOError):
                pass
        initial = {
            'logs': [],
            'log_stats': {'total_logs': 0, 'last_log': None},
            'errors': [],
            'error_stats': {'total_errors': 0, 'last_error': None}
        }
        with open(self.filepath, 'w') as f:
            json.dump(initial, f, indent=2)

    def _read_data(self):
        with self.lock:
            for attempt in range(10):
                try:
                    with open(self.filepath, 'r') as f:
                        return json.load(f)
                except (IOError, json.JSONDecodeError):
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise

    def _write_data(self, data):
        with self.lock:
            for attempt in range(10):
                try:
                    temp = self.filepath + '.tmp'
                    with open(temp, 'w') as f:
                        json.dump(data, f, indent=2)
                    os.replace(temp, self.filepath)
                    break
                except IOError:
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise

    def append(self, promo_name, action, triggered_by, result, details=''):
        data = self._read_data()
        now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        entry = {
            'id': data['log_stats']['total_logs'] + 1,
            'timestamp': now,
            'promo_name': promo_name,
            'action': action,
            'triggered_by': triggered_by,
            'result': result,
            'details': details
        }

        data['logs'].insert(0, entry)
        data['logs'] = data['logs'][:self.MAX_LOGS]
        data['log_stats']['total_logs'] += 1
        data['log_stats']['last_log'] = now

        if result == 'error':
            data['errors'].insert(0, entry)
            data['errors'] = data['errors'][:self.MAX_ERRORS]
            data['error_stats']['total_errors'] += 1
            data['error_stats']['last_error'] = now

        self._write_data(data)

    def get_logs(self, limit=50):
        return self._read_data().get('logs', [])[:limit]

    def get_errors(self, limit=50):
        return self._read_data().get('errors', [])[:limit]

    def clear_logs(self):
        data = self._read_data()
        count = len(data.get('logs', []))
        data['logs'] = []
        data['log_stats'] = {'total_logs': 0, 'last_log': None}
        self._write_data(data)
        return count

    def clear_errors(self):
        data = self._read_data()
        count = len(data.get('errors', []))
        data['errors'] = []
        data['error_stats'] = {'total_errors': 0, 'last_error': None}
        self._write_data(data)
        return count
