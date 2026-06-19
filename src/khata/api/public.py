from flask import Blueprint, g, jsonify

from ..services import sharing_links

bp = Blueprint("public", __name__, url_prefix="/api/public")


@bp.get("/<token>")
def public_view(token):
    try:
        plan, scope = sharing_links.resolve_public(g.db, token)
    except sharing_links.ShareNotFound:
        return jsonify(error="not_found"), 404
    except sharing_links.ShareGone:
        return jsonify(error="gone"), 410
    resp = jsonify(sharing_links.public_state(g.db, plan, scope))
    resp.headers["Cache-Control"] = "no-store"
    return resp, 200
