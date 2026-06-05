from flask import Blueprint, current_app, jsonify

from ..services import feed
from .auth import current_user

bp = Blueprint("feed", __name__)


@bp.get("/api/feed/config")
def feed_config():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(enabled=feed.feed_enabled(current_app.config["KHATA"])), 200
