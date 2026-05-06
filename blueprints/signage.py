import logging
import os
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory

from API_Service_Network.DigitalDisplayBoard.ddb_data import SignageConfig, SignageLog, Media
from blueprints.auth import access_required, login_required
from config import Config

signage_bp = Blueprint('signage', __name__)
logger = logging.getLogger(__name__)
app_configs = Config()
signage_config = SignageConfig()
signage_log = SignageLog()
media = Media()

# ============================================================================
# Sheet cache + scheduler
# ============================================================================

_sheet_cache      = {}   # { key: {'rows': [[...]], 'fetched_at': datetime, 'error': str|None} }
_sheet_cache_lock = threading.Lock()
_sheet_scheduler  = BackgroundScheduler()


def _refresh_sheet(key: str) -> None:
    """Export the sheet as a PNG via the Sheets export URL and save it to the media folder."""
    cfg = signage_config.get_sheet(key)
    if not cfg:
        return
    try:
        import urllib.parse
        import fitz  # pymupdf
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession

        creds = service_account.Credentials.from_service_account_file(
            app_configs.GOOGLE_CREDENTIALS_PATH,
            scopes=['https://www.googleapis.com/auth/drive.readonly'],
        )

        params = {
            'format':      'pdf',
            'gid':         str(cfg.get('sheet_gid') or '0'),
            'portrait':    'true'  if cfg.get('portrait', False)     else 'false',
            'fitw':        'true'  if cfg.get('fit_width', True)      else 'false',
            'gridlines':   'false' if cfg.get('hide_gridlines', True) else 'true',
            'sheetnames':    'false',
            'printtitle':    'false',
            'pagenumbers':   'false',
            'top_margin':    '0',
            'bottom_margin': '0',
            'left_margin':   '0',
            'right_margin':  '0',
        }
        export_range = (cfg.get('export_range') or '').strip()
        if export_range:
            params['range'] = export_range

        url  = (f"https://docs.google.com/spreadsheets/d/{cfg['sheet_id']}/export?"
                + urllib.parse.urlencode(params))
        sess = AuthorizedSession(creds)
        resp = sess.get(url)
        resp.raise_for_status()

        doc  = fitz.open(stream=resp.content, filetype='pdf')
        page = doc[0]
        pix  = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        dest = os.path.join(media.folder, f'_sheet_{key}.png')
        pix.save(dest)

        with _sheet_cache_lock:
            _sheet_cache[key] = {'fetched_at': datetime.now(), 'error': None}

    except Exception as e:
        logger.warning('Sheet refresh failed for %s: %s', key, e)
        with _sheet_cache_lock:
            existing = _sheet_cache.get(key, {})
            _sheet_cache[key] = {'fetched_at': existing.get('fetched_at'), 'error': str(e)}


def _schedule_sheet(key: str, cfg: dict) -> None:
    job_id = f'sheet_{key}'
    if _sheet_scheduler.get_job(job_id):
        _sheet_scheduler.remove_job(job_id)
    interval = max(1, int(cfg.get('refresh_interval_mins', 15)))
    _sheet_scheduler.add_job(
        _refresh_sheet, 'interval', minutes=interval,
        id=job_id, args=[key], replace_existing=True,
    )


def _unschedule_sheet(key: str) -> None:
    job_id = f'sheet_{key}'
    if _sheet_scheduler.get_job(job_id):
        _sheet_scheduler.remove_job(job_id)


# Seed cache and schedule jobs for all enabled sheets on startup
for _key, _cfg in signage_config.get_all_sheets().items():
    if _cfg.get('enabled'):
        _schedule_sheet(_key, _cfg)
        _refresh_sheet(_key)

if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('PRODUCTION') == '1':
    _sheet_scheduler.start()

# ============================================================================
# Routes — index
# ============================================================================

@signage_bp.route('/')
@access_required('signage')
def index():
    data      = signage_config.get_all()
    slideshows = data.get('slideshows', {})
    sheets    = data.get('sheets', {})
    return render_template('signage/index.html', slideshows=slideshows, sheets=sheets)


# ============================================================================
# Routes — slideshows
# ============================================================================

@signage_bp.route('/api/get-data')
@access_required('signage')
def get_slideshows():
    data = signage_config.get_all()
    return jsonify({'success': True, 'slideshows': data.get('slideshows'), 'media': data.get('media')})


@signage_bp.route('/api/slideshow/create', methods=['POST'])
@access_required('signage')
def api_create_slideshow():
    body = request.get_json(force=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Name is required'}), 400
    description = (body.get('description') or '').strip()
    speed_secs  = max(1, int(body.get('speed_secs', 20) or 20))
    key, cfg    = signage_config.create(name, description, speed_secs)
    return jsonify({'success': True, 'key': key, 'config': cfg})


@signage_bp.route('/api/slideshow/<name>/delete', methods=['POST'])
@access_required('signage')
def api_delete_slideshow(name):
    if not signage_config.delete(name):
        return jsonify({'success': False, 'error': 'Slideshow not found'}), 404
    return jsonify({'success': True})


@signage_bp.route('/api/update/<name>', methods=['POST'])
@access_required('signage')
def api_update_slideshow(name):
    body = request.get_json(force=True) or {}
    allowed = {'name', 'description', 'speed_secs', 'enabled', 'media'}
    fields  = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return jsonify({'success': False, 'error': 'No valid fields provided'}), 400
    updated = signage_config.update(name, fields)
    if not updated:
        return jsonify({'success': False, 'error': 'Slideshow not found'}), 404
    return jsonify({'success': True, 'config': updated})


@signage_bp.route('/api/slideshow/<name>')
@login_required
def api_get_slideshow(name):
    slideshows = signage_config.get_all().get('slideshows', {})
    cfg = slideshows.get(name)
    if cfg is None:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'config': cfg})


