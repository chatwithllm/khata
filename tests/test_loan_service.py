from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.loans import (
    create_loan_plan,
    add_disbursement,
    log_loan_entry,
    loan_state,
    set_collateral,
    ValidationError,
)
from khata.services.holdings import create_holding_plan, add_buy, set_quote


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


def _loan(s, u, **kw):
    base = dict(name="L", currency="INR", direction="taken", interest_type="monthly",
                rate_bps=200, start_date=date(2026, 1, 1))
    base.update(kw)
    return create_loan_plan(s, owner_id=u.id, **base)


def test_interest_single_tranche_monthly(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=200, interest_type="monthly", start_date=date(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 1))
    st = loan_state(s, plan.loan, as_of=date(2026, 4, 1))  # 3 complete months @ 2% of 1,00,000
    assert st["principal_outstanding_minor"] == 10000000
    assert st["interest_accrued_minor"] == 600000   # 3 × 2,000.00
    assert st["interest_due_minor"] == 600000
    assert len(st["schedule"]) == 3
    assert st["next_due_month"] == 0 and st["months_behind"] == 3


def test_interest_yearly_rate(ctx):
    s, u = ctx
    plan = _loan(s, u, interest_type="yearly", rate_bps=1200, start_date=date(2026, 1, 1))  # 12%/yr = 1%/mo
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 1))
    st = loan_state(s, plan.loan, as_of=date(2026, 3, 1))  # 2 months
    assert st["interest_accrued_minor"] == 200000  # 2 × 1,000.00


def test_topup_tranche_increases_accrual(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=200, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 2, 1))
    st = loan_state(s, plan.loan, as_of=date(2026, 3, 1))  # 2 months
    assert st["interest_accrued_minor"] == 600000  # m0 1L->2,000 ; m1 2L->4,000
    assert st["principal_outstanding_minor"] == 20000000


def test_partial_principal_repayment_reduces_accrual(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=200, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=20000000, occurred_at=_dt(2026, 1, 1))
    log_loan_entry(s, plan=plan, user_id=u.id, kind="principal_repayment",
                   amount_minor=10000000, occurred_at=_dt(2026, 2, 1))
    st = loan_state(s, plan.loan, as_of=date(2026, 3, 1))  # 2 months
    assert st["interest_accrued_minor"] == 600000  # m0 2L->4,000 ; m1 1L->2,000
    assert st["principal_outstanding_minor"] == 10000000


def test_none_interest_zero(ctx):
    s, u = ctx
    plan = _loan(s, u, interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=50000000, occurred_at=_dt(2026, 1, 1))
    st = loan_state(s, plan.loan, as_of=date(2027, 1, 1))
    assert st["interest_accrued_minor"] == 0 and st["schedule"] == []
    assert st["principal_outstanding_minor"] == 50000000


def test_interest_payments_greedy_schedule(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=200, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 1))
    log_loan_entry(s, plan=plan, user_id=u.id, kind="interest_payment",
                   amount_minor=300000, occurred_at=_dt(2026, 2, 1))  # pay 3,000
    st = loan_state(s, plan.loan, as_of=date(2026, 4, 1))  # 3 months × 2,000 = 6,000 accrued
    assert st["interest_paid_minor"] == 300000
    assert st["interest_due_minor"] == 300000
    sch = st["schedule"]
    assert sch[0]["status"] == "paid"
    assert sch[1]["status"] == "partial" and sch[1]["applied_minor"] == 100000
    assert sch[2]["status"] == "due"
    assert st["next_due_month"] == 1 and st["months_behind"] == 2


def test_interest_end_of_month_start_clamps(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=100, interest_type="monthly", start_date=date(2026, 1, 31))  # 1%/mo
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 31))
    st = loan_state(s, plan.loan, as_of=date(2026, 3, 31))  # 2 complete months
    assert len(st["schedule"]) == 2
    assert st["schedule"][1]["period_start"] == "2026-02-28"   # Feb clamped from day 31
    assert st["interest_accrued_minor"] == 200000              # 2 × 1% × 1,00,000


# ── Collateral / LTV (Plan 4.2 Task 2) ───────────────────────────────────────

def _quoted_holding(s, owner_id, *, currency="INR", price_minor=10000000):
    """Holding with a buy of 10 units, quoted so current_value_minor == price_minor*10.
    With price_minor=10000000 → current_value_minor == 100000000 (₹10,00,000)."""
    hp = create_holding_plan(s, owner_id=owner_id, name="Gold", currency=currency,
                             asset_class="gold", unit="g")
    add_buy(s, plan=hp, user_id=owner_id, quantity_micro=10_000_000,  # 10 units
            amount_minor=80000000, occurred_at=_dt(2026, 1, 1))
    set_quote(s, plan=hp, price_minor=price_minor, as_of=date(2026, 1, 1))
    return hp


