from flask import Blueprint, render_template, request, jsonify, session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from datetime import datetime
import threading
import os
import pytz

from blueprints.auth import login_required, access_required
from API_Service_Network.RetailPromoManager.data import PromoData, PromoLogger
from API_Service_Network.RetailPromoManager.promo import upsert_discount

promo_bp = Blueprint('promo', __name__)

PST = pytz.timezone('America/Los_Angeles')
promo_scheduler = BackgroundScheduler(timezone=PST)
promo_data = PromoData()
promo_logger = PromoLogger()


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _now_pst():
    return datetime.now(PST)


def _parse_pst(dt_str):
    """Parse a naive ISO 8601 string as a PST-aware datetime."""
    return PST.localize(datetime.fromisoformat(dt_str))


def _job_id(name):
    return f'job_promo_{name.replace(" ", "_")}'


# ─── Core Logic ─────────────────────────────────────────────────────────────────

def route_promo(name, triggered_by='scheduler'):
    """Activate or deactivate a promo in Fishbowl based on its current status."""
    cfg = promo_data.get(name)
    if cfg is None:
        promo_logger.append(name, 'route', triggered_by, 'error', 'Promo not found in config.')
        return

    status = cfg['status']
    now = _now_pst()
    end = _parse_pst(cfg['end_dt'])

    if status == 'pending':
        if now >= end:
            ok = upsert_discount(cfg['name'], cfg['description'], cfg['discount_type'], cfg['discount_amount'], False)
            if ok:
                promo_data.set_status(name, 'inactive')
                promo_logger.append(name, 'deactivate', triggered_by, 'success',
                                    'Window expired before activation. Marked inactive in Fishbowl.')
            else:
                promo_logger.append(name, 'deactivate', triggered_by, 'error',
                                    'Fishbowl call failed. Status unchanged.')
        else:
            ok = upsert_discount(cfg['name'], cfg['description'], cfg['discount_type'], cfg['discount_amount'], True)
            if ok:
                promo_data.set_status(name, 'active')
                promo_logger.append(name, 'activate', triggered_by, 'success', 'Activated in Fishbowl.')
            else:
                promo_logger.append(name, 'activate', triggered_by, 'error',
                                    'Fishbowl call failed. Status unchanged.')

    elif status == 'active':
        ok = upsert_discount(cfg['name'], cfg['description'], cfg['discount_type'], cfg['discount_amount'], False)
        if ok:
            promo_data.set_status(name, 'inactive')
            promo_logger.append(name, 'deactivate', triggered_by, 'success', 'Deactivated in Fishbowl.')
        else:
            promo_logger.append(name, 'deactivate', triggered_by, 'error',
                                'Fishbowl call failed. Status unchanged.')

    elif status == 'inactive':
        ok = upsert_discount(cfg['name'], cfg['description'], cfg['discount_type'], cfg['discount_amount'], False)
        if ok:
            promo_logger.append(name, 'deactivate', triggered_by, 'success',
                                'Deactivate confirmed (already inactive).')
        else:
            promo_logger.append(name, 'deactivate', triggered_by, 'error',
                                'Fishbowl deactivate call failed.')

    schedule_promo(name)


def schedule_promo(name):
    """Add or replace the APScheduler DateTrigger job for a promo."""
    job_id = _job_id(name)
    if promo_scheduler.get_job(job_id):
        promo_scheduler.remove_job(job_id)

    cfg = promo_data.get(name)
    if cfg is None:
        return

    status = cfg['status']
    if status == 'pending':
        run_date = _parse_pst(cfg['start_dt'])
        promo_scheduler.add_job(
            func=route_promo,
            trigger=DateTrigger(run_date=run_date),
            args=[name],
            id=job_id,
            name=f'Promo: {name}',
            replace_existing=True,
        )
    elif status == 'active':
        run_date = _parse_pst(cfg['end_dt'])
        promo_scheduler.add_job(
            func=route_promo,
            trigger=DateTrigger(run_date=run_date),
            args=[name],
            id=job_id,
            name=f'Promo: {name}',
            replace_existing=True,
        )
    # inactive: no job needed


def _startup_recovery():
    """On server start, scan all promos and handle any missed scheduled fires."""
    now = _now_pst()
    for name, cfg in promo_data.get_all().items():
        status = cfg['status']
        try:
            start = _parse_pst(cfg['start_dt'])
            end = _parse_pst(cfg['end_dt'])
        except (ValueError, KeyError):
            continue

        if status == 'pending':
            if start <= now < end:
                threading.Thread(target=route_promo, args=[name, 'startup'], daemon=True).start()
            elif now >= end:
                promo_data.set_status(name, 'inactive')
                threading.Thread(target=route_promo, args=[name, 'startup'], daemon=True).start()
            else:
                schedule_promo(name)
        elif status == 'active':
            if now >= end:
                threading.Thread(target=route_promo, args=[name, 'startup'], daemon=True).start()
            else:
                schedule_promo(name)
        # inactive: nothing to do


