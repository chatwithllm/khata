from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.holdings import (
    create_holding_plan, add_buy, add_sell, set_quote, holding_state,
    HoldingError, ValidationError,
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


def _dt(day=1):
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def _gold(s, u):
    return create_holding_plan(s, owner_id=u.id, name="Gold 22K", currency="INR",
                               asset_class="gold", unit="gram", purity="22K")


def test_create_holding_plan(ctx):
    s, u = ctx
    plan = _gold(s, u)
    s.commit()
    assert plan.type == "holding"
    assert plan.holding.asset_class == "gold"
    st = holding_state(s, plan.holding)
    assert st["qty_held_micro"] == 0
    assert st["current_value_minor"] is None  # no quote yet


def test_buy_tranches_average_cost(ctx):
    s, u = ctx
    plan = _gold(s, u)
    # 10 g @ 50,000/g = 500,000 ; 5 g @ 56,000/g = 280,000
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=10_000_000, amount_minor=50000000,
            occurred_at=_dt(1))
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=5_000_000, amount_minor=28000000,
            occurred_at=_dt(2))
    s.commit()
    st = holding_state(s, plan.holding)
    assert st["qty_held_micro"] == 15_000_000           # 15 g
    # avg = (50000000 + 28000000) / 15 = 5200000 minor/g
    # (consistent with cost_of_held_minor below: 5200000 * 15 == 78000000)
    assert st["avg_cost_per_unit_minor"] == 5200000
    assert st["cost_of_held_minor"] == 78000000          # 780,000


def test_quote_sets_value_and_unrealized(ctx):
    s, u = ctx
    plan = _gold(s, u)
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=10_000_000, amount_minor=50000000,
            occurred_at=_dt(1))
    set_quote(s, plan=plan, price_minor=60000, as_of=_dt(3))   # 600/g spot
    s.commit()
    st = holding_state(s, plan.holding)
    assert st["current_value_minor"] == 60000 * 10        # 600,000
    assert st["unrealized_gain_minor"] == 60000 * 10 - 50000000  # 100,000


def test_sell_reduces_qty_and_realized_gain(ctx):
    s, u = ctx
    plan = _gold(s, u)
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=10_000_000, amount_minor=50000000,
            occurred_at=_dt(1))   # avg 50,000/g
    add_sell(s, plan=plan, user_id=u.id, quantity_micro=4_000_000, amount_minor=24000000,
             occurred_at=_dt(5))  # sold 4 g for 240,000
    s.commit()
    st = holding_state(s, plan.holding)
    assert st["qty_held_micro"] == 6_000_000
    # realized = 240,000 - avg(50,000)*4 = 240,000 - 200,000 = 40,000
    assert st["realized_gain_minor"] == 4000000


def test_oversell_rejected(ctx):
    s, u = ctx
    plan = _gold(s, u)
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=2_000_000, amount_minor=10000000,
            occurred_at=_dt(1))
    with pytest.raises(ValidationError):
        add_sell(s, plan=plan, user_id=u.id, quantity_micro=3_000_000, amount_minor=18000000,
                 occurred_at=_dt(2))


def test_unvalued_has_null_value(ctx):
    s, u = ctx
    plan = _gold(s, u)
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=1_000_000, amount_minor=5000000,
            occurred_at=_dt(1))
    s.commit()
    st = holding_state(s, plan.holding)
    assert st["current_value_minor"] is None
    assert st["unrealized_gain_minor"] is None


def test_invalid_asset_class_rejected(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_holding_plan(s, owner_id=u.id, name="X", currency="INR",
                            asset_class="crypto", unit="coin")
