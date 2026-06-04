from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.loans import (
    create_loan_plan,
    add_disbursement,
    log_loan_entry,
    loan_state,
    ValidationError,
)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="a@b.com", display_name="Arjun", password_hash="x")
        s.add(u)
        s.flush()
        yield s, u


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_create_loan_and_direction_wiring(ctx):
    s, u = ctx
    plan = create_loan_plan(s, owner_id=u.id, name="Gold loan", currency="INR",
                            direction="taken", interest_type="yearly", rate_bps=850,
                            start_date=date(2026, 1, 14))
    s.commit()
    assert plan.loan.direction == "taken" and plan.loan.rate_bps == 850
    d = add_disbursement(s, plan=plan, user_id=u.id, amount_minor=60000000,
                         occurred_at=_dt(2026, 1, 14))
    assert d.kind == "disbursement" and d.direction == "in"  # taken -> money to me
    p = log_loan_entry(s, plan=plan, user_id=u.id, kind="interest_payment",
                       amount_minor=2805, occurred_at=_dt(2026, 2, 14))
    assert p.direction == "out"  # taken -> I pay


def test_given_direction_flips_cashflow(ctx):
    s, u = ctx
    plan = create_loan_plan(s, owner_id=u.id, name="Lent S.Mehta", currency="INR",
                            direction="given", interest_type="monthly", rate_bps=200,
                            start_date=date(2026, 4, 2))
    d = add_disbursement(s, plan=plan, user_id=u.id, amount_minor=50000000,
                         occurred_at=_dt(2026, 4, 2))
    assert d.direction == "out"  # given -> money I lend
    r = log_loan_entry(s, plan=plan, user_id=u.id, kind="principal_repayment",
                       amount_minor=10000000, occurred_at=_dt(2026, 5, 2))
    assert r.direction == "in"  # given -> repaid to me


def test_create_loan_validates(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_loan_plan(s, owner_id=u.id, name="x", currency="INR", direction="sideways",
                         interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        create_loan_plan(s, owner_id=u.id, name="x", currency="INR", direction="taken",
                         interest_type="weekly", rate_bps=0, start_date=date(2026, 1, 1))


def test_log_loan_entry_validates(ctx):
    s, u = ctx
    plan = create_loan_plan(s, owner_id=u.id, name="L", currency="INR", direction="taken",
                            interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        log_loan_entry(s, plan=plan, user_id=u.id, kind="bribe", amount_minor=100,
                       occurred_at=_dt(2026, 1, 1))
    with pytest.raises(ValidationError):
        log_loan_entry(s, plan=plan, user_id=u.id, kind="interest_payment", amount_minor=0,
                       occurred_at=_dt(2026, 1, 1))
