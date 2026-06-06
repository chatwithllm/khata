from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.services.fx import set_rate, get_rate, convert, FxError, ValidationError


@pytest.fixture
def s():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as sess:
        yield sess


def _now():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_convert_math():
    # 1 USD = ₹83.42 → rate_micro 83_420_000. $1.00 (100 USD-minor) → ₹83.42 (8342 INR-minor)
    assert convert(100, rate_micro=83_420_000) == 8342
    assert convert(0, rate_micro=83_420_000) == 0


def test_set_get_and_upsert(s):
    set_rate(s, base="INR", quote="USD", rate_micro=83_420_000, as_of=_now())
    s.commit()
    assert get_rate(s, "INR", "USD") == 83_420_000
    # upsert: same pair updates, does not duplicate
    set_rate(s, base="INR", quote="USD", rate_micro=84_000_000, as_of=_now())
    s.commit()
    assert get_rate(s, "INR", "USD") == 84_000_000
    from khata.models import FxRate
    assert s.query(FxRate).count() == 1


def test_get_rate_identity_and_miss(s):
    assert get_rate(s, "INR", "INR") == 1_000_000   # identity
    assert get_rate(s, "INR", "USD") is None         # unset


def test_set_rate_validation(s):
    with pytest.raises(ValidationError):
        set_rate(s, base="INR", quote="INR", rate_micro=1_000_000, as_of=_now())  # same
    with pytest.raises(ValidationError):
        set_rate(s, base="INR", quote="USD", rate_micro=0, as_of=_now())          # non-positive
    with pytest.raises(ValidationError):
        set_rate(s, base="EUR", quote="USD", rate_micro=1, as_of=_now())          # unsupported


def test_get_rate_inverse_fallback(s):
    # store INR→USD only; a USD-base user converting USD→INR must still resolve via inverse
    set_rate(s, base="INR", quote="USD", rate_micro=12_000, as_of=_now())  # 1 INR = 0.012 USD
    s.commit()
    assert get_rate(s, "INR", "USD") == 12_000
    inv = get_rate(s, "USD", "INR")
    assert inv is not None
    # 1/0.012 ≈ 83.33 → ~83_333_333 micro
    assert 83_000_000 <= inv <= 83_700_000


def test_get_rate_identity_and_missing(s):
    assert get_rate(s, "USD", "USD") == 1_000_000
    assert get_rate(s, "USD", "INR") is None
