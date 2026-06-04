import pytest
from sqlalchemy import text

from khata.db import Base, make_engine, make_session_factory
from khata.models import User


def test_user_persists_and_enforces_unique_email():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        s.add(User(email="a@b.com", display_name="Arjun", password_hash="x"))
        s.commit()
        count = s.execute(text("SELECT COUNT(*) FROM users")).scalar()
        assert count == 1


def test_google_sub_persists_and_is_unique():
    from sqlalchemy.exc import IntegrityError
    from khata.db import Base, make_engine, make_session_factory
    from khata.models import User

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = make_session_factory(engine)()

    u = User(email="g@b.com", display_name="G", password_hash=None, google_sub="sub-123")
    s.add(u)
    s.commit()
    assert s.get(User, u.id).google_sub == "sub-123"

    s.add(User(email="h@b.com", display_name="H", password_hash=None, google_sub="sub-123"))
    with pytest.raises(IntegrityError):
        s.commit()
