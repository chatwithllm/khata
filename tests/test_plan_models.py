from datetime import datetime, timezone

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, AssetPurchase, Installment, LedgerEntry


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_plan_with_asset_installments_and_ledger():
    s = _session()
    u = User(email="a@b.com", display_name="Arjun", password_hash="x")
    s.add(u)
    s.flush()
    plan = Plan(owner_user_id=u.id, type="asset", name="Plot", currency="INR")
    s.add(plan)
    s.flush()
    s.add(AssetPurchase(plan_id=plan.id, total_price_minor=200000000))
    s.add(Installment(plan_id=plan.id, seq=1, planned_amount_minor=25000000))
    s.add(LedgerEntry(plan_id=plan.id, logged_by_user_id=u.id, direction="out",
                      amount_minor=25000000, currency="INR",
                      occurred_at=datetime.now(timezone.utc),
                      method="transfer", funding_source="savings"))
    s.commit()

    got = s.get(Plan, plan.id)
    assert got.asset.total_price_minor == 200000000
    assert len(got.installments) == 1
    assert len(got.ledger_entries) == 1
    assert got.ledger_entries[0].method == "transfer"
