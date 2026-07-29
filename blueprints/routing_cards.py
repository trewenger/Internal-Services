import re
from urllib.parse import urlencode, urlparse

from flask import Blueprint, jsonify, redirect, render_template, render_template_string, request, session

from API_Service_Network.DigitalRoutingCardManager.data import CardData
from blueprints.auth import access_required, login_required
from config import Config

routing_cards_bp = Blueprint('routing_cards', __name__)

card_data = CardData()


# ============================================================================
# Resolve route — no auth (operator-facing, intranet only)
# ============================================================================

@routing_cards_bp.route('/c/<card_id>')
def resolve(card_id):
    card = card_data.lookup_card(card_id)
    if card is None:
        return render_template('routing_cards/card_status.html',
                               status='unknown', card_id=card_id), 404

    assignment = card_data.get_active_assignment(card_id)
    if assignment is None:
        return render_template('routing_cards/card_status.html',
                               status='unassigned', card_id=card_id)

    if not assignment.get('work_order_url'):
        return render_template('routing_cards/card_status.html',
                               status='unassigned', card_id=card_id)

    if not Config.INTUIFLOW_WORKORDER_BASE_URL:
        return render_template('routing_cards/card_status.html',
                               status='config_error', card_id=card_id), 500

    # Reconstruct from stored fields rather than parsing the stored URL's host,
    # so internal-proxy URLs pasted during assignment never pollute the redirect.
    params = urlencode({
        'OrderNumber': assignment.get('order_number', ''),
        'PartNumber':  assignment.get('part_number', ''),
        'Revision':    assignment.get('revision', ''),
        'Location':    Config.INTUIFLOW_LOCATION,
    })
    target = f"{Config.INTUIFLOW_WORKORDER_BASE_URL.rstrip('/')}?{params}"
    # Use a JS redirect instead of HTTP 302 — IIS ARR rewrites Location headers
    # in redirect responses, changing external hosts back to rwas01.
    return render_template_string(
        '<meta http-equiv="refresh" content="0; url={{ url }}">'
        '<script>window.location.replace({{ url | tojson }});</script>',
        url=target,
    ), 200


# ============================================================================
# Page routes — require login + routing-cards access
# ============================================================================

@routing_cards_bp.route('/')
@access_required('routing-cards')
def index():
    can_write = session.get('access', {}).get('routing-cards') == 'write'
    cards     = card_data.list_cards_with_assignments()
    card_host = Config.CARD_HOST_BASE_URL.rstrip('/')

    # Derive active orders for the close-work-order dropdown
    order_counts = {}
    for c in cards:
        if c['assignment']:
            on = c['assignment']['order_number']
            order_counts[on] = order_counts.get(on, 0) + 1
    active_orders = [{'order_number': on, 'card_count': cnt}
                     for on, cnt in sorted(order_counts.items())]

    return render_template('routing_cards/index.html',
                           cards=cards, can_write=can_write,
                           card_host=card_host, active_orders=active_orders)


@routing_cards_bp.route('/assign')
@access_required('routing-cards')
def assign():
    can_write = session.get('access', {}).get('routing-cards') == 'write'
    return render_template('routing_cards/assign.html', can_write=can_write)


# ============================================================================
# API routes — require login
# ============================================================================

@routing_cards_bp.route('/api/assign', methods=['POST'])
@login_required
def api_assign():
    body            = request.get_json(force=True, silent=True) or {}
    card_id         = (body.get('card_id') or '').strip()
    order_number    = (body.get('order_number') or '').strip()
    part_number     = (body.get('part_number') or '').strip()
    revision        = (body.get('revision') or '').strip()
    work_order_url  = (body.get('work_order_url') or '').strip()
    force           = bool(body.get('force', False))

    if not card_id or not order_number:
        return jsonify({'error': 'card_id and order_number are required'}), 400

    result = card_data.assign_card(
        card_id, order_number, part_number, revision,
        assigned_by=session.get('username', 'unknown'),
        work_order_url=work_order_url,
        force=force,
    )
    if not result['ok']:
        if result.get('conflict'):
            return jsonify({'error': result['error'], 'conflict': True,
                            'current_order': result['current_order']}), 409
        return jsonify({'error': result['error']}), 409
    return jsonify({'success': True, 'batch_number': result['batch_number'], 'id': result['id']})


@routing_cards_bp.route('/api/assign/<int:assignment_id>/last-batch', methods=['PATCH'])
@login_required
def api_last_batch(assignment_id):
    result = card_data.set_last_batch(assignment_id)
    if not result['ok']:
        return jsonify({'error': result['error']}), 404
    return jsonify({'success': True, 'new_value': result['new_value'], 'cleared_ids': result['cleared_ids']})


@routing_cards_bp.route('/api/close', methods=['POST'])
@login_required
def api_close():
    body         = request.get_json(force=True, silent=True) or {}
    order_number = (body.get('order_number') or '').strip()
    if not order_number:
        return jsonify({'error': 'order_number is required'}), 400
    result = card_data.close_work_order(order_number)
    return jsonify({'success': True, 'closed_count': result['closed_count']})


@routing_cards_bp.route('/api/cards')
@login_required
def api_cards():
    return jsonify({'success': True, 'cards': card_data.list_cards_with_assignments()})


@routing_cards_bp.route('/api/cards/register', methods=['POST'])
@login_required
def api_register_cards():
    body         = request.get_json(force=True, silent=True) or {}
    card_ids_raw = body.get('card_ids', '')
    if isinstance(card_ids_raw, list):
        card_ids = card_ids_raw
    else:
        card_ids = [c.strip() for c in re.split(r'[\n,\s]+', str(card_ids_raw)) if c.strip()]

    if not card_ids:
        return jsonify({'error': 'No card IDs provided'}), 400

    result = card_data.register_cards(card_ids)
    return jsonify({'success': True, 'added': result['added'], 'duplicates': result['duplicates']})
