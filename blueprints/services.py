import logging
import os
import re
import secrets
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Blueprint, jsonify, render_template, request, session

from API_Service_Network.VariousInternalServices.data import ServicesConfig, ServicesLog, ShortcutState
from blueprints.auth import access_required, login_required
from common.Clients.Email.EmailApi import send_email
from config import Config

services_bp = Blueprint('services', __name__)
logger = logging.getLogger(__name__)

# Instantiate data objects at module level
services_config = ServicesConfig()
services_log    = ServicesLog()
shortcut_state  = ShortcutState()

SERVICE_DESCRIPTIONS = {
    'on-time-performance': 'Queries Fishbowl for order completion data and updates the On-Time Performance Google Sheet.',
    'tax-system-health':   'Checks Fishbowl for tax compliance issues (product tax codes and customer exempt statuses).',
    'vendor-tracker':      'Finds parts currently at vendor via Fishbowl and updates the Vendor Tracker Google Sheet.',
    'wip-update':          'Updates the WIP Tracker Google Sheet with current work-in-progress data from Fishbowl.',
    'onedrive-shortcuts':  'Adds "Add shortcut to OneDrive" shortcuts for configured SharePoint libraries to target '
                           'users\' OneDrive, and removes them when a sync is deleted or a user leaves its targets.',
}

# ============================================================================
# Helper functions
# ============================================================================

