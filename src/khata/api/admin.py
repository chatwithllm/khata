"""Admin API — user management (admin-only).

Gated by `services.admin.is_admin`. All routes 403 for non-admins. The service layer
enforces the "always keep one enabled admin" invariant and the no-self-footgun rules.
"""
from flask import Blueprint, g, jsonify, request

from ..services import admin
from ..services.admin import AdminError
from .auth import current_user

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _require_admin():
    user = current_user()
    if user is None:
        return None, (jsonify(error="unauthenticated"), 401)
    if not admin.is_admin(user):
        return None, (jsonify(error="forbidden", detail="admin only"), 403)
    return user, None


@bp.get("/users")
def list_users():
    _, err = _require_admin()
    if err:
        return err
    return jsonify(users=admin.list_users(g.db)), 200


@bp.post("/users/<int:user_id>/disable")
def set_disabled(user_id):
    actor, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        u = admin.set_disabled(g.db, actor=actor, user_id=user_id, disabled=bool(data.get("disabled")))
        g.db.commit()
    except AdminError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True, disabled=u.disabled), 200


@bp.post("/users/<int:user_id>/admin")
def set_admin(user_id):
    actor, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        u = admin.set_admin(g.db, actor=actor, user_id=user_id, make_admin=bool(data.get("is_admin")))
        g.db.commit()
    except AdminError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True, is_admin=u.is_admin), 200


@bp.post("/users/<int:user_id>/reset-password")
def reset_password(user_id):
    _, err = _require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        admin.reset_password(g.db, user_id=user_id, new_password=data.get("password", ""))
        g.db.commit()
    except AdminError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True), 200


@bp.delete("/users/<int:user_id>")
def delete_user(user_id):
    actor, err = _require_admin()
    if err:
        return err
    try:
        stats = admin.delete_user(g.db, actor=actor, user_id=user_id)
        g.db.commit()
    except AdminError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True, **stats), 200
