import json
import os
import re
import threading
import time
from datetime import datetime

from werkzeug.utils import secure_filename


_DIR = os.path.dirname(os.path.abspath(__file__))

_DEFAULT_SLIDESHOW_CONFIG = {
    'name': 'slideshow 1',
    'description': '',
    'speed_secs': 20,
    'enabled': False,
    'media': []
}

_DEFAULT_CONFIG = {
    'slideshows': [],
    'media': [],
}

_DEFAULT_LOG = {
    'log_stats':   {'total_logs': 0,   'last_log':   None},
    'logs':        [],
    'error_stats': {'total_errors': 0, 'last_error': None},
    'errors':      [],
}

VIDEO_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
ALLOWED_EXTS = VIDEO_EXTS | IMAGE_EXTS

# ============================================================================
# Media — manages media storage and access
# ============================================================================
class Media:
    """Manages media content for DDB"""

    def __init__(self):
        self.folder = os.path.join(_DIR, 'media')
        self._ensure_dir_exists()

    def _ensure_dir_exists(self):
        os.makedirs(os.path.join(self.folder), exist_ok=True)

    def get_all(self) -> list:
        """Returns metadata dicts for all valid media files in the folder."""
        files = []
        try:
            for filename in os.listdir(self.folder):
                ext = os.path.splitext(filename)[1].lower()
                if ext not in ALLOWED_EXTS:
                    continue
                filepath = os.path.join(self.folder, filename)
                if not os.path.isfile(filepath):
                    continue
                files.append({
                    'filename': filename,
                    'type': 'video' if ext in VIDEO_EXTS else 'image',
                    'ext': ext,
                    'size': os.path.getsize(filepath),
                })
        except OSError:
            pass
        return files

    def get_file(self, filename: str) -> str | None:
        """Returns the full path if the file exists and has a valid extension, else None."""
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTS:
            return None
        filepath = os.path.normpath(os.path.join(self.folder, filename))
        if not filepath.startswith(self.folder + os.sep) and filepath != self.folder:
            return None
        return filepath if os.path.isfile(filepath) else None

    def delete_file(self, filename: str) -> bool:
        """Delete a media file by name. Returns True if deleted, False if not found or invalid."""
        filepath = self.get_file(filename)
        if not filepath:
            return False
        try:
            os.remove(filepath)
            return True
        except OSError:
            return False

    def save_file(self, file_obj) -> dict | None:
        """Save an uploaded file object. Returns metadata dict, or None if the type is invalid."""
        filename = secure_filename(file_obj.filename or '')
        if not filename:
            return None
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTS:
            return None
        filepath = os.path.join(self.folder, filename)
        file_obj.save(filepath)
        return {
            'filename': filename,
            'type':     'video' if ext in VIDEO_EXTS else 'image',
            'ext':      ext,
            'size':     os.path.getsize(filepath),
        }
    

# ============================================================================
# SignageConfig — manages ddb_config.json
# ============================================================================

