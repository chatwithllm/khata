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
