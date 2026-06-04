from flask import Blueprint, g, jsonify, request, session

from ..services.auth import (
    register_user,
    authenticate_user,
    EmailTakenError,
    InvalidCredentialsError,
    AuthError,
)
from ..models import User

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _user_json(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name}


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