class SignageConfig:
    """Manages per-slideshow settings and content."""

    def __init__(self):
        self.filepath = os.path.join(_DIR, 'ddb_config.json')
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
                    slideshows = data.get("slideshows")
                    for name in slideshows:
                        cfg = slideshows.get(name)
                        for key, default in _DEFAULT_SLIDESHOW_CONFIG.items():
                            if key not in cfg:
                                cfg[key] = default
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

    def get(self, slideshow_name:str) -> dict:
        """Return config for one slideshow_name."""
        all_data = self.get_all()
        slideshows = all_data.get('slideshows', [])
        for s in slideshows:
            if s.get("name") == slideshow_name:
                return dict(s) or {}

    def set_running(self, slideshow_name:str, running:bool) -> None:
        """Mark a slideshow as running or not."""
        all_data = self.get_all()
        slideshows = all_data.get('slideshows', [])
        for s in slideshows:
            if s.get("name") == slideshow_name:
                s["enabled"] = running
                self._write(slideshows)
                break       

    def create(self, name: str, description: str = '', speed_secs: int = 20) -> tuple[str, dict]:
        """Create a new slideshow entry. Returns (key, config_dict)."""
        with self.lock:
            for attempt in range(10):
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        all_data = json.load(f)
                    break
                except (IOError, json.JSONDecodeError):
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise
            slideshows = all_data.get('slideshows', {})
            base_key = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_') or 'slideshow'
            key, n = base_key, 2
            while key in slideshows:
                key = f'{base_key}_{n}'
                n += 1
            cfg = {**_DEFAULT_SLIDESHOW_CONFIG, 'name': name, 'description': description, 'speed_secs': speed_secs}
            slideshows[key] = cfg
            all_data['slideshows'] = slideshows
            self._write_unlocked(all_data)
            return key, dict(cfg)

    def delete(self, slideshow_name: str) -> bool:
        """Delete a slideshow entry. Returns True if deleted, False if not found."""
        with self.lock:
            for attempt in range(10):
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        all_data = json.load(f)
                    break
                except (IOError, json.JSONDecodeError):
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise
            slideshows = all_data.get('slideshows', {})
            if slideshow_name not in slideshows:
                return False
            del slideshows[slideshow_name]
            self._write_unlocked(all_data)
            return True

    def remove_media_from_all(self, filename: str) -> None:
        """Remove a filename from the media list of every slideshow that references it."""
        with self.lock:
            for attempt in range(10):
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        all_data = json.load(f)
                    break
                except (IOError, json.JSONDecodeError):
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise
            changed = False
            for cfg in all_data.get('slideshows', {}).values():
                media_list = cfg.get('media', [])
                if filename in media_list:
                    cfg['media'] = [m for m in media_list if m != filename]
                    changed = True
            if changed:
                self._write_unlocked(all_data)

    def update(self, slideshow_name:str, fields:dict) -> dict:
        """Merge fields into one slideshow's config. Returns the updated config, or {} if not found."""
        with self.lock:
            for attempt in range(10):
                try:
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        all_data = json.load(f)
                    break
                except (IOError, json.JSONDecodeError):
                    if attempt < 9:
                        time.sleep(0.1)
                    else:
                        raise
            slideshows = all_data.get('slideshows', {})
            if slideshow_name not in slideshows:
                return {}
            slideshows[slideshow_name].update(fields)
            self._write_unlocked(all_data)
            return dict(slideshows[slideshow_name])


# ============================================================================
# SignageLog — manages ddb_log.json
# ============================================================================

class SignageLog:
    """Manages logs + errors in ddb_log.json."""

    def __init__(self):
        self.filepath = os.path.join(_DIR, 'ddb_log.json')
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
            json.dump(_DEFAULT_LOG, f, indent=2)

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

    def _write(self, data:dict) -> None:
        with self.lock:
            temp = self.filepath + '.tmp'
            with open(temp, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            os.replace(temp, self.filepath)

    # ----------------------------- Public API -------------------------------- #

    def add_log(self, status:str, triggered_by:str, log_data:dict) -> None:
        """Append a record to logs and errors (error runs only)."""
        data = self._read()

        timestamp = datetime.now().isoformat()
        run_id    = data['log_stats']['total_runs'] + 1

        entry = {
            'id':           run_id,
            'timestamp':    timestamp,
            'status':       status,
            'triggered_by': triggered_by,
            'log_data':     log_data,
        }

        if status == 'success':
            data['logs'].insert(0, entry)
            data['logs'] = data['logs'][:10]
            data['log_stats']['total_runs'] = run_id
            data['log_stats']['last_run']   = timestamp

        if status == 'error':
            err_id = data['error_stats']['total_errors'] + 1
            data['errors'].insert(0, {**entry, 'id': err_id})
            data['errors'] = data['errors'][:10]
            data['error_stats']['total_errors'] = err_id
            data['error_stats']['last_error']   = timestamp

        self._write(data)

    def get_logs(self, limit:int = 50) -> dict:
        """Return log file logs, capped at limit."""
        data = self._read()
        return {
            'logs':        data['logs'][:limit],
            'log_stats':   data['log_stats'],
        }
    
    def get_errors(self, limit:int = 50) -> dict:
        """Return log file errors, capped at limit."""
        data = self._read()
        return {
            'errors':      data['errors'][:limit],
            'error_stats': data['error_stats'],
        }

    def clear_logs(self) -> int:
        """Clear all run records. Returns count cleared."""
        data  = self._read()
        count = len(data.get('logs', []))
        data['logs']      = []
        data['log_stats'] = {'total_runs': 0, 'last_run': None}
        self._write(data)
        return count

    def clear_errors(self) -> int:
        """Clear error records. Returns count cleared."""
        data  = self._read()
        count = len(data.get('errors', []))
        data['errors'] = []
        data['error_stats'] = {'total_errors': 0, 'last_error': None}
        self._write(data)
        return count
