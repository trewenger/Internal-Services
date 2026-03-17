from functools import wraps
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, abort
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from config import Config
from user_store import UserStore
from common.Clients.Email.EmailApi import send_email

auth_bp = Blueprint('auth', __name__)

# --------------------------------- Access levels ----------------------------------- #

LEVELS = {'none': 0, 'read': 1, 'write': 2}


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def access_required(section: str, min_level: str = 'read'):
    """Decorator that enforces login + minimum access level for a section.

    Sections: 'retail', 'services', 'intuiflow', 'settings'
    Levels:   'read', 'write'  (default min_level is 'read')

    If the user has 'none' access: redirects to / with a flash message.
    If the user has 'read' but 'write' is required: aborts with 403.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get('logged_in'):
                return redirect(url_for('auth.login'))
            user_level = session.get('access', {}).get(section, 'none')
            if LEVELS.get(user_level, 0) < LEVELS.get(min_level, 1):
                if user_level == 'none':
                    flash(f"You don't have access to that section.", 'error')
                    return redirect(url_for('retail.index') if session.get('access', {}).get('retail', 'none') != 'none' else url_for('auth.login'))
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


# --------------------------------- Invite tokens ----------------------------------- #

def generate_invite_token(username: str) -> str:
    s = URLSafeTimedSerializer(Config.SECRET_KEY)
    return s.dumps(username, salt='account-invite')


def verify_invite_token(token: str) -> str:
    """Returns username encoded in token. Raises SignatureExpired or BadSignature if invalid."""
    s = URLSafeTimedSerializer(Config.SECRET_KEY)
    return s.loads(token, salt='account-invite', max_age=172800)  # 48 hours


def generate_reset_token(username: str) -> str:
    s = URLSafeTimedSerializer(Config.SECRET_KEY)
    return s.dumps(username, salt='password-reset')


def verify_reset_token(token: str) -> str:
    """Returns username encoded in token. Raises SignatureExpired or BadSignature if invalid."""
    s = URLSafeTimedSerializer(Config.SECRET_KEY)
    return s.loads(token, salt='password-reset', max_age=3600)  # 1 hour


# -------------------------------------- Routes ------------------------------------- #

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('retail.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = UserStore.authenticate(username, password)

        if user:
            user_access = dict(UserStore.get_user(username))['access']
            # need to find a page where user has access.
            landing_page = None
            for k, v in user_access.items():
                if v != 'none':
                    landing_page = k
                    break

            if not landing_page:
                return render_template('auth/login.html', error='You do not have access to any modules. Request access to login.')
            session['logged_in'] = True
            session['username'] = username
            session['access'] = user.get('access', {})
            return redirect(url_for(f'{landing_page}.index'))
        
        return render_template('auth/login.html', error='Invalid username or password.')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@auth_bp.route('/accept-invite/<token>', methods=['GET', 'POST'])
def accept_invite(token):
    try:
        username = verify_invite_token(token)
    except SignatureExpired:
        return render_template('auth/accept_invite.html', error='This invite link has expired. Please ask for a new one.', token=None)
    except BadSignature:
        return render_template('auth/accept_invite.html', error='This invite link is invalid.', token=None)

    user = UserStore.get_user(username)
    if user is None:
        return render_template('auth/accept_invite.html', error='Invite not found.', token=None)
    if user.get('status') == 'active':
        return render_template('auth/accept_invite.html', error='This invite has already been used. Please log in.', token=None)

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(password) < 8:
            return render_template('auth/accept_invite.html', token=token, username=username,
                                   error='Password must be at least 8 characters.')
        if password != confirm:
            return render_template('auth/accept_invite.html', token=token, username=username,
                                   error='Passwords do not match.')
        UserStore.activate_user(username, password)
        flash('Account activated! You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/accept_invite.html', token=token, username=username)


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if session.get('logged_in'):
        return redirect(url_for('retail.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        username, user = UserStore.get_user_by_email(email)

        if username and user and user.get('status') == 'active':
            token = generate_reset_token(username)
            base = Config.APP_BASE_URL or request.host_url.rstrip('/')
            reset_url = base + url_for('auth.reset_password', token=token)
            html_body = f"""
            <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
                <h2 style="color: #1e40af;">Password reset request</h2>
                <p>We received a request to reset the password for your Internal Services account.
                   Click the link below to set a new password.</p>
                <p style="margin: 24px 0;">
                    <a href="{reset_url}"
                       style="background:#3b82f6;color:white;padding:12px 24px;border-radius:6px;
                              text-decoration:none;font-weight:bold;">
                        Reset your password →
                    </a>
                </p>
                <p style="color:#6b7280;font-size:13px;">
                    This link expires in 1 hour. If you didn't request a reset, you can ignore
                    this email — your password has not been changed.
                </p>
            </div>
            """
            try:
                send_email(
                    subject='Internal Services — Password Reset',
                    html_body=html_body,
                    recipients=[email],
                )
            except Exception:
                pass  # Fail silently — same response shown regardless

        flash("If that email is registered, you'll receive a reset link shortly.", 'info')
        return redirect(url_for('auth.forgot_password'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        username = verify_reset_token(token)
    except SignatureExpired:
        return render_template('auth/reset_password.html',
                               error='This reset link has expired. Please request a new one.',
                               token=None)
    except BadSignature:
        return render_template('auth/reset_password.html',
                               error='This reset link is invalid.', token=None)

    user = UserStore.get_user(username)
    if user is None or user.get('status') != 'active':
        return render_template('auth/reset_password.html',
                               error='Invalid or expired reset link.', token=None)

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')
        if len(password) < 8:
            return render_template('auth/reset_password.html', token=token, username=username,
                                   error='Password must be at least 8 characters.')
        if password != confirm:
            return render_template('auth/reset_password.html', token=token, username=username,
                                   error='Passwords do not match.')
        UserStore.activate_user(username, password)
        flash('Password updated. You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token, username=username)
