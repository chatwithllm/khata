"""Stateless bearer tokens for the mobile client.

The web app authenticates with a signed session cookie. Native mobile clients
can't carry cookies cleanly, so they get a signed bearer token instead. The
token is just the user id signed with the app SECRET_KEY (itsdangerous), so it
needs no DB table and is revoked en masse by rotating SECRET_KEY.

Same trust model as the session cookie (both rely on SECRET_KEY); the token
simply travels in an Authorization header instead of a Set-Cookie.
"""
from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT = "khata-mobile-bearer-v1"
# 30 days — long enough that the app rarely forces re-login, short enough that a
# leaked token expires on its own. The client refreshes by logging in again.
_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt=_SALT)


def issue_token(secret_key: str, user_id: int) -> str:
    """Return a signed bearer token carrying the user id."""
    return _serializer(secret_key).dumps({"uid": user_id})


def read_token(secret_key: str, token: str) -> int | None:
    """Return the user id from a valid token, or None if missing/invalid/expired."""
    if not token:
        return None
    try:
        data = _serializer(secret_key).loads(token, max_age=_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid")
    return uid if isinstance(uid, int) else None
