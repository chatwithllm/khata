from flask import Blueprint, current_app, g, jsonify, request, session

from ..tokens import issue_token, read_token
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
            "has_password": bool(user.password_hash), "avatar": user.avatar,
            "is_admin": user.is_admin}


def _bearer_uid():
    """User id from an Authorization: Bearer <token> header, if present and valid."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    return read_token(current_app.config["SECRET_KEY"], token)


def current_user():
    # Web clients carry the session cookie; mobile clients carry a bearer token.
    # Either one identifies the user — the rest of the API is auth-mechanism-agnostic.
    uid = session.get("user_id")
    if uid is None:
        uid = _bearer_uid()
    if uid is None:
        return None
    user = g.db.get(User, uid)
    # A disabled account's live session/token stops resolving — an immediate, reversible
    # lockout without deleting any data.
    if user is not None and user.disabled:
        return None
    return user


def _token_for(user: User) -> str:
    return issue_token(current_app.config["SECRET_KEY"], user.id)


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
    return jsonify(user=_user_json(user), token=_token_for(user)), 201


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    try:
        user = authenticate_user(g.db, email=data.get("email", ""), password=data.get("password", ""))
    except InvalidCredentialsError:
        return jsonify(error="invalid_credentials"), 401
    if user.disabled:
        return jsonify(error="account_disabled", detail="this account has been disabled by an admin"), 403
    session["user_id"] = user.id
    return jsonify(user=_user_json(user), token=_token_for(user)), 200


@bp.post("/logout")
def logout():
    session.pop("user_id", None)
    return jsonify(ok=True), 200


@bp.get("/me")
def me():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    from .backup import _is_operator  # local import avoids a blueprint import cycle
    return jsonify(user=_user_json(user), is_operator=_is_operator(user)), 200


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


# Cropped avatars are stored as small data URLs. Cap the payload so the DB / JSON backup
# stay lean (a 256px JPEG is well under this; reject anything that isn't a small image).
_AVATAR_MAX = 200_000   # ~200 KB of data-URL text


@bp.post("/avatar")
def set_avatar_route():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    av = data.get("avatar")
    if av in (None, ""):
        user.avatar = None            # clear the photo
    else:
        if not isinstance(av, str) or not av.startswith("data:image/"):
            return jsonify(error="invalid", detail="avatar must be an image data URL"), 400
        if len(av) > _AVATAR_MAX:
            return jsonify(error="invalid", detail="image too large — crop/zoom to a smaller area"), 413
        user.avatar = av
    g.db.commit()
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
    if user.disabled:
        return jsonify(error="account_disabled", detail="this account has been disabled by an admin"), 403
    session["user_id"] = user.id
    return jsonify(user=_user_json(user), created=created, token=_token_for(user)), 200
