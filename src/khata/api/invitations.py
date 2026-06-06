from flask import Blueprint, g, jsonify

from ..services import sharing
from .auth import current_user

bp = Blueprint("invitations", __name__, url_prefix="/api/invitations")


@bp.get("")
def index():
    """Pending shares awaiting the current user's accept/decline."""
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(invitations=sharing.list_invitations(g.db, user.id)), 200


@bp.post("/<int:plan_id>/accept")
def accept(plan_id):
    return _respond(plan_id, accept=True)


@bp.post("/<int:plan_id>/decline")
def decline(plan_id):
    return _respond(plan_id, accept=False)


def _respond(plan_id, *, accept):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    try:
        result = sharing.respond_invitation(g.db, user_id=user.id, plan_id=plan_id, accept=accept)
        g.db.commit()
    except sharing.MemberError as e:
        g.db.rollback()
        code = 404 if str(e) == "not_a_member" else 409
        return jsonify(error=str(e)), code
    return jsonify(result), 200
