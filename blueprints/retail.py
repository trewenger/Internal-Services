from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import logging, os

from config import Config
from API_Service_Network.RetailInventoryManager.data import InventoryData, Logger
from API_Service_Network.RetailInventoryManager.sync import FishbowlSync
from blueprints.auth import login_required, access_required

retail_bp = Blueprint('retail', __name__)

# Initialize data/sync objects
data = InventoryData()
log = Logger()
sync_manager = FishbowlSync()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------ Background scheduler -------------------------------- #

scheduler = BackgroundScheduler()
SYNC_JOB = None
SALES_JOB = None


def remove_job(job_name: str) -> bool:
    global SYNC_JOB, SALES_JOB
    job_removed = False

    if job_name == "fishbowl_sales":
        if scheduler.get_job('fishbowl_sales') is not None:
            try:
                scheduler.remove_job('fishbowl_sales', 'default')
                job_removed = True
            except:
                try:
                    SALES_JOB.remove()
                    job_removed = True
                except Exception as e:
                    print(f"\n WARNING UNABLE TO REMOVE THE SALES JOB: {e} \n ")
                    log.log_error(
                        error_type='scheduler_error',
                        message=f"Failed to remove sales job: {str(e)}",
                        source='retail.py:remove_job',
                        details={'job_name': 'fishbowl_sales', 'error': str(e)}
                    )
        else:
            job_removed = True
    else:
        if scheduler.get_job('fishbowl_sync') is not None:
            try:
                scheduler.remove_job('fishbowl_sync', 'default')
                job_removed = True
            except:
                try:
                    SYNC_JOB.remove()
                    job_removed = True
                except Exception as e:
                    print(f"\n WARNING UNABLE TO REMOVE THE PREVIOUS SYNC JOB SCHEDULE \n ")
                    log.log_error(
                        error_type='scheduler_error',
                        message=f"Failed to remove sync job: {str(e)}",
                        source='retail.py:remove_job',
                        details={'job_name': 'fishbowl_sync', 'error': str(e)}
                    )
        else:
            job_removed = True

    return job_removed


def get_sync_interval():
    config = data.get_config()
    return config.get('sync_interval_minutes', 7)


def get_sales_interval():
    config = data.get_config()
    return config.get('sales_interval_minutes', 7)


def reschedule_sync():
    global SYNC_JOB
    job_removed = remove_job("fishbowl_sync")
    if not SYNC_JOB or job_removed is True:
        interval = get_sync_interval()
        job = scheduler.add_job(
            func=sync_manager.determine_sync,
            trigger='interval',
            minutes=interval,
            id='fishbowl_sync',
            name='Sync Fishbowl inventory',
            replace_existing=True
        )
        logger.info(f"Sync job scheduled with {interval} minute interval")
        scheduler.print_jobs()
        print('\n')
        return job
    else:
        print(" \n WARNING UNABLE TO REMOVE THE PREVIOUS SYNC JOB SCHEDULE \n ")
        return SYNC_JOB


def reschedule_sales():
    global SALES_JOB
    job_removed = remove_job("fishbowl_sales")
    if not SALES_JOB or job_removed is True:
        interval = get_sales_interval()
        job = scheduler.add_job(
            func=sync_manager.run_sales_check,
            trigger='interval',
            minutes=interval,
            id='fishbowl_sales',
            name='Sync Fishbowl Sales',
            replace_existing=True
        )
        logger.info(f"Sales check job scheduled with {interval} minute interval")
        return job
    else:
        print(" \n WARNING UNABLE TO REMOVE THE PREVIOUS SALES JOB SCHEDULE \n ")
        return SALES_JOB


# Initial schedule on module load
_config = data.get_config()
_mode = _config["inventory_method"]
if _mode == 'manual':
    SALES_JOB = reschedule_sales()
SYNC_JOB = reschedule_sync()

# Start scheduler only in the correct process:
#   WERKZEUG_RUN_MAIN='true' → Werkzeug worker child (dev mode)
#   PRODUCTION='1'           → waitress production run (set in serve.py)
# The Werkzeug reloader parent process has neither set, so it won't start.
# Cannot use record_once/app.debug here — app.debug isn't set yet when
# register_blueprint() fires at app.py module level.
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('PRODUCTION') == '1':
    scheduler.start()

# ---------------------------------- Routes ------------------------------------------ #

@retail_bp.route('/')
@access_required('retail')
def index():
    skus = data.get_all_skus()
    config = data.get_config()
    total_skus = len(skus)
    sold_out = sum(1 for s in skus.values() if s['available_qty'] <= 0)
    low_stock = sum(1 for s in skus.values() if 0 < s['available_qty'] <= 10)
    return render_template('retail/index.html',
                           skus=skus,
                           config=config,
                           stats={'total': total_skus, 'sold_out': sold_out, 'low_stock': low_stock})


