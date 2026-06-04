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
