from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.assets import create_asset_plan, asset_state, log_payment, respond_amount
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


def test_asset_state_splits_agreed_vs_pending(ctx):
    s, b1, b2, plan = ctx
    # owner logs own entry (agreed) + attributes one to b2 (pending)
    log_payment(s, plan=plan, user_id=b1.id, amount_minor=1000, occurred_at=_dt(),
                method="cash", funding_source="savings", acting_user_id=b1.id)
    log_payment(s, plan=plan, user_id=b2.id, amount_minor=500, occurred_at=_dt(),
                method="cash", funding_source="savings", acting_user_id=b1.id)
    st = asset_state(s, plan)
    assert st["paid_to_date_minor"] == 1500
    assert st["paid_agreed_minor"] == 1000
    assert st["paid_pending_minor"] == 500
    by_uid = {c["user_id"]: c for c in st["contributors"]}
    assert by_uid[b1.id]["agreed_minor"] == 1000
    assert by_uid[b1.id]["pending_minor"] == 0
    assert by_uid[b2.id]["agreed_minor"] == 0
    assert by_uid[b2.id]["pending_minor"] == 500


def test_in_transit_by_contributor(ctx):
    s, b1, b2, plan = ctx
    # b2 sends 1500 to b1; b1 forwards 900 to seller — 600 of b2's money still in transit
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=1500, occurred_at=_dt(1), method="transfer")
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=900, occurred_at=_dt(2), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 900}])
    st = transfers.plan_transfers(s, plan)
    assert st["in_transit_minor"] == 600
    rows = {r["user_id"]: r["amount_minor"] for r in st["in_transit_by_contributor"]}
    assert rows == {b2.id: 600}


def test_in_transit_multi_origin(ctx):
    s, b1, b2, plan = ctx
    # b2 600 -> b1; b1 relays 1000 (600 b2 + 400 own) -> b2 holds... use free-text holder
    hA = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=600, occurred_at=_dt(1), method="upi")
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Middleman",
                         amount_minor=1000, occurred_at=_dt(2), method="upi",
                         sources=[{"source_hop_id": hA.id, "amount_minor": 600},
                                  {"source_hop_id": None, "amount_minor": 400}])
    st = transfers.plan_transfers(s, plan)
    # hA fully consumed; middleman hop outstanding 1000 = 600 b2 + 400 b1
    assert st["in_transit_minor"] == 1000
    rows = {r["user_id"]: r["amount_minor"] for r in st["in_transit_by_contributor"]}
    assert rows == {b2.id: 600, b1.id: 400}
