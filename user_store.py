import json
import os
from werkzeug.security import generate_password_hash, check_password_hash

_CREDS_FILE = os.path.join(os.path.dirname(__file__), 'credentials.json')

_DEFAULT_ACCESS = {
    'retail':    'read',
    'services':  'read',
    'intuiflow': 'read',
    'settings':  'none',
    'promo':     'none',
}

_ADMIN_ACCESS = {
    'retail':    'write',
    'services':  'write',
    'intuiflow': 'write',
    'settings':  'write',
    'promo':     'write',
}


class UserStore:

    @staticmethod
    def load() -> dict:
        if not os.path.exists(_CREDS_FILE):
            return {}
        with open(_CREDS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def save(users: dict) -> None:
        tmp = _CREDS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=2)
        os.replace(tmp, _CREDS_FILE)

    @staticmethod
    def get_user(username: str) -> dict | None:
        return UserStore.load().get(username)

    @staticmethod
    def authenticate(username: str, password: str) -> dict | None:
        user = UserStore.get_user(username)
        if user is None:
            return None
        if user.get('status') != 'active':
            return None
        if not check_password_hash(user.get('password_hash', ''), password):
            return None
        return user

    @staticmethod
    def create_invite(username: str, email: str, access: dict | None = None) -> dict:
        users = UserStore.load()
        entry = {
            'email':  email,
            'status': 'invited',
            'access': access if access is not None else dict(_DEFAULT_ACCESS),
        }
        users[username] = entry
        UserStore.save(users)
        return entry

    @staticmethod
    def activate_user(username: str, password: str) -> bool:
        users = UserStore.load()
        if username not in users:
            return False
        users[username]['password_hash'] = generate_password_hash(password)
        users[username]['status'] = 'active'
        UserStore.save(users)
        return True
    
    @staticmethod
    def deactivate_user(username: str) -> bool:
        users = UserStore.load()
        if username not in users:
            return False
        users[username]['status'] = 'inactive'
        UserStore.save(users)
        return True
    
    @staticmethod
    def reactivate_user(username: str) -> bool:
        users = UserStore.load()
        if username not in users:
            return False
        users[username]['status'] = 'active'
        UserStore.save(users)
        return True

    @staticmethod
    def update_access(username: str, access: dict) -> bool:
        users = UserStore.load()
        if username not in users:
            return False
        users[username]['access'] = access
        UserStore.save(users)
        return True

    @staticmethod
    def get_user_by_email(email: str) -> tuple:
        """Find a user by email (case-insensitive). Returns (username, user_dict) or (None, None)."""
        target = email.strip().lower()
        for username, data in UserStore.load().items():
            if data.get('email', '').lower() == target:
                return username, data
        return None, None

    @staticmethod
    def init() -> None:
        """Seed credentials.json with a default admin account if it doesn't exist."""
        if os.path.exists(_CREDS_FILE):
            return
        users = {
            'admin': {
                'password_hash': generate_password_hash('changeme'),
                'email': '',
                'status': 'active',
                'access': dict(_ADMIN_ACCESS),
            }
        }
        UserStore.save(users)
