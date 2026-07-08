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
        b1 = User(email="b1@x.com", display_name="B1", password_hash="x")
        b2 = User(email="b2@x.com", display_name="B2", password_hash="x")
        s.add_all([b1, b2]); s.flush()
        plan = create_asset_plan(s, owner_id=b1.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        s.commit()
        yield s, b1, b2, plan


def test_plan_transfers_summary(ctx):
    s, b1, b2, plan = ctx
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=1000000, occurred_at=_dt(1), method="transfer")
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=900000, occurred_at=_dt(5), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    st = transfers.plan_transfers(s, plan)
    assert st["in_transit_minor"] == 100000
    assert len(st["chains"]) == 1
    ch = st["chains"][0]
    assert ch["chain_id"] == h1.chain_id
    assert ch["closed"] is False
    assert [h["amount_minor"] for h in ch["hops"]] == [1000000, 900000]
    assert ch["hops"][0]["from"]["display"] == "B2"
    assert ch["hops"][0]["outstanding_minor"] == 100000
    assert ch["hops"][1]["is_terminal"] is True


def test_closed_chain_flag(ctx):
    s, b1, b2, plan = ctx
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=500, occurred_at=_dt(1), method="cash")
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=500, occurred_at=_dt(2), method="cash",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 500}])
    st = transfers.plan_transfers(s, plan)
    assert st["in_transit_minor"] == 0
    assert st["chains"][0]["closed"] is True
