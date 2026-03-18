import logging
import os
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Blueprint, jsonify, render_template, request

from API_Service_Network.VariousInternalServices.data import ServicesConfig, ServicesLog
from blueprints.auth import access_required, login_required
from common.Clients.Email.EmailApi import send_email
from config import Config

services_bp = Blueprint('services', __name__)
logger = logging.getLogger(__name__)

# Instantiate data objects at module level
services_config = ServicesConfig()
services_log    = ServicesLog()

SERVICE_DESCRIPTIONS = {
    'on-time-performance': 'Queries Fishbowl for order completion data and updates the On-Time Performance Google Sheet.',
    'tax-system-health':   'Checks Fishbowl for tax compliance issues (product tax codes and customer exempt statuses).',
    'vendor-tracker':      'Finds parts currently at vendor via Fishbowl and updates the Vendor Tracker Google Sheet.',
    'wip-update':          'Updates the WIP Tracker Google Sheet with current work-in-progress data from Fishbowl.',
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


def run_on_time_performance(triggered_by:str='scheduler') -> None:
    services_config.set_running('on-time-performance', True)
    try:
        from API_Service_Network.VariousInternalServices.scripts.OnTimePerformance import on_time_performance
        log_obj  = on_time_performance(result_recipients=[], custom_headers=None)
        success  = log_obj.error_flag() == 0
        log_data = log_obj.get_log()
    except Exception as e:
        success, log_data = False, {'error': [str(e)]}
        logger.error(f'on-time-performance failed: {e}')
    services_config.save_result('on-time-performance', success)
    services_log.append_run('on-time-performance', 'success' if success else 'error', triggered_by, log_data)
    _maybe_notify(services_config.get('on-time-performance'), success, log_data)

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

# Maps service name → runner. Used by the scheduler on startup and by the
# generic /config route when rescheduling after a settings change.
_RUNNERS = {
    'on-time-performance': run_on_time_performance,
    'tax-system-health':   run_tax_system_health,
    'vendor-tracker':      run_vendor_tracker,
    'wip-update':          run_wip_update,
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
