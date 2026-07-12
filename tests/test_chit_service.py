from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.chits import (create_chit_plan, duplicate_chit_plan, log_chit_entry,
                                  chit_state, auction_dividend, ChitError, ValidationError)


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


def test_schedule_paid_due_upcoming(ctx):
    s, u = ctx
    p = _chit(s, u)  # 20-month chit from 2026-01-01, subscription 50,000
    # record 3 contributions → first 3 months paid
    for d in (1, 2, 3):
        log_chit_entry(s, plan=p, user_id=u.id, kind="chit_contribution",
                       amount_minor=5000000, occurred_at=_dt(d))
    s.commit()
    # as_of mid-run: 2026-05 → months 0..4 have arrived (Jan..May), 3 paid, 2 overdue
    st = chit_state(s, p.chit, as_of=date(2026, 5, 15))
    assert st["term_months"] == 20
    assert len(st["schedule"]) == 20
    statuses = [r["status"] for r in st["schedule"]]
    assert statuses[:3] == ["paid", "paid", "paid"]
    assert statuses[3] == "due" and statuses[4] == "due"      # Apr, May arrived, unpaid
    assert statuses[5] == "upcoming"                          # Jun not yet
    assert st["schedule"][0]["period_start"] == "2026-01-01"
    assert st["schedule"][1]["period_start"] == "2026-02-01"
    assert st["next_due_month"] == 3
    assert st["next_due_date"] == "2026-04-01"
    assert st["months_behind"] == 2                           # Apr + May overdue
    assert st["schedule"][0]["expected_minor"] == 5000000


def test_schedule_fully_paid(ctx):
    s, u = ctx
    p = create_chit_plan(s, owner_id=u.id, name="C", currency="INR",
                         chit_value_minor=100000000, n_members=3, commission_bps=0,
                         start_date=date(2026, 1, 1))
    for d in (1, 2, 3):
        log_chit_entry(s, plan=p, user_id=u.id, kind="chit_contribution",
                       amount_minor=int(100000000 / 3), occurred_at=_dt(d))
    s.commit()
    st = chit_state(s, p.chit, as_of=date(2026, 6, 1))
    assert [r["status"] for r in st["schedule"]] == ["paid", "paid", "paid"]
    assert st["next_due_month"] is None and st["next_due_date"] is None
    assert st["months_behind"] == 0


def test_duplicate_copies_terms_empty_ledger(ctx):
    s, u = ctx
    src = _chit(s, u)  # value 100000000 minor, 20 members, 500 bps, 2026-01-01
    log_chit_entry(s, plan=src, user_id=u.id, kind="chit_contribution", amount_minor=5000000, occurred_at=_dt(1))
    s.commit()
    dup = duplicate_chit_plan(s, source_plan=src, owner_id=u.id, name="C -2")
    s.commit()
    assert dup.id != src.id
    assert dup.name == "C -2"
    assert dup.type == "chit"
    assert dup.currency == src.currency
    assert dup.chit.chit_value_minor == src.chit.chit_value_minor
    assert dup.chit.n_members == src.chit.n_members
    assert dup.chit.commission_bps == src.chit.commission_bps
    assert dup.chit.start_date == src.chit.start_date
    assert list(dup.ledger_entries) == []
    st = chit_state(s, dup.chit)
    assert st["months_recorded"] == 0
    assert st["total_contributed_minor"] == 0


def test_validation(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_chit_plan(s, owner_id=u.id, name="C", currency="INR", chit_value_minor=100000000,
                         n_members=1, commission_bps=0, start_date=date(2026, 1, 1))  # n<2
    p = _chit(s, u)
    with pytest.raises(ValidationError):
        log_chit_entry(s, plan=p, user_id=u.id, kind="bogus", amount_minor=1, occurred_at=_dt(1))
