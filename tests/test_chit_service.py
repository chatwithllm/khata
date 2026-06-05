from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.chits import (create_chit_plan, log_chit_entry, chit_state,
                                  auction_dividend, ChitError, ValidationError)


@pytest.fixture
def ctx():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    S = make_session_factory(e)
    with S() as s:
        u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
        yield s, u


def _dt(d=1): return datetime(2026, 1, d, tzinfo=timezone.utc)


def _chit(s, u):
    return create_chit_plan(s, owner_id=u.id, name="C", currency="INR",
                            chit_value_minor=100000000, n_members=20, commission_bps=500,
                            start_date=date(2026, 1, 1))


def test_subscription_and_net(ctx):
    s, u = ctx
    p = _chit(s, u)
    # chit value 10,00,000 over 20 members → subscription 50,000 (5000000 minor)
    log_chit_entry(s, plan=p, user_id=u.id, kind="chit_contribution", amount_minor=5000000, occurred_at=_dt(1))
    log_chit_entry(s, plan=p, user_id=u.id, kind="chit_dividend", amount_minor=200000, occurred_at=_dt(1))
    s.commit()
    st = chit_state(s, p.chit)
    assert st["subscription_minor"] == 5000000
    assert st["total_contributed_minor"] == 5000000
    assert st["total_dividends_minor"] == 200000
    assert st["net_contributed_minor"] == 4800000
    assert st["net_position_minor"] == 200000 - 5000000
    assert st["won"] is False


def test_win_makes_net_positive(ctx):
    s, u = ctx
    p = _chit(s, u)
    log_chit_entry(s, plan=p, user_id=u.id, kind="chit_contribution", amount_minor=5000000, occurred_at=_dt(1))
    log_chit_entry(s, plan=p, user_id=u.id, kind="chit_prize", amount_minor=92000000, occurred_at=_dt(2))
    s.commit()
    st = chit_state(s, p.chit)
    assert st["prize_received_minor"] == 92000000
    assert st["won"] is True
    assert st["net_position_minor"] == 92000000 - 5000000


def test_auction_dividend_math():
    # chit value 10,00,000; commission 5% = 50,000; winning bid 1,00,000
    d = auction_dividend(chit_value_minor=100000000, commission_bps=500, n_members=20,
                         winning_bid_minor=10000000)
    assert d["commission_minor"] == 5000000           # 50,000
    assert d["dividend_pool_minor"] == 5000000         # bid 1,00,000 − commission 50,000
    assert d["dividend_per_member_minor"] == 250000    # / 20 = 2,500
    assert d["prize_minor"] == 90000000                # chit value − bid = 9,00,000


def test_validation(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_chit_plan(s, owner_id=u.id, name="C", currency="INR", chit_value_minor=100000000,
                         n_members=1, commission_bps=0, start_date=date(2026, 1, 1))  # n<2
    p = _chit(s, u)
    with pytest.raises(ValidationError):
        log_chit_entry(s, plan=p, user_id=u.id, kind="bogus", amount_minor=1, occurred_at=_dt(1))
