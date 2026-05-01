from flask import Flask, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from user_store import UserStore

app = Flask(__name__, template_folder='templates', static_folder='static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

# Seed credentials.json with default admin account if it doesn't exist yet
UserStore.init()

# -------------------------------- Context processor -------------------------------- #

@app.context_processor
def inject_user():
    return {'user_access': session.get('access', {})}

# ------------------------------------ Routes --------------------------------------- #

@app.route('/')
def index():
    return redirect(url_for('retail.index'))

# -------------------------------- Blueprints --------------------------------------- #

from blueprints.auth import auth_bp
from blueprints.retail import retail_bp
from blueprints.services import services_bp
from blueprints.intuiflow import intuiflow_bp
from blueprints.settings import settings_bp
from blueprints.promo import promo_bp

app.register_blueprint(auth_bp)
app.register_blueprint(retail_bp, url_prefix='/retail')
app.register_blueprint(services_bp, url_prefix='/services')
app.register_blueprint(intuiflow_bp, url_prefix='/intuiflow')
app.register_blueprint(settings_bp, url_prefix='/settings')
app.register_blueprint(promo_bp, url_prefix='/retail-promo')

# ------------------------------------------------------------------------------- #

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