# ─── Scheduler Startup ───────────────────────────────────────────────────────────

if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('PRODUCTION') == '1':
    _startup_recovery()
    promo_scheduler.start()


# ─── Page Routes ─────────────────────────────────────────────────────────────────

@promo_bp.route('/')
@access_required('promo')
def index():
    can_write = session.get('access', {}).get('promo') == 'write'
    return render_template('promo/index.html', can_write=can_write)


# ─── API Routes ──────────────────────────────────────────────────────────────────

@promo_bp.route('/api/status')
@login_required
def api_status():
    promos = promo_data.get_all()
    promo_list = []
    stats = {'total': 0, 'pending': 0, 'active': 0, 'inactive': 0}

    for name, cfg in promos.items():
        stats['total'] += 1
        stats[cfg['status']] += 1

        job = promo_scheduler.get_job(_job_id(name))
        next_run = None
        if job and job.next_run_time:
            next_run = job.next_run_time.astimezone(PST).strftime('%m/%d/%Y %I:%M %p PST')

        promo_list.append({**cfg, 'next_run': next_run})

    return jsonify({'success': True, 'promos': promo_list, 'stats': stats})


@promo_bp.route('/api/promo', methods=['POST'])
@login_required
def api_add_promo():
    try:
        req = request.get_json()
        name = req.get('name', '').strip()
        description = req.get('description', '').strip()
        use_type = req.get('use_type', 'unlimited')
        start_dt = req.get('start_dt', '').strip()
        end_dt = req.get('end_dt', '').strip()
        discount_type = req.get('discount_type', '').strip()
        discount_amount = float(req.get('discount_amount', 0))
        user = session.get('username', 'unknown')

        if not name:
            return jsonify({'error': 'Name is required.'}), 400
        if promo_data.get(name) is not None:
            return jsonify({'error': f'Promo code "{name}" already exists.'}), 400
        if not start_dt or not end_dt:
            return jsonify({'error': 'Start and end datetimes are required.'}), 400
        if discount_type not in ('percentage', 'flat'):
            return jsonify({'error': 'Discount type must be "percentage" or "flat".'}), 400
        if use_type not in ('single', 'unlimited'):
            return jsonify({'error': 'Use type must be "single" or "unlimited".'}), 400

        try:
            start = _parse_pst(start_dt)
            end = _parse_pst(end_dt)
        except ValueError:
            return jsonify({'error': 'Invalid datetime format.'}), 400

        now = _now_pst()
        if end <= start:
            return jsonify({'error': 'End datetime must be after start datetime.'}), 400
        if end <= now:
            return jsonify({'error': 'End datetime must be in the future.'}), 400
        if discount_amount <= 0:
            return jsonify({'error': 'Discount amount must be greater than 0.'}), 400
        if discount_type == 'percentage' and discount_amount > 100:
            return jsonify({'error': 'Percentage discount cannot exceed 100.'}), 400

        # Fishbowl first — reject entirely if it fails
        ok = upsert_discount(name, description, discount_type, discount_amount, False)
        if not ok:
            promo_logger.append(name, 'add', user, 'error',
                                'Fishbowl registration failed. Promo not saved.')
            return jsonify({'error': 'Failed to register promo in Fishbowl. Promo not saved.'}), 500

        config = {
            'name': name,
            'description': description,
            'use_type': use_type,
            'start_dt': start_dt,
            'end_dt': end_dt,
            'discount_type': discount_type,
            'discount_amount': discount_amount,
            'status': 'pending',
            'last_modified': _now_pst().strftime('%Y-%m-%dT%H:%M:%S'),
        }
        promo_data.add(name, config)
        promo_logger.append(name, 'add', user, 'success',
                            'Promo created and registered in Fishbowl.')

        if start <= now < end:
            threading.Thread(target=route_promo, args=[name, user], daemon=True).start()
        else:
            schedule_promo(name)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@promo_bp.route('/api/promo/<name>', methods=['PUT'])
