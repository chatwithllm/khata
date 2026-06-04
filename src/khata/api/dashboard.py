from flask import Blueprint, g, jsonify

from ..services import dashboard
from .auth import current_user

bp = Blueprint("dashboard", __name__)


@bp.get("/api/dashboard")
def get_dashboard():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(dashboard.net_position(g.db, user.id)), 200