@retail_bp.route('/how-to')
@access_required('retail')
def how_to():
    return render_template('retail/how_to.html')


# -------------------------------- Config R/W ---------------------------------------- #

@retail_bp.route('/api/config', methods=['GET'])
@login_required
def api_get_config():
    config = data.get_config()
    return jsonify(config)


@retail_bp.route('/api/config', methods=['PUT'])
@login_required
def api_update_config():
    try:
        req_data = request.get_json()
        updates = {}
        requires_restart = False

        if 'inventory_method' in req_data:
            method = req_data['inventory_method']
            if method not in ['manual', 'automated']:
                return jsonify({'error': 'Invalid inventory method'}), 400
            updates['inventory_method'] = method
            logger.info(f"Inventory method changed to: {method} by {session.get('username')}")

        if 'sync_interval_minutes' in req_data:
            interval = int(req_data['sync_interval_minutes'])
            if interval < 1 or interval > 180:
                return jsonify({'error': 'Interval must be between 1 and 180 minutes'}), 400
            updates['sync_interval_minutes'] = interval
            requires_restart = True
            logger.info(f"Sync interval changed to: {interval} minutes by {session.get('username')}")

        if 'sales_interval_minutes' in req_data:
            interval = int(req_data['sales_interval_minutes'])
            if interval < 1 or interval > 180:
                return jsonify({'error': 'Interval must be between 1 and 180 minutes'}), 400
            updates['sales_interval_minutes'] = interval
            requires_restart = True
            logger.info(f"Sales interval changed to: {interval} minutes by {session.get('username')}")

        data.update_config(updates)
        return jsonify({'success': True, 'requires_restart': requires_restart})

    except Exception as e:
        logger.error(f"Error updating config: {e}")
        log.log_error(
            error_type='api_error',
            message=f"Failed to update config: {str(e)}",
            source='retail.py:api_update_config',
            details={'error': str(e)},
            user=session.get('username', 'unknown')
        )
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/reschedule-sales', methods=['POST'])
@login_required
def api_reschedule_sales():
    try:
        reschedule_sales()
        interval = get_sales_interval()
        return jsonify({'success': True, 'message': f'Sales check rescheduled to run every {interval} minutes'})
    except Exception as e:
        logger.error(f"Error rescheduling sales check: {e}")
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/reschedule-sync', methods=['POST'])
@login_required
def api_reschedule_sync():
    try:
        reschedule_sync()
        interval = get_sync_interval()
        return jsonify({'success': True, 'message': f'Sync rescheduled to run every {interval} minutes'})
    except Exception as e:
        logger.error(f"Error rescheduling sync: {e}")
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/remove-job', methods=['POST'])
@login_required
def api_remove_job():
    try:
        remove_job('fishbowl_sales')
        return jsonify({'success': True, 'message': 'Job removed from scheduler'})
    except Exception as e:
        logger.error(f"Error removing job: {e}")
        return jsonify({'error': str(e)}), 500


# ---------------------------------- SKU Routes -------------------------------------- #

@retail_bp.route('/api/skus', methods=['GET'])
@login_required
def api_get_skus():
    skus = data.get_all_skus()
    return jsonify(skus)


@retail_bp.route('/api/skus', methods=['POST'])
@login_required
def api_add_sku():
    try:
        req_data = request.get_json()
        sku = req_data.get('sku', '').strip().upper()
        product_name = req_data.get('product_name', '').strip()
        available_qty = int(req_data.get('available_qty', 0))
        notes = req_data.get('notes', '').strip()
        sn_flag = req_data.get('sn_flag', False)
        part_num = req_data.get('part_num', '').strip().upper()
        user = session.get('username', 'unknown')

        if not sku or not product_name:
            return jsonify({'error': 'SKU and product name required'}), 400
        if data.get_sku(sku):
            return jsonify({'error': 'SKU already exists'}), 400

        sku_data = data.add_sku(
            sku=sku, product_name=product_name, available_qty=available_qty,
            modified_by=user, notes=notes,
            sn_flag=sn_flag, part_num=part_num
        )

        # json logging file
        log.log(action='add', sku=sku, data=sku_data, user=user)

        return jsonify({'success': True, 'data': sku_data})

    except Exception as e:
        logger.error(f"Error adding SKU: {e}")
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/sku-check', methods=['POST'])
@login_required
def api_sku_check():
    try:
        req_data = request.get_json()
        sku = req_data.get('sku', '').strip().upper()
        if not sku:
            return jsonify({'error': 'SKU required'}), 400
        result = sync_manager.get_sku_info(sku)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error validating SKU: {e}")
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/skus/<sku>', methods=['PUT'])
@login_required
def api_update_sku(sku):
    try:
        req_data = request.get_json()
        user = session.get('username', 'unknown')
        updates = {}

        if 'product_name' in req_data:
            updates['product_name'] = req_data['product_name'].strip()
        if 'available_qty' in req_data:
            updates['available_qty'] = int(req_data['available_qty'])
        if 'notes' in req_data:
            updates['notes'] = req_data['notes'].strip()

        sku_data = data.update_sku(sku=sku, updates=updates, modified_by=user)
        if not sku_data:
            return jsonify({'error': 'SKU not found'}), 404
        
        # json log file
        log.log(action='update', sku=sku, data=sku_data, user=user)

        return jsonify({'success': True, 'data': sku_data})

    except Exception as e:
        logger.error(f"Error updating SKU {sku}: {e}")
        return jsonify({'error': str(e)}), 500