@login_required
def api_edit_promo(name):
    try:
        cfg = promo_data.get(name)
        if cfg is None:
            return jsonify({'error': 'Promo not found.'}), 404

        req = request.get_json()
        description = req.get('description', cfg['description']).strip()
        use_type = req.get('use_type', cfg['use_type'])
        start_dt = req.get('start_dt', cfg['start_dt']).strip()
        end_dt = req.get('end_dt', cfg['end_dt']).strip()
        discount_type = req.get('discount_type', cfg['discount_type'])
        discount_amount = float(req.get('discount_amount', cfg['discount_amount']))
        user = session.get('username', 'unknown')

        if discount_type not in ('percentage', 'flat'):
            return jsonify({'error': 'Discount type must be "percentage" or "flat".'}), 400
        if use_type not in ('single', 'unlimited'):
            return jsonify({'error': 'Use type must be "single" or "unlimited".'}), 400

        try:
            start = _parse_pst(start_dt)
            end = _parse_pst(end_dt)
        except ValueError:
            return jsonify({'error': 'Invalid datetime format.'}), 400

        now = _now_pst()
        if end <= start:
            return jsonify({'error': 'End datetime must be after start datetime.'}), 400
        if end <= now:
            return jsonify({'error': 'End datetime must be in the future.'}), 400
        if discount_amount <= 0:
            return jsonify({'error': 'Discount amount must be greater than 0.'}), 400
        if discount_type == 'percentage' and discount_amount > 100:
            return jsonify({'error': 'Percentage discount cannot exceed 100.'}), 400

        pre_status = cfg['status']

        promo_data.update(name, {
            'description': description,
            'use_type': use_type,
            'start_dt': start_dt,
            'end_dt': end_dt,
            'discount_type': discount_type,
            'discount_amount': discount_amount,
        })

        job_id = _job_id(name)
        if promo_scheduler.get_job(job_id):
            promo_scheduler.remove_job(job_id)

        if pre_status == 'active':
            if end > now:
                # Case A: still active, sync any changed fields to Fishbowl immediately
                ok = upsert_discount(name, description, discount_type, discount_amount, True)
                if ok:
                    promo_logger.append(name, 'edit', user, 'success',
                                        'Updated while active. Fishbowl synced. Rescheduled at new end datetime.')
                else:
                    promo_logger.append(name, 'edit', user, 'error',
                                        'Config updated but Fishbowl sync failed. Will retry at deactivation.')
                schedule_promo(name)
            else:
                # Case B: active but new end is in the past — deactivate immediately
                promo_logger.append(name, 'edit', user, 'success',
                                    'Updated while active; end datetime moved to past. Deactivating.')
                threading.Thread(target=route_promo, args=[name, user], daemon=True).start()
        else:
            # Case C: pending or inactive — reset to pending and re-evaluate
            promo_data.set_status(name, 'pending')
            if start <= now < end:
                promo_logger.append(name, 'edit', user, 'success',
                                    'Updated. Start has passed; activating immediately.')
                threading.Thread(target=route_promo, args=[name, user], daemon=True).start()
            elif now >= end:
                promo_logger.append(name, 'edit', user, 'success',
                                    'Updated. Window has passed; marking inactive.')
                threading.Thread(target=route_promo, args=[name, user], daemon=True).start()
            else:
                promo_logger.append(name, 'edit', user, 'success',
                                    'Updated. Rescheduled at new start datetime.')
                schedule_promo(name)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@promo_bp.route('/api/promo/<name>/inactivate', methods=['POST'])
@login_required
def api_inactivate_promo(name):
    try:
        cfg = promo_data.get(name)
        if cfg is None:
            return jsonify({'error': 'Promo not found.'}), 404
        if cfg['status'] == 'inactive':
            return jsonify({'error': 'Promo is already inactive.'}), 400

        user = session.get('username', 'unknown')
        promo_data.set_status(name, 'inactive')
        promo_logger.append(name, 'inactivate', user, 'success',
                            'Manually inactivated. Deactivating in Fishbowl.')
        threading.Thread(target=route_promo, args=[name, user], daemon=True).start()

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@promo_bp.route('/api/logs')
@login_required
def api_get_logs():
    limit = request.args.get('limit', 50, type=int)
    logs = promo_logger.get_logs(limit=limit)
    errors = promo_logger.get_errors(limit=limit)
    return jsonify({'success': True, 'logs': logs, 'errors': errors})


@promo_bp.route('/api/logs/clear', methods=['POST'])
@login_required
def api_clear_logs():
    count = promo_logger.clear_logs()
    return jsonify({'success': True, 'count': count})


@promo_bp.route('/api/errors/clear', methods=['POST'])
@login_required
def api_clear_errors():
    count = promo_logger.clear_errors()
    return jsonify({'success': True, 'count': count})
