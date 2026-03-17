from flask import Blueprint, render_template
from blueprints.auth import login_required, access_required

intuiflow_bp = Blueprint('intuiflow', __name__)


@intuiflow_bp.route('/')
@access_required('intuiflow')
def index():
    return render_template('intuiflow/index.html')