@retail_bp.route('/api/skus/<sku>', methods=['DELETE'])
@login_required
def api_delete_sku(sku):
    try:
        sku_data = data.get_sku(sku)
        success = data.delete_sku(sku)
        if not success:
            return jsonify({'error': 'SKU not found'}), 404
        
        # json log file
        log.log(action='delete', sku=sku, data=sku_data, user=session.get('username', 'unknown'))
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error deleting SKU {sku}: {e}")
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/sync', methods=['POST'])
@login_required
def api_sync():
    try:
        result = sync_manager.determine_sync()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error triggering sync: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@retail_bp.route('/api/check', methods=['POST'])
@login_required
def api_check():
    try:
        result = sync_manager.run_sales_check()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error triggering sales check: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@retail_bp.route('/api/status', methods=['GET'])
@login_required
def api_status():
    config = data.get_config()
    return jsonify({
        'last_sync_run': config.get('last_sync_run'),
        'sync_interval_minutes': config.get('sync_interval_minutes'),
        'scheduler_running': scheduler.running
    })


# -------------------------------- Error Log Routes ---------------------------------- #

@retail_bp.route('/api/errors', methods=['GET'])
@login_required
def api_get_errors():
    try:
        limit = request.args.get('limit', 50, type=int)
        unresolved_only = request.args.get('unresolved_only', 'false').lower() == 'true'
        errors = log.get_errors(limit=limit, unresolved_only=unresolved_only)
        return jsonify({'success': True, 'errors': errors})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/errors/stats', methods=['GET'])
@login_required
def api_get_error_stats():
    try:
        stats = log.get_error_stats()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/errors/<int:error_id>', methods=['GET'])
@login_required
def api_get_error(error_id):
    try:
        error = log.get_error_by_id(error_id)
        if error:
            return jsonify({'success': True, 'error': error})
        return jsonify({'error': 'Error not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/errors/<int:error_id>/resolve', methods=['POST'])
@login_required
def api_resolve_error(error_id):
    try:
        success = log.mark_resolved(error_id, resolved_by=session.get('username', 'system'))
        if success:
            return jsonify({'success': True, 'message': f'Error {error_id} marked as resolved'})
        return jsonify({'error': 'Error not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/errors/clear', methods=['POST'])
@login_required
def api_clear_errors():
    try:
        count = log.clear_all_errors()
        logger.info(f"All error logs cleared by {session.get('username')}")
        return jsonify({'success': True, 'message': f'Cleared {count} errors', 'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/errors', methods=['POST'])
@login_required
def api_log_error():
    try:
        req_data = request.get_json()
        error_type = req_data.get('error_type', 'manual_error')
        message = req_data.get('message')
        source = req_data.get('source', 'webapp')
        details = req_data.get('details', {})
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        error_entry = log.log_error(
            error_type=error_type, message=message, source=source,
            details=details, user=session.get('username', 'system')
        )
        return jsonify({'success': True, 'error': error_entry})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# -------------------------------- Audit Log Routes ---------------------------------- #

@retail_bp.route('/api/logs', methods=['GET'])
@login_required
def api_get_logs():
    try:
        limit = request.args.get('limit', 50, type=int)
        logs = log.get_logs(limit=limit)
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/logs/stats', methods=['GET'])
@login_required
def api_get_log_stats():
    try:
        stats = log.get_log_stats()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/logs/<int:log_id>', methods=['GET'])
@login_required
def api_get_log(log_id):
    try:
        log_info = log.get_log_by_id(log_id)
        if log_info:
            return jsonify({'success': True, 'error': log_info})
        return jsonify({'error': 'Audit Log entry not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@retail_bp.route('/api/logs/clear', methods=['POST'])
@login_required
def api_clear_logs():
    try:
        count = log.clear_all_logs()
        logger.info(f"All audit logs cleared by {session.get('username')}")
        return jsonify({'success': True, 'message': f'Cleared {count} audit log entries', 'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
