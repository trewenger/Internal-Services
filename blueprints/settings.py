from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from common.Clients.Email.EmailApi import send_email
from config import Config

from blueprints.auth import access_required, generate_invite_token
from user_store import UserStore

import requests, json

settings_bp = Blueprint('settings', __name__)

SECTIONS = ['retail', 'services', 'intuiflow', 'settings', 'promo']
SENDER_EMAIL = Config.SENDER_EMAIL

@settings_bp.route('/')
@access_required('settings', 'write')
def index():
    users = UserStore.load()
    return render_template('settings/index.html', users=users, sections=SECTIONS)


@settings_bp.route('/invite', methods=['POST'])
@access_required('settings', 'write')
def invite():
    username = request.form.get('username', '').strip().lower()
    email = request.form.get('email', '').strip()

    if not username or not email:
        flash('Username and email are required.', 'error')
        return redirect(url_for('settings.index'))

    if UserStore.get_user(username):
        flash(f'A user named "{username}" already exists.', 'error')
        return redirect(url_for('settings.index'))

    
    token = generate_invite_token(username)
    base = Config.APP_BASE_URL or request.host_url.rstrip('/')
    accept_url = base + url_for('auth.accept_invite', token=token)

    html_body = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
        <h2 style="color: #1e40af;">You've been invited to Internal Services</h2>
        <p>An account has been created for you. Click the link below to set your
           password and activate your account. <br>
           <b>NOTE: </b>you must be connected to the main Radian network or the VPN. </p>
        <p style="margin: 24px 0;">
            <a href="{accept_url}"
               style="background:#3b82f6;color:white;padding:12px 24px;border-radius:6px;
                      text-decoration:none;font-weight:bold;">
                Set your password →
            </a>
        </p>
        <p style="color:#6b7280;font-size:13px;">
            This link expires in 48 hours. If you weren't expecting this email, you can ignore it.
        </p>
    </div>
    """

    try:
        # returns a dict: {status, data}
        email_result = send_email(
            subject='You\'ve been invited to the Internal Services web app',
            html_body=html_body,
            recipients=[email],
            sender=SENDER_EMAIL
        )
        
        if not email_result['status'] or email_result['status'] >= 204:
            raise Exception(email_result['data'])

        UserStore.create_invite(username, email)    # create user entry only after successful email send.
        flash(f'Invite sent to {email}.', 'success')
    except Exception as e:
        flash(f'Invite email failed to send, account not created: {e}', 'error')

    return redirect(url_for('settings.index'))


@settings_bp.route('/invite/resend/<username>', methods=['POST'])
@access_required('settings', 'write')
def resend_invite(username):
    user = UserStore.get_user(username)
    if not user or user.get('status') != 'invited':
        return jsonify({'error': 'User not found or already active'}), 400

    token = generate_invite_token(username)
    base = Config.APP_BASE_URL or request.host_url.rstrip('/')
    accept_url = base + url_for('auth.accept_invite', token=token)
    email = user.get('email', '')

    html_body = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
        <h2 style="color: #1e40af;">Your invite to Internal Services (resent)</h2>
        <p>Use the link below to set your password and activate your account.</p>
        <p style="margin: 24px 0;">
            <a href="{accept_url}"
               style="background:#3b82f6;color:white;padding:12px 24px;border-radius:6px;
                      text-decoration:none;font-weight:bold;">
                Set your password →
            </a>
        </p>
        <p style="color:#6b7280;font-size:13px;">This link expires in 48 hours.</p>
    </div>
    """

    try:
        # returns a dict: {status, data}
        email_result = send_email(
            subject='Your invite to Internal Services (resent)',
            html_body=html_body,
            recipients=[email],
            sender=SENDER_EMAIL
        )

        if not email_result['status'] or email_result['status'] >= 204:
            raise Exception(email_result['data'])

        return jsonify({'success': True, 'message': f'Invite resent to {email}'})
    except Exception as e:
        return jsonify({'error sending email: ': str(e)}), 500


@settings_bp.route('/users/<username>/access', methods=['PUT'])
@access_required('settings', 'write')
def update_access(username):
    user = UserStore.get_user(username)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json()
    if not data or 'access' not in data:
        return jsonify({'error': 'access dict required'}), 400

    new_access = {s: data['access'].get(s, 'none') for s in SECTIONS}
    valid_levels = {'none', 'read', 'write'}
    if not all(v in valid_levels for v in new_access.values()):
        return jsonify({'error': 'Invalid access level'}), 400

    UserStore.update_access(username, new_access)
    return jsonify({'success': True, 'access': new_access})

@settings_bp.route('/users/<username>/deactivate', methods=['POST'])
@access_required('settings', 'write')
def deactivate_user(username):
    user = UserStore.get_user(username)
    if not user or user.get('status') == 'inactive':
        return jsonify({'error': 'User not found or is already inactive'}), 400

    try:
        result = UserStore.deactivate_user(username)
        if not result:
            raise Exception('Failed to deactivate the user. ')
        
        return jsonify({'success': True, 'message': f'{username} successfully deactivated.'})
    except Exception as e:
        return jsonify({'error: ': str(e)}), 500
    
@settings_bp.route('/users/<username>/reactivate', methods=['POST'])
@access_required('settings', 'write')
def reactivate_user(username):
    user = UserStore.get_user(username)
    if not user or user.get('status') != 'inactive':
        return jsonify({'error': 'User not found or is already active'}), 400

    try:
        result = UserStore.reactivate_user(username)
        if not result:
            raise Exception('Failed to reactivate the user. ')
        
        return jsonify({'success': True, 'message': f'{username} successfully reactivated.'})
    except Exception as e:
        return jsonify({'error: ': str(e)}), 500
    