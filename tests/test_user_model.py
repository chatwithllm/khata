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