def _maybe_notify(cfg: dict, success: bool, log_data: dict) -> None:
    mode       = cfg.get('notify_mode', 'none')
    recipients = cfg.get('notify_recipients', [])
    if not recipients or mode == 'none':
        return
    if mode == 'failure' and success:
        return

    label        = cfg.get('label', 'Service')
    status_word  = 'Success' if success else 'Error'
    status_color = '#166534' if success else '#991b1b'
    status_bg    = '#dcfce7' if success else '#fee2e2'

    log_rows = ''
    for func, messages in log_data.items():
        log_rows += (
            f'<tr><td style="font-weight:bold;padding:4px 8px;vertical-align:top;">{func}</td>'
            f'<td style="padding:4px 8px;">' + '<br>'.join(str(m) for m in messages) + '</td></tr>'
        )

    html_body = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:0 auto;">
        <h2 style="color:#1e40af;">Internal Services — {label}</h2>
        <p>
            <span style="background:{status_bg};color:{status_color};padding:4px 12px;
                         border-radius:9999px;font-weight:bold;font-size:13px;">
                {status_word}
            </span>
            &nbsp; Run completed at {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </p>
        <table style="border-collapse:collapse;width:100%;font-size:13px;margin-top:12px;">
            {log_rows}
        </table>
        <p style="color:#6b7280;font-size:12px;margin-top:16px;">
            This is an automated notification from Internal Services.
        </p>
    </div>
    """
    try:
        send_email(
            subject=f'[Internal Services] {label} — {status_word}',
            html_body=html_body,
            recipients=recipients,
            sender=Config.SENDER_EMAIL,
        )
    except Exception as e:
        logger.error(f'Notification email failed for {label}: {e}')

# ============================================================================
# Per-service runner functions
# Called directly by APScheduler and by Run Now routes (via a thread).
# Mirrors retail.py calling sync_manager.determine_sync() from both contexts.
# To add custom kwargs for a service, add them to the service function call below.
# ============================================================================

# WORKING AND COMPLETED
def run_on_time_performance(triggered_by:str='scheduler') -> None:
    services_config.set_running('on-time-performance', True)
    config = services_config.get('on-time-performance')
    notify_recipients = config['notify_recipients']
    notify_mode = config['notify_mode']

    try:
        from API_Service_Network.VariousInternalServices.scripts.OnTimePerformance import on_time_performance
        log_obj  = on_time_performance(result_recipients=notify_recipients, notification_mode=notify_mode)
        success  = log_obj.error_flag() == 0
        log_data = log_obj.get_log()
    except Exception as e:
        success, log_data = False, {'error': [str(e)]}
        logger.error(f'on-time-performance failed: {e}')

    services_config.save_result('on-time-performance', success)
    services_log.append_run('on-time-performance', 'success' if success else 'error', triggered_by, log_data)

# WORKING AND COMPLETED
def run_tax_system_health(triggered_by:str='scheduler') -> None:
    services_config.set_running('tax-system-health', True)
    config = services_config.get('tax-system-health')
    notify_recipients = config['notify_recipients']
    notify_mode = config['notify_mode']

    try:
        from API_Service_Network.VariousInternalServices.scripts.TaxSystemHealth import tax_system_health
        log_obj  = tax_system_health(result_recipients=notify_recipients, notification_mode=notify_mode)
        success  = log_obj.error_flag() == 0
        log_data = log_obj.get_log()
    except Exception as e:
        success, log_data = False, {'error': [str(e)]}
        logger.error(f'tax-system-health failed: {e}')

    services_config.save_result('tax-system-health', success)
    services_log.append_run('tax-system-health', 'success' if success else 'error', triggered_by, log_data)

# WORKING AND COMPLETED
def run_vendor_tracker(triggered_by:str='scheduler') -> None:
    services_config.set_running('vendor-tracker', True)
    config = services_config.get('vendor-tracker')
    notify_recipients = config['notify_recipients']
    notify_mode = config['notify_mode']

    try:
        from API_Service_Network.VariousInternalServices.scripts.VendorTracker import vendor_tracker
        log_obj  = vendor_tracker(result_recipients=notify_recipients, notification_mode=notify_mode)
        success  = log_obj.error_flag() == 0
        log_data = log_obj.get_log()
    except Exception as e:
        success, log_data = False, {'error': [str(e)]}
        logger.error(f'vendor-tracker failed: {e}')
    services_config.save_result('vendor-tracker', success)
    services_log.append_run('vendor-tracker', 'success' if success else 'error', triggered_by, log_data)

# WORKING AND COMPLETED
def run_wip_update(triggered_by:str='scheduler') -> None:
    services_config.set_running('wip-update', True)
    try:
        from API_Service_Network.VariousInternalServices.scripts.WipUpdate import wip_update
        log_obj  = wip_update(result_recipients=[])
        success  = log_obj.error_flag() == 0
        log_data = log_obj.get_log()
    except Exception as e:
        success, log_data = False, {'error': [str(e)]}
        logger.error(f'wip-update failed: {e}')
    services_config.save_result('wip-update', success)
    services_log.append_run('wip-update', 'success' if success else 'error', triggered_by, log_data)
    _maybe_notify(services_config.get('wip-update'), success, log_data)

# WORKING — see .claude/12. sharepoint_onedrive_shortcut.md
def run_onedrive_shortcuts(triggered_by:str='scheduler') -> None:
    services_config.set_running('onedrive-shortcuts', True)
    cfg = services_config.get('onedrive-shortcuts')
    try:
        from API_Service_Network.VariousInternalServices.scripts.OneDriveShortcuts import onedrive_shortcuts
        log_obj  = onedrive_shortcuts(syncs=cfg.get('syncs', []), state=shortcut_state)
        success  = log_obj.error_flag() == 0
        log_data = log_obj.get_log()
    except Exception as e:
        success, log_data = False, {'error': [str(e)]}
        logger.error(f'onedrive-shortcuts failed: {e}')
    services_config.save_result('onedrive-shortcuts', success)
    services_log.append_run('onedrive-shortcuts', 'success' if success else 'error', triggered_by, log_data)
    _maybe_notify(services_config.get('onedrive-shortcuts'), success, log_data)

# Maps service name → runner. Used by the scheduler on startup and by the
# generic /config route when rescheduling after a settings change.
_RUNNERS = {
    'on-time-performance': run_on_time_performance,
    'tax-system-health':   run_tax_system_health,
    'vendor-tracker':      run_vendor_tracker,
    'wip-update':          run_wip_update,
    'onedrive-shortcuts':  run_onedrive_shortcuts,
}

# ============================================================================
# Scheduler
# ============================================================================

scheduler = BackgroundScheduler()


def _schedule(service_name: str, cfg: dict) -> None:
    """Add or replace the APScheduler job for a service. No-op if not enabled."""
    runner = _RUNNERS.get(service_name)
    if not runner:
        return

    job_id = f'job_{service_name}'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if not cfg.get('enabled'):
        return

    if cfg.get('schedule_type') == 'cron' and cfg.get('schedule_cron'):
        scheduler.add_job(
            func=runner,
            trigger='cron',
            id=job_id,
            replace_existing=True,
            **cfg['schedule_cron'],
        )
    else:
        # Anchor interval to last_run so a server restart doesn't reset the clock.
        start_date = None
        if cfg.get('last_run'):
            try:
                start_date = datetime.fromisoformat(cfg['last_run'])
            except (ValueError, TypeError):
                pass
        scheduler.add_job(
            func=runner,
            trigger='interval',
            minutes=cfg.get('schedule_interval_minutes', 1440),
            start_date=start_date,
            id=job_id,
            replace_existing=True,
        )
    logger.info(f"Scheduled {service_name} (type={cfg.get('schedule_type', 'interval')})")


def _unschedule(service_name: str) -> None:
    job_id = f'job_{service_name}'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


# On startup, restore schedules for any enabled services.
for _name, _cfg in services_config.get_all().items():
    if _cfg.get('enabled'):
        _schedule(_name, _cfg)

# Start scheduler only in the correct process (mirrors retail.py guard):
#   WERKZEUG_RUN_MAIN='true' → Werkzeug worker child (dev mode)
#   PRODUCTION='1'           → waitress production run (set in serve.py)
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('PRODUCTION') == '1':
    scheduler.start()


# ============================================================================
# Routes — page
# ============================================================================

@services_bp.route('/')
@access_required('services')
def index():
    config = services_config.get_all()
    return render_template('services/index.html', services=config, descriptions=SERVICE_DESCRIPTIONS)


@services_bp.route('/how-to')
@access_required('services')
def how_to():
    return render_template('services/how_to.html')


# ============================================================================
# Routes — per-service Run Now
# Thin HTTP wrappers — start the runner in a background thread and return JSON.
# ============================================================================

def _start_thread(service_name: str, runner) -> tuple:
    """Guard + thread spin-up shared by all Run Now routes."""
    cfg = services_config.get(service_name)
    if not cfg:
        return False, 'Unknown service', 404
    if cfg.get('running'):
        return False, 'Service is already running', 409
    threading.Thread(target=runner, kwargs={'triggered_by': 'manual'}, daemon=True).start()
    return True, cfg['label'], 200


@services_bp.route('/run/on-time-performance', methods=['POST'])
@login_required
def route_run_on_time_performance():
    ok, msg, code = _start_thread('on-time-performance', run_on_time_performance)
    if not ok:
        return jsonify({'error': msg}), code
    return jsonify({'success': True, 'message': f'{msg} started'})


@services_bp.route('/run/tax-system-health', methods=['POST'])
@login_required
def route_run_tax_system_health():
    ok, msg, code = _start_thread('tax-system-health', run_tax_system_health)
    if not ok:
        return jsonify({'error': msg}), code
    return jsonify({'success': True, 'message': f'{msg} started'})


@services_bp.route('/run/vendor-tracker', methods=['POST'])
@login_required
def route_run_vendor_tracker():
    ok, msg, code = _start_thread('vendor-tracker', run_vendor_tracker)
    if not ok:
        return jsonify({'error': msg}), code
    return jsonify({'success': True, 'message': f'{msg} started'})


@services_bp.route('/run/wip-update', methods=['POST'])
@login_required
def route_run_wip_update():
    ok, msg, code = _start_thread('wip-update', run_wip_update)
    if not ok:
        return jsonify({'error': msg}), code
    return jsonify({'success': True, 'message': f'{msg} started'})


@services_bp.route('/run/onedrive-shortcuts', methods=['POST'])
@login_required
def route_run_onedrive_shortcuts():
    ok, msg, code = _start_thread('onedrive-shortcuts', run_onedrive_shortcuts)
    if not ok:
        return jsonify({'error': msg}), code
    return jsonify({'success': True, 'message': f'{msg} started'})


# ============================================================================
# Routes — status, logs, config
# ============================================================================

@services_bp.route('/status', methods=['GET'])
@login_required
def get_status():
    config = services_config.get_all()
    for name, cfg in config.items():
        job = scheduler.get_job(f'job_{name}')
        cfg['next_run'] = job.next_run_time.isoformat() if job and job.next_run_time else None
    return jsonify({'success': True, 'services': config})


@services_bp.route('/logs/<service_name>', methods=['GET'])
@login_required
def get_service_log(service_name):
    if service_name not in _RUNNERS:
        return jsonify({'error': 'Unknown service'}), 404
    return jsonify({'success': True, 'data': services_log.get_logs(service_name)})


@services_bp.route('/logs/<service_name>', methods=['DELETE'])
@login_required
def clear_service_log(service_name):
    if service_name not in _RUNNERS:
        return jsonify({'error': 'Unknown service'}), 404
    count = services_log.clear_logs(service_name)
    return jsonify({'success': True, 'cleared': count})


@services_bp.route('/logs/<service_name>/errors', methods=['DELETE'])
@login_required
def clear_service_errors(service_name):
    if service_name not in _RUNNERS:
        return jsonify({'error': 'Unknown service'}), 404
    count = services_log.clear_errors(service_name)
    return jsonify({'success': True, 'cleared': count})


@services_bp.route('/config/<service_name>', methods=['PUT'])
@login_required
def update_service_config(service_name):
    try:
        if service_name not in _RUNNERS:
            return jsonify({'error': 'Unknown service'}), 404

        req_data = request.get_json()
        updates  = {}

        # --- Schedule fields ---
        if 'schedule_type' in req_data:
            updates['schedule_type'] = req_data['schedule_type']
        if 'schedule_interval_minutes' in req_data:
            interval = int(req_data['schedule_interval_minutes'])
            if interval < 1:
                return jsonify({'error': 'Interval must be at least 1 minute'}), 400
            updates['schedule_interval_minutes'] = interval
        if 'schedule_cron' in req_data:
            updates['schedule_cron'] = req_data['schedule_cron']
        if 'enabled' in req_data:
            updates['enabled'] = bool(req_data['enabled'])

        # --- Notification fields ---
        if 'notify_mode' in req_data:
            if req_data['notify_mode'] not in ('none', 'always', 'failure'):
                return jsonify({'error': 'Invalid notify_mode'}), 400
            updates['notify_mode'] = req_data['notify_mode']
        if 'notify_recipients' in req_data:
            updates['notify_recipients'] = list(req_data['notify_recipients'])

        updated = services_config.update(service_name, updates)
        _schedule(service_name, updated)

        job = scheduler.get_job(f'job_{service_name}')
        updated['next_run'] = job.next_run_time.isoformat() if job and job.next_run_time else None

        return jsonify({'success': True, 'config': updated})

    except Exception as e:
        logger.error(f'Error updating config for {service_name}: {e}')
        return jsonify({'error': str(e)}), 500


# ============================================================================
# Routes — OneDrive Shortcuts (sync management, validate, preview)
# See .claude/12. sharepoint_onedrive_shortcut.md
# ============================================================================

_SHORTCUT_KEY        = 'onedrive-shortcuts'
_SYNC_ID_RE          = re.compile(r'^[0-9a-f]{8}$')
_SITE_URL_RE         = re.compile(r'^https://[A-Za-z0-9-]+\.sharepoint\.com(/.*)?$', re.IGNORECASE)
_TARGET_TYPES        = ('all_users', 'groups', 'users')
_INVALID_NAME_CHARS  = set('"*:<>?/\\|')

# Preview runs in a background thread (it can take longer than the IIS proxy timeout on a large
# tenant); the UI polls GET /onedrive-shortcuts/preview for the result.
_preview_lock  = threading.Lock()
_preview_state = {'running': False, 'started_at': None, 'result': None, 'error': None}


def _require_write():
    """Returns a 403 response tuple if the current user lacks services write access, else None."""
    if session.get('access', {}).get('services') != 'write':
        return jsonify({'error': 'Write access to Services is required'}), 403
    return None


def _clean_list(values) -> list:
    """Strips, drops blanks, and de-duplicates (case-insensitive, order kept) a list of strings."""
    seen, out = set(), []
    for v in values or []:
        v = str(v).strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _validate_syncs(raw: list) -> tuple:
    """Validates and normalizes a submitted sync list. Returns (clean_syncs, error_message)."""
    if not isinstance(raw, list):
        return None, 'syncs must be a list'
    clean, names, ids = [], set(), set()
    for i, s in enumerate(raw, start=1):
        if not isinstance(s, dict):
            return None, f'Sync #{i} is invalid'
        name = str(s.get('name', '')).strip()
        label = f"Sync '{name}'" if name else f'Sync #{i}'
        if not name:
            return None, f'{label}: name is required'
        if name.lower() in names:
            return None, f"Sync names must be unique ('{name}' is used twice)"
        names.add(name.lower())

        site_url = str(s.get('site_url', '')).strip()
        if not _SITE_URL_RE.match(site_url):
            return None, f'{label}: site URL must look like https://<tenant>.sharepoint.com/sites/<site>'
        library = str(s.get('library_name', '')).strip()
        if not library:
            return None, f'{label}: library name is required'
        shortcut_name = str(s.get('shortcut_name', '') or '').strip()
        if shortcut_name and (_INVALID_NAME_CHARS & set(shortcut_name) or shortcut_name.endswith('.')):
            return None, f'{label}: shortcut name cannot contain " * : < > ? / \\ | or end with a period'

        target_type = s.get('target_type')
        if target_type not in _TARGET_TYPES:
            return None, f'{label}: target type must be one of {", ".join(_TARGET_TYPES)}'
        targets = _clean_list(s.get('targets')) if target_type != 'all_users' else []
        if target_type != 'all_users' and not targets:
            return None, f'{label}: add at least one {"group" if target_type == "groups" else "user"}'

        sync_id = str(s.get('id', '')).strip().lower()
        if not _SYNC_ID_RE.match(sync_id) or sync_id in ids:
            sync_id = secrets.token_hex(4)
            while sync_id in ids:
                sync_id = secrets.token_hex(4)
        ids.add(sync_id)

        clean.append({
            'id':            sync_id,
            'name':          name,
            'enabled':       bool(s.get('enabled', True)),
            'site_url':      site_url.rstrip('/'),
            'library_name':  library,
            'shortcut_name': shortcut_name,
            'target_type':   target_type,
            'targets':       targets,
            'exclude_upns':  _clean_list(s.get('exclude_upns')),
        })
    return clean, None


@services_bp.route('/onedrive-shortcuts/syncs', methods=['PUT'])
@login_required
def save_shortcut_syncs():
    denied = _require_write()
    if denied:
        return denied
    cfg = services_config.get(_SHORTCUT_KEY)
    if cfg.get('running'):
        return jsonify({'error': 'OneDrive Shortcuts is running - wait for it to finish before saving syncs'}), 409

    syncs, error = _validate_syncs((request.get_json() or {}).get('syncs'))
    if error:
        return jsonify({'error': error}), 400

    try:
        updated = services_config.update(_SHORTCUT_KEY, {'syncs': syncs})
        queued  = shortcut_state.reconcile_with_config(syncs)
    except Exception as e:
        logger.error(f'Error saving OneDrive shortcut syncs: {e}')
        return jsonify({'error': str(e)}), 500

    # Process queued removals promptly rather than waiting for the next scheduled run.
    run_started = False
    if queued and not services_config.get(_SHORTCUT_KEY).get('running'):
        threading.Thread(target=run_onedrive_shortcuts, kwargs={'triggered_by': 'sync-change'}, daemon=True).start()
        run_started = True

    return jsonify({'success': True, 'syncs': updated['syncs'], 'queued_removals': queued,
                    'run_started': run_started, 'state': shortcut_state.summary()})


@services_bp.route('/onedrive-shortcuts/state', methods=['GET'])
@login_required
def get_shortcut_state():
    return jsonify({'success': True, 'state': shortcut_state.summary()})


@services_bp.route('/onedrive-shortcuts/validate', methods=['POST'])
@login_required
def validate_shortcut_sync():
    syncs, error = _validate_syncs([(request.get_json() or {}).get('sync')])
    if error:
        return jsonify({'error': error}), 400
    try:
        from API_Service_Network.VariousInternalServices.scripts.OneDriveShortcuts import validate_sync
        return jsonify({'success': True, 'result': validate_sync(syncs[0])})
    except Exception as e:
        logger.error(f'OneDrive shortcut validate failed: {e}')
        return jsonify({'error': str(e)}), 500


def _run_preview() -> None:
    try:
        from API_Service_Network.VariousInternalServices.scripts.OneDriveShortcuts import preview_onedrive_shortcuts
        result = preview_onedrive_shortcuts(services_config.get(_SHORTCUT_KEY).get('syncs', []), shortcut_state)
        with _preview_lock:
            _preview_state.update(result=result, error=None)
    except Exception as e:
        logger.error(f'OneDrive shortcut preview failed: {e}')
        with _preview_lock:
            _preview_state.update(result=None, error=str(e))
    finally:
        with _preview_lock:
            _preview_state['running'] = False


@services_bp.route('/onedrive-shortcuts/preview', methods=['POST'])
@login_required
def start_shortcut_preview():
    with _preview_lock:
        if _preview_state['running']:
            return jsonify({'success': True, 'message': 'Preview already running'})
        _preview_state.update(running=True, started_at=datetime.now().isoformat(), result=None, error=None)
    threading.Thread(target=_run_preview, daemon=True).start()
    return jsonify({'success': True, 'message': 'Preview started'})


@services_bp.route('/onedrive-shortcuts/preview', methods=['GET'])
@login_required
def get_shortcut_preview():
    with _preview_lock:
        return jsonify({'success': True, **_preview_state})


@services_bp.route('/onedrive-shortcuts/force-removals/<sync_id>', methods=['POST'])
@login_required
def allow_shortcut_removals(sync_id):
    denied = _require_write()
    if denied:
        return denied
    if not shortcut_state.set_force_removals(sync_id, True):
        return jsonify({'error': 'Unknown sync'}), 404
    return jsonify({'success': True, 'state': shortcut_state.summary()})
