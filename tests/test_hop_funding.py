from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.assets import create_asset_plan
from khata.services import transfers


def _dt(day=1):
    return datetime(2026, 7, day, tzinfo=timezone.utc)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="u@x.com", display_name="U", password_hash="x")
        s.add(u); s.flush()
        loan = create_asset_plan(s, owner_id=u.id, name="Car loan",
                                 currency="INR", total_price_minor=10000000)
        loan.type = "loan"
        plan = create_asset_plan(s, owner_id=u.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        s.commit()
        yield s, u, plan, loan


def test_hop_stores_funding_columns(ctx):
    s, u, plan, loan = ctx
    from khata.models import TransferHop
    # Pure model test — Task 1 is schema-only; create_hop wiring lands in Task 2.
    hop = TransferHop(
        plan_id=plan.id, from_user_id=u.id, to_name="Middleman",
        amount_minor=200000, currency="INR", occurred_at=_dt(),
        method="transfer", logged_by_user_id=u.id,
        funding_source="loan", funding_plan_id=loan.id)
    s.add(hop); s.flush()
    fresh = s.get(TransferHop, hop.id)
    assert fresh.funding_source == "loan"
    assert fresh.funding_plan_id == loan.id


def test_create_hop_rejects_bad_funding_source(ctx):
    s, u, plan, loan = ctx
    with pytest.raises(transfers.TransferValidationError):
        transfers.create_hop(
            s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id,
            to_name="M", amount_minor=1000, occurred_at=_dt(),
            method="transfer", funding_source="not_a_source")


def test_update_hop_sets_and_clears_funding(ctx):
    s, u, plan, loan = ctx
    hop = transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id,
        to_name="M", amount_minor=1000, occurred_at=_dt(), method="transfer")
    s.commit()
    assert hop.funding_source is None
    transfers.update_hop(s, plan=plan, hop_id=hop.id, acting_user_id=u.id,
                         funding_source="loan", funding_plan_id=loan.id)
    s.commit()
    assert hop.funding_source == "loan"
    assert hop.funding_plan_id == loan.id
    # explicit clear
    transfers.update_hop(s, plan=plan, hop_id=hop.id, acting_user_id=u.id,
                         funding_source=None, funding_plan_id=None)
    s.commit()
    assert hop.funding_source is None
    assert hop.funding_plan_id is None


def test_update_hop_without_funding_kwargs_leaves_it(ctx):
    s, u, plan, loan = ctx
    hop = transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id,
        to_name="M", amount_minor=1000, occurred_at=_dt(), method="transfer",
        funding_source="savings")
    s.commit()
    transfers.update_hop(s, plan=plan, hop_id=hop.id, acting_user_id=u.id,
                         method="upi")
    s.commit()
    assert hop.funding_source == "savings"   # untouched when kwarg omitted


def test_fanout_splits_per_funding_source(ctx):
    s, u, plan, loan = ctx
    from khata.models import LedgerEntry
    from sqlalchemy import select
    # u sends two origin hops to a middleman: one loan-funded, one savings-funded
    h_loan = transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id, to_name="Mid",
        amount_minor=200000, occurred_at=_dt(1), method="transfer",
        funding_source="loan", funding_plan_id=loan.id)
    h_sav = transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id, to_name="Mid",
        amount_minor=100000, occurred_at=_dt(2), method="transfer",
        funding_source="savings")
    # middleman (still u for test simplicity) forwards all 300000 to the seller
    transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_name="Mid", to_name="Seller",
        amount_minor=300000, occurred_at=_dt(3), method="transfer", is_terminal=True,
        sources=[{"source_hop_id": h_loan.id, "amount_minor": 200000},
                 {"source_hop_id": h_sav.id, "amount_minor": 100000}])
    s.commit()
    entries = s.scalars(select(LedgerEntry).where(LedgerEntry.plan_id == plan.id)).all()
    by = {(e.funding_source, e.funding_plan_id): e.amount_minor for e in entries}
    assert by[("loan", loan.id)] == 200000
    assert by[("savings", None)] == 100000
    assert len(entries) == 2
