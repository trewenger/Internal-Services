import threading
import sys
import os
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_RUNNING
import logging

from blueprints.auth import login_required, access_required
from API_Service_Network.VariousInternalServices import load_services_config, save_services_config

services_bp = Blueprint('services', __name__)

logger = logging.getLogger(__name__)

# --------------------------------- Service Registry --------------------------------- #
# Lazy imports — the scripts call load_dotenv() at module level so we import them
# here after the app's .env has been loaded.

def _get_service_func(service_name: str):
    """Returns the callable for the given service name."""
    if service_name == 'on-time-performance':
        from API_Service_Network.VariousInternalServices.OnTimePerformance import on_time_performance
        return on_time_performance
    elif service_name == 'tax-system-health':
        from API_Service_Network.VariousInternalServices.TaxSystemHealth import tax_system_health
        return tax_system_health
    elif service_name == 'vendor-tracker':
        from API_Service_Network.VariousInternalServices.VendorTracker import vendor_tracker
        return vendor_tracker
    elif service_name == 'wip-update':
        from API_Service_Network.VariousInternalServices.WipUpdate import wip_update
        return wip_update
    return None


SERVICE_DESCRIPTIONS = {
    'on-time-performance': 'Queries Fishbowl for order completion data and updates the On-Time Performance Google Sheet.',
    'tax-system-health':   'Checks Fishbowl for tax compliance issues (product tax codes and customer exempt statuses).',
    'vendor-tracker':      'Finds parts currently at vendor via Fishbowl and updates the Vendor Tracker Google Sheet.',
    'wip-update':          'Updates the WIP Tracker Google Sheet with current work-in-progress data from Fishbowl.',
}

# ---------------------------------- Scheduler --------------------------------------- #

scheduler = BackgroundScheduler()
scheduler.start()


def _run_service_background(service_name: str):
    """Runs a service in a background thread and saves the result."""
    config = load_services_config()
    config[service_name]['running'] = True
    save_services_config(config)

    try:
        func = _get_service_func(service_name)
        if func is None:
            raise ValueError(f"Unknown service: {service_name}")

        log_obj = func(result_recipients=[])
        success = log_obj.error_flag() == 0
        log_data = log_obj.get_log()

    except Exception as e:
        success = False
        log_data = {'error': [str(e)]}
        logger.error(f"Service {service_name} failed: {e}")

    config = load_services_config()
    config[service_name]['running'] = False
    config[service_name]['last_run'] = datetime.now().isoformat()
    config[service_name]['last_status'] = 'success' if success else 'error'
    config[service_name]['last_log'] = log_data
    save_services_config(config)


def schedule_service(service_name: str, interval_minutes: int):
    """Adds or replaces a scheduled job for the given service."""
    job_id = f'service_{service_name}'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(
        func=_run_service_background,
        args=[service_name],
        trigger='interval',
        minutes=interval_minutes,
        id=job_id,
        replace_existing=True
    )
    logger.info(f"Scheduled {service_name} every {interval_minutes} minutes")


def unschedule_service(service_name: str):
    job_id = f'service_{service_name}'
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


# On startup, schedule any services that were enabled
_startup_config = load_services_config()
for _name, _cfg in _startup_config.items():
    if _cfg.get('enabled'):
        schedule_service(_name, _cfg.get('schedule_interval_minutes', 1440))

# ------------------------------------ Routes ---------------------------------------- #

@services_bp.route('/')
@access_required('services')
def index():
    config = load_services_config()
    return render_template('services/index.html', services=config, descriptions=SERVICE_DESCRIPTIONS)


@services_bp.route('/run/<service_name>', methods=['POST'])
@login_required
def run_service(service_name):
    config = load_services_config()
    if service_name not in config:
        return jsonify({'error': 'Unknown service'}), 404

    if config[service_name].get('running'):
        return jsonify({'error': 'Service is already running'}), 409

    thread = threading.Thread(target=_run_service_background, args=[service_name], daemon=True)
    thread.start()

    return jsonify({'success': True, 'message': f'{config[service_name]["label"]} started'})


@services_bp.route('/status', methods=['GET'])
@login_required
def get_status():
    config = load_services_config()
    return jsonify({'success': True, 'services': config})


@services_bp.route('/config/<service_name>', methods=['PUT'])
@login_required
def update_service_config(service_name):
    try:
        config = load_services_config()
        if service_name not in config:
            return jsonify({'error': 'Unknown service'}), 404

        req_data = request.get_json()

        if 'schedule_interval_minutes' in req_data:
            interval = int(req_data['schedule_interval_minutes'])
            if interval < 1:
                return jsonify({'error': 'Interval must be at least 1 minute'}), 400
            config[service_name]['schedule_interval_minutes'] = interval

        if 'enabled' in req_data:
            config[service_name]['enabled'] = bool(req_data['enabled'])

        save_services_config(config)

        # Reschedule based on new settings
        if config[service_name]['enabled']:
            schedule_service(service_name, config[service_name]['schedule_interval_minutes'])
        else:
            unschedule_service(service_name)

        return jsonify({'success': True, 'config': config[service_name]})

    except Exception as e:
        logger.error(f"Error updating service config: {e}")
        return jsonify({'error': str(e)}), 500
