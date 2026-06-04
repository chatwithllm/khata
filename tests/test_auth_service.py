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
