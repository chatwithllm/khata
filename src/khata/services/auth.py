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
