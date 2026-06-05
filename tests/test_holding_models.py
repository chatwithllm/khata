import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, Holding, LedgerEntry


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_holding_persists_and_relationship():
    s = _session()
    u = User(email="a@b.com", display_name="A", password_hash="x")
    s.add(u)
    s.flush()
    plan = Plan(owner_user_id=u.id, type="holding", name="Gold 22K", currency="INR")
    s.add(plan)
    s.flush()
    s.add(Holding(plan_id=plan.id, asset_class="gold", unit="gram",
                  symbol=None, purity="22K"))
    s.commit()

    got = s.get(Plan, plan.id)
    assert got.holding.asset_class == "gold"
    assert got.holding.unit == "gram"
    assert got.holding.purity == "22K"
    assert got.holding.current_price_minor is None


def test_quantity_micro_on_ledger_and_cascade():
    s = _session()
    u = User(email="a@b.com", display_name="A", password_hash="x")
    s.add(u)
    s.flush()
    plan = Plan(owner_user_id=u.id, type="holding", name="Gold", currency="INR")
    s.add(plan)
    s.flush()
    s.add(Holding(plan_id=plan.id, asset_class="gold", unit="gram"))
    from datetime import datetime, timezone
    s.add(LedgerEntry(plan_id=plan.id, logged_by_user_id=u.id, kind="buy", direction="out",
                      amount_minor=50000000, currency="INR",
                      occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                      quantity_micro=92_500_000))
    s.commit()

    e = s.get(Plan, plan.id).ledger_entries[0]
    assert e.quantity_micro == 92_500_000

    # cascade: deleting the plan removes the holding
    pid = plan.id
    s.delete(s.get(Plan, pid))
    s.commit()
    assert s.get(Holding, pid) is None
