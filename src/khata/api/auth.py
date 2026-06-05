from flask import Blueprint, current_app, g, jsonify, request, session

from ..services.auth import (
    register_user,
    authenticate_user,
    set_password,
    update_profile,
    login_with_google,
    EmailTakenError,
    InvalidCredentialsError,
    GoogleAuthError,
    EmailUnverifiedError,
    AuthError,
)
from ..models import User

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _user_json(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name,
            "has_password": bool(user.password_hash)}


def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    return g.db.get(User, uid)


@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    try:
        user = register_user(
            g.db,
            email=data.get("email", ""),
            display_name=data.get("display_name", ""),
            password=data.get("password", ""),
        )
        g.db.commit()
    except EmailTakenError:
        g.db.rollback()
        return jsonify(error="email_taken"), 409
    except AuthError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    session["user_id"] = user.id
    return jsonify(user=_user_json(user)), 201


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    try:
        user = authenticate_user(g.db, email=data.get("email", ""), password=data.get("password", ""))
    except InvalidCredentialsError:
        return jsonify(error="invalid_credentials"), 401
    session["user_id"] = user.id
    return jsonify(user=_user_json(user)), 200


@bp.post("/logout")
def logout():
    session.pop("user_id", None)
    return jsonify(ok=True), 200


@bp.get("/me")
def me():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(user=_user_json(user)), 200


@bp.post("/password")
def set_password_route():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    try:
        set_password(g.db, user=user, password=data.get("password", ""))
        g.db.commit()
    except AuthError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True), 200


@bp.post("/profile")
def update_profile_route():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    try:
        update_profile(g.db, user=user, display_name=data.get("display_name", ""))
        g.db.commit()
    except AuthError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(user=_user_json(user)), 200


@bp.get("/config")
def auth_config():
    cfg = current_app.config["KHATA"]
    return jsonify(google_client_id=cfg.google_client_id), 200


@bp.post("/google")
def google_login():
    cfg = current_app.config["KHATA"]
    if not cfg.google_client_id:
        return jsonify(error="google_not_configured"), 503
    data = request.get_json(silent=True) or {}
    verifier = current_app.config["GOOGLE_VERIFIER"]
    try:
        claims = verifier(data.get("credential", ""), cfg.google_client_id)
        user, created = login_with_google(g.db, claims=claims)
        g.db.commit()
    except EmailUnverifiedError:
        g.db.rollback()
        return jsonify(error="email_unverified"), 403
    except (GoogleAuthError, ValueError):
        g.db.rollback()
        return jsonify(error="invalid_token"), 401
    session["user_id"] = user.id
    return jsonify(user=_user_json(user), created=created), 200
