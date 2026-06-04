from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.assets import (
    create_asset_plan,
    set_installments,
    log_payment,
    list_plans,
    asset_state,
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


def _now():
    return datetime.now(timezone.utc)


def test_create_plan_and_list(ctx):
    s, u = ctx
    plan = create_asset_plan(s, owner_id=u.id, name="Plot", currency="INR",
                             total_price_minor=100000)
    s.commit()
    assert plan.id is not None
    assert plan.asset.total_price_minor == 100000
    assert [p.id for p in list_plans(s, u.id)] == [plan.id]


def test_create_plan_rejects_nonpositive_price(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_asset_plan(s, owner_id=u.id, name="X", currency="INR", total_price_minor=0)


def test_set_installments_replaces(ctx):
    s, u = ctx
    plan = create_asset_plan(s, owner_id=u.id, name="Plot", currency="INR",
                             total_price_minor=100000)
    set_installments(s, plan=plan, items=[{"amount_minor": 25000}, {"amount_minor": 25000}])
    set_installments(s, plan=plan, items=[{"amount_minor": 50000}])
    s.commit()
    assert [(i.seq, i.planned_amount_minor) for i in plan.installments] == [(1, 50000)]


def test_log_payment_validates_method_and_source(ctx):
    s, u = ctx
    plan = create_asset_plan(s, owner_id=u.id, name="Plot", currency="INR",
                             total_price_minor=100000)
    with pytest.raises(ValidationError):
        log_payment(s, plan=plan, user_id=u.id, amount_minor=1000, occurred_at=_now(),
                    method="bitcoin", funding_source="savings")
    with pytest.raises(ValidationError):
        log_payment(s, plan=plan, user_id=u.id, amount_minor=1000, occurred_at=_now(),
                    method="cash", funding_source="lottery")
    entry = log_payment(s, plan=plan, user_id=u.id, amount_minor=1000, occurred_at=_now(),
                        method="cash", funding_source="savings")
    s.commit()
    assert entry.id is not None
    assert entry.currency == "INR"


def test_set_installments_rejects_nonpositive(ctx):
    s, u = ctx
    plan = create_asset_plan(s, owner_id=u.id, name="P", currency="INR", total_price_minor=100000)
    with pytest.raises(ValidationError):
        set_installments(s, plan=plan, items=[{"amount_minor": 1000}, {"amount_minor": 0}])


def test_log_payment_rejects_nonpositive_amount_and_bad_direction(ctx):
    s, u = ctx
    plan = create_asset_plan(s, owner_id=u.id, name="P", currency="INR", total_price_minor=100000)
    with pytest.raises(ValidationError):
        log_payment(s, plan=plan, user_id=u.id, amount_minor=0, occurred_at=_now(),
                    method="cash", funding_source="savings")
    with pytest.raises(ValidationError):
        log_payment(s, plan=plan, user_id=u.id, amount_minor=1000, occurred_at=_now(),
                    method="cash", funding_source="savings", direction="sideways")


def _plan_with_schedule(s, u, total, amounts):
    plan = create_asset_plan(s, owner_id=u.id, name="Plot", currency="INR",
                             total_price_minor=total)
    set_installments(s, plan=plan, items=[{"amount_minor": a} for a in amounts])
    return plan


def _pay(s, u, plan, amount, source="savings"):
    log_payment(s, plan=plan, user_id=u.id, amount_minor=amount, occurred_at=_now(),
                method="transfer", funding_source=source)


def test_state_exact_and_partial_rollforward(ctx):
    s, u = ctx
    plan = _plan_with_schedule(s, u, 100000, [25000, 25000, 25000, 25000])
    _pay(s, u, plan, 30000)  # covers #1 fully, #2 partially (greedy/fungible)
    st = asset_state(s, plan)
    assert st["paid_to_date_minor"] == 30000
    assert st["remaining_minor"] == 70000
    assert st["overpaid_minor"] == 0
    rows = st["installments"]
    assert rows[0]["status"] == "paid" and rows[0]["applied_minor"] == 25000
    assert rows[1]["status"] == "partial" and rows[1]["applied_minor"] == 5000
    assert rows[2]["status"] == "due" and rows[2]["applied_minor"] == 0
    assert st["next_due_seq"] == 2


def test_state_multiple_payments_and_fully_paid(ctx):
    s, u = ctx
    plan = _plan_with_schedule(s, u, 50000, [25000, 25000])
    _pay(s, u, plan, 25000)
    _pay(s, u, plan, 25000)
    st = asset_state(s, plan)
    assert st["remaining_minor"] == 0
    assert all(r["status"] == "paid" for r in st["installments"])
    assert st["next_due_seq"] is None


def test_state_overpaid(ctx):
    s, u = ctx
    plan = _plan_with_schedule(s, u, 50000, [25000])
    _pay(s, u, plan, 60000)
    st = asset_state(s, plan)
    assert st["remaining_minor"] == 0
    assert st["overpaid_minor"] == 10000


def test_state_funding_breakdown(ctx):
    s, u = ctx
    plan = _plan_with_schedule(s, u, 100000, [100000])
    _pay(s, u, plan, 30000, source="savings")
    _pay(s, u, plan, 10000, source="loan")
    st = asset_state(s, plan)
    fb = {d["source"]: d for d in st["funding_breakdown"]}
    assert fb["savings"]["amount_minor"] == 30000 and fb["savings"]["pct"] == 75
    assert fb["loan"]["amount_minor"] == 10000 and fb["loan"]["pct"] == 25
    assert st["funding_breakdown"][0]["source"] == "savings"  # biggest first


def test_create_plan_rejects_unknown_currency(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_asset_plan(s, owner_id=u.id, name="X", currency="XYZ", total_price_minor=100000)


def test_state_excludes_in_direction_entries(ctx):
    s, u = ctx
    plan = _plan_with_schedule(s, u, 100000, [100000])
    _pay(s, u, plan, 30000, source="savings")  # out — counts
    # an 'in' funding receipt must NOT count toward paid or breakdown
    log_payment(s, plan=plan, user_id=u.id, amount_minor=50000, occurred_at=_now(),
                method="transfer", funding_source="borrowed", direction="in")
    st = asset_state(s, plan)
    assert st["paid_to_date_minor"] == 30000
    assert [d["source"] for d in st["funding_breakdown"]] == ["savings"]
