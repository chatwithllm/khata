import pytest
from sqlalchemy.exc import IntegrityError

from khata.db import Base, make_engine, make_session_factory
from khata.models import FxRate


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_fx_rate_persists_and_pair_unique():
    s = _session()
    s.add(FxRate(base_currency="INR", quote_currency="USD", rate_micro=83_420_000))
    s.commit()
    assert s.query(FxRate).count() == 1
    s.add(FxRate(base_currency="INR", quote_currency="USD", rate_micro=84_000_000))
    with pytest.raises(IntegrityError):
        s.commit()
