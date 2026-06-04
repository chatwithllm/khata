from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User
from ..security import hash_password, verify_password


class AuthError(Exception):
    pass


class EmailTakenError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class GoogleAuthError(AuthError):
    pass


class EmailUnverifiedError(GoogleAuthError):
    pass


def register_user(session: Session, *, email: str, display_name: str, password: str) -> User:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AuthError("invalid email")
    if len(password) < 6:
        raise AuthError("password too short")
    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise EmailTakenError(email)
    user = User(email=email, display_name=display_name.strip() or email,
                password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def authenticate_user(session: Session, *, email: str, password: str) -> User:
    email = email.strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password_hash or ""):
        raise InvalidCredentialsError(email)
    return user


def verify_google_credential(credential: str, client_id: str) -> dict:
    """Verify a Google Identity Services ID token; return the relevant claims.

    Raises GoogleAuthError on any verification failure. google-auth is imported
    lazily so the rest of the auth module (and tests that stub the verifier) do
    not require the package.
    """
    from google.oauth2 import id_token
    from google.auth.transport import requests as ga_requests

    try:
        info = id_token.verify_oauth2_token(credential, ga_requests.Request(), client_id)
    except ValueError as e:
        raise GoogleAuthError(str(e)) from e
    return {
        "sub": info["sub"],
        "email": info.get("email"),
        "email_verified": bool(info.get("email_verified", False)),
        "name": info.get("name"),
    }


def login_with_google(session: Session, *, claims: dict) -> tuple[User, bool]:
    """Find-by-sub / link-by-verified-email / create. Returns (user, created)."""
    sub = claims["sub"]
    user = session.scalar(select(User).where(User.google_sub == sub))
    if user is not None:
        return user, False

    if not claims.get("email_verified"):
        raise EmailUnverifiedError("email_unverified")
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise EmailUnverifiedError("email_unverified")

    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        existing.google_sub = sub
        session.flush()
        return existing, False

    name = (claims.get("name") or "").strip() or email
    user = User(email=email, display_name=name, password_hash=None, google_sub=sub)
    session.add(user)
    session.flush()
    return user, True
