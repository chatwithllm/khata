import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.services.auth import (
    register_user,
    authenticate_user,
    EmailTakenError,
    InvalidCredentialsError,
)


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        yield s


def test_register_then_authenticate(session):
    user = register_user(session, email="a@b.com", display_name="Arjun", password="pw12345")
    session.commit()
    assert user.id is not None
    got = authenticate_user(session, email="a@b.com", password="pw12345")
    assert got.id == user.id


def test_duplicate_email_rejected(session):
    register_user(session, email="a@b.com", display_name="A", password="pw12345")
    session.commit()
    with pytest.raises(EmailTakenError):
        register_user(session, email="a@b.com", display_name="A2", password="pw12345")


def test_bad_password_rejected(session):
    register_user(session, email="a@b.com", display_name="A", password="pw12345")
    session.commit()
    with pytest.raises(InvalidCredentialsError):
        authenticate_user(session, email="a@b.com", password="nope")


def test_google_create_new_user(session):
    from khata.services.auth import login_with_google
    claims = {"sub": "g-1", "email": "New@B.com", "email_verified": True, "name": "Neha"}
    user, created = login_with_google(session, claims=claims)
    session.commit()
    assert created is True
    assert user.email == "new@b.com"
    assert user.display_name == "Neha"
    assert user.password_hash is None
    assert user.google_sub == "g-1"


def test_google_links_existing_verified_email(session):
    from khata.services.auth import login_with_google
    existing = register_user(session, email="a@b.com", display_name="Arjun", password="pw12345")
    session.commit()
    claims = {"sub": "g-2", "email": "a@b.com", "email_verified": True, "name": "Arjun G"}
    user, created = login_with_google(session, claims=claims)
    session.commit()
    assert created is False
    assert user.id == existing.id
    assert user.google_sub == "g-2"
    assert user.display_name == "Arjun"  # not overwritten on link


def test_google_matches_by_sub_on_repeat(session):
    from khata.services.auth import login_with_google
    claims = {"sub": "g-3", "email": "c@b.com", "email_verified": True, "name": "Cee"}
    first, c1 = login_with_google(session, claims=claims)
    session.commit()
    again = {"sub": "g-3", "email": "changed@b.com", "email_verified": True, "name": "Cee2"}
    second, c2 = login_with_google(session, claims=again)
    session.commit()
    assert c1 is True and c2 is False
    assert second.id == first.id
    assert second.email == "c@b.com"  # original email unchanged


def test_google_unverified_email_refused(session):
    from khata.services.auth import login_with_google, EmailUnverifiedError
    claims = {"sub": "g-4", "email": "d@b.com", "email_verified": False, "name": "Dee"}
    with pytest.raises(EmailUnverifiedError):
        login_with_google(session, claims=claims)


def test_google_name_fallback_to_email(session):
    from khata.services.auth import login_with_google
    claims = {"sub": "g-5", "email": "e@b.com", "email_verified": True, "name": ""}
    user, created = login_with_google(session, claims=claims)
    session.commit()
    assert created is True
    assert user.display_name == "e@b.com"
