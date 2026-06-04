from sqlalchemy import text

from khata.db import make_engine, make_session_factory


def test_engine_runs_and_wal_enabled():
    engine = make_engine("sqlite:///:memory:")
    Session = make_session_factory(engine)
    with Session() as s:
        assert s.execute(text("SELECT 1")).scalar() == 1