def _taken_loan_disbursed(s, owner_id, amount_minor, *, currency="INR"):
    lp = create_loan_plan(s, owner_id=owner_id, name="GL", currency=currency,
                          direction="taken", interest_type="none", rate_bps=0,
                          start_date=date(2026, 1, 1))
    add_disbursement(s, plan=lp, user_id=owner_id, amount_minor=amount_minor,
                     occurred_at=_dt(2026, 1, 1))
    return lp


def test_set_collateral_and_ltv(ctx):
    s, u = ctx
    hp = _quoted_holding(s, u.id)                              # value 100000000
    lp = _taken_loan_disbursed(s, u.id, 60000000)             # principal 60000000
    set_collateral(s, plan=lp, collateral_plan_id=hp.id)
    s.commit()
    st = loan_state(s, lp.loan, as_of=date(2026, 6, 1))
    assert st["secured"] is True
    assert st["collateral"] is not None
    assert st["collateral"]["plan_id"] == hp.id
    assert st["collateral"]["asset_class"] == "gold"
    assert st["collateral"]["currency"] == "INR"
    assert st["collateral"]["value_minor"] == 100000000
    # round(60000000 * 100 / 100000000) == round(60.0) == 60
    assert st["collateral"]["ltv_pct"] == 60


def test_set_collateral_non_holding_rejected(ctx):
    s, u = ctx
    lp = _taken_loan_disbursed(s, u.id, 60000000)
    # another loan plan (type == "loan", not "holding") as collateral target
    other = create_loan_plan(s, owner_id=u.id, name="Other", currency="INR",
                             direction="taken", interest_type="none", rate_bps=0,
                             start_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        set_collateral(s, plan=lp, collateral_plan_id=other.id)


def test_set_collateral_cross_currency_rejected(ctx):
    s, u = ctx
    hp = create_holding_plan(s, owner_id=u.id, name="US Gold", currency="USD",
                             asset_class="gold", unit="oz")
    lp = _taken_loan_disbursed(s, u.id, 60000000, currency="INR")
    with pytest.raises(ValidationError):
        set_collateral(s, plan=lp, collateral_plan_id=hp.id)


def test_set_collateral_cross_owner_rejected(ctx):
    s, u = ctx
    other_user = User(email="b@b.com", display_name="Bina", password_hash="x")
    s.add(other_user)
    s.flush()
    hp = create_holding_plan(s, owner_id=other_user.id, name="Their Gold", currency="INR",
                             asset_class="gold", unit="g")
    lp = _taken_loan_disbursed(s, u.id, 60000000)
    with pytest.raises(ValidationError):
        set_collateral(s, plan=lp, collateral_plan_id=hp.id)


def test_set_collateral_unlink(ctx):
    s, u = ctx
    hp = _quoted_holding(s, u.id)
    lp = _taken_loan_disbursed(s, u.id, 60000000)
    set_collateral(s, plan=lp, collateral_plan_id=hp.id)
    set_collateral(s, plan=lp, collateral_plan_id=None)
    s.commit()
    st = loan_state(s, lp.loan, as_of=date(2026, 6, 1))
    assert st["secured"] is False
    assert st["collateral"] is None


def test_set_collateral_unquoted_holding_no_ltv(ctx):
    s, u = ctx
    # holding with a buy but NO quote → current_value_minor is None
    hp = create_holding_plan(s, owner_id=u.id, name="Unquoted", currency="INR",
                             asset_class="gold", unit="g")
    add_buy(s, plan=hp, user_id=u.id, quantity_micro=10_000_000,
            amount_minor=80000000, occurred_at=_dt(2026, 1, 1))
    lp = _taken_loan_disbursed(s, u.id, 60000000)
    set_collateral(s, plan=lp, collateral_plan_id=hp.id)
    s.commit()
    st = loan_state(s, lp.loan, as_of=date(2026, 6, 1))
    assert st["secured"] is True
    assert st["collateral"] is not None
    assert st["collateral"]["value_minor"] is None
    assert st["collateral"]["ltv_pct"] is None


def test_collateral_ltv_rounds_half_up(ctx):
    s, u = ctx
    # value 100000000; principal 66666667 → 66.666... → HALF_UP → 67
    hp = _quoted_holding(s, u.id)                              # value 100000000
    lp = _taken_loan_disbursed(s, u.id, 66666667)
    set_collateral(s, plan=lp, collateral_plan_id=hp.id)
    s.commit()
    st = loan_state(s, lp.loan, as_of=date(2026, 6, 1))
    assert st["collateral"]["ltv_pct"] == 67