@signage_bp.route('/slideshow/<name>')
@login_required
def slideshow_view(name):
    slideshows = signage_config.get_all().get('slideshows', {})
    cfg = slideshows.get(name)
    if cfg is None:
        abort(404)
    return render_template('signage/slideshow.html', slideshow_key=name, cfg=cfg)


# ============================================================================
# Routes — media files
# ============================================================================

@signage_bp.route('/api/media')
@access_required('signage')
def api_get_media():
    return jsonify({'success': True, 'media': media.get_all()})


@signage_bp.route('/media/file/<path:filename>')
@access_required('signage')
def serve_media_file(filename):
    if not media.get_file(filename):
        return jsonify({'error': 'Not found'}), 404
    return send_from_directory(media.folder, filename)


@signage_bp.route('/api/media/upload', methods=['POST'])
@access_required('signage')
def api_upload_media():
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'success': False, 'error': 'No files provided'}), 400
    results = []
    for f in files:
        if not f.filename:
            continue
        item = media.save_file(f)
        if item:
            results.append({'filename': item['filename'], 'success': True})
        else:
            results.append({'filename': f.filename, 'success': False, 'error': 'Invalid file type'})
    return jsonify({'success': True, 'results': results})


@signage_bp.route('/api/media/delete/<path:filename>', methods=['POST'])
@access_required('signage')
def api_delete_media(filename):
    if not media.delete_file(filename):
        return jsonify({'success': False, 'error': 'Not found or invalid file type'}), 404
    signage_config.remove_media_from_all(filename)
    return jsonify({'success': True})


# ============================================================================
# Routes — sheet resources
# ============================================================================

@signage_bp.route('/api/sheet')
@access_required('signage')
def api_get_sheets():
    sheets = signage_config.get_all_sheets()
    result = {}
    with _sheet_cache_lock:
        for key, cfg in sheets.items():
            cache = _sheet_cache.get(key, {})
            result[key] = {
                **cfg,
                'fetched_at': cache.get('fetched_at').isoformat() if cache.get('fetched_at') else None,
                'error':      cache.get('error'),
            }
    return jsonify({'success': True, 'sheets': result})


@signage_bp.route('/api/sheet/create', methods=['POST'])
@access_required('signage')
def api_create_sheet():
    body     = request.get_json(force=True) or {}
    name     = (body.get('name') or '').strip()
    sheet_id = (body.get('sheet_id') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Name is required'}), 400
    if not sheet_id:
        return jsonify({'success': False, 'error': 'Sheet ID is required'}), 400
    interval = max(1, int(body.get('refresh_interval_mins', 15) or 15))
    extra = {k: body[k] for k in ('portrait', 'fit_width', 'hide_gridlines', 'sheet_gid', 'export_range') if k in body}
    key, cfg = signage_config.create_sheet(name, sheet_id, interval, **extra)
    if cfg.get('enabled'):
        _schedule_sheet(key, cfg)
        _refresh_sheet(key)
    return jsonify({'success': True, 'key': key, 'config': cfg})


@signage_bp.route('/api/sheet/<key>/update', methods=['POST'])
@access_required('signage')
def api_update_sheet(key):
    body    = request.get_json(force=True) or {}
    updated = signage_config.update_sheet(key, body)
    if not updated:
        return jsonify({'success': False, 'error': 'Sheet not found'}), 404
    # Reschedule if interval or enabled changed
    _unschedule_sheet(key)
    if updated.get('enabled'):
        _schedule_sheet(key, updated)
    return jsonify({'success': True, 'config': updated})


@signage_bp.route('/api/sheet/<key>/delete', methods=['POST'])
@access_required('signage')
def api_delete_sheet(key):
    _unschedule_sheet(key)
    with _sheet_cache_lock:
        _sheet_cache.pop(key, None)
    if not signage_config.delete_sheet(key):
        return jsonify({'success': False, 'error': 'Sheet not found'}), 404
    signage_config.remove_media_from_all(f'sheet:{key}')
    png = os.path.join(media.folder, f'_sheet_{key}.png')
    try:
        os.remove(png)
    except OSError:
        pass
    return jsonify({'success': True})


@signage_bp.route('/api/sheet/<key>/refresh', methods=['POST'])
@access_required('signage')
def api_refresh_sheet(key):
    cfg = signage_config.get_sheet(key)
    if not cfg:
        return jsonify({'success': False, 'error': 'Sheet not found'}), 404
    _refresh_sheet(key)
    with _sheet_cache_lock:
        cache = _sheet_cache.get(key, {})
    fetched_at = cache.get('fetched_at')
    return jsonify({
        'success':    True,
        'error':      cache.get('error'),
        'fetched_at': fetched_at.isoformat() if fetched_at else None,
    })


# ============================================================================
# Routes — logs
# ============================================================================

@signage_bp.route('/api/logs')
@login_required
def api_get_logs():
    limit  = request.args.get('limit', 50, type=int)
    logs   = signage_log.get_logs(limit=limit)
    errors = signage_log.get_errors(limit=limit)
    return jsonify({'success': True, 'logs': logs, 'errors': errors})


@signage_bp.route('/api/logs/clear', methods=['POST'])
@login_required
def api_clear_logs():
    count = signage_log.clear_logs()
    return jsonify({'success': True, 'count': count})


@signage_bp.route('/api/errors/clear', methods=['POST'])
@login_required
def api_clear_errors():
    count = signage_log.clear_errors()
    return jsonify({'success': True, 'count': count})
