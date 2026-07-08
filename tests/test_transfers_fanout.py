from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, LedgerEntry
from khata.services.assets import create_asset_plan, asset_state
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
        b3 = User(email="b3@x.com", display_name="B3", password_hash="x")
        s.add_all([b1, b2, b3]); s.flush()
        plan = create_asset_plan(s, owner_id=b1.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        s.commit()
        yield s, b1, b2, b3, plan


def test_merged_terminal_fans_out_per_contributor(ctx):
    s, b1, b2, b3, plan = ctx
    # b2 sends 10k to b1 (in transit)
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=1000000, occurred_at=_dt(1), method="transfer")
    # b1 pays seller 20k: 10k from h1 + 10k own
    h2 = transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                              from_user_id=b1.id, to_name="Seller",
                              amount_minor=2000000, occurred_at=_dt(5), method="transfer",
                              is_terminal=True,
                              sources=[{"source_hop_id": h1.id, "amount_minor": 1000000},
                                       {"source_hop_id": None, "amount_minor": 1000000}])
    entries = s.query(LedgerEntry).filter_by(source_hop_id=h2.id).all()
    by_user = {e.logged_by_user_id: e.amount_minor for e in entries}
    assert by_user == {b2.id: 1000000, b1.id: 1000000}
    st = asset_state(s, plan)
    assert st["paid_to_date_minor"] == 2000000
    # b2's entry attributed by b1 -> needs b2's confirmation (existing machinery)
    e_b2 = next(e for e in entries if e.logged_by_user_id == b2.id)
    assert e_b2.amount_status == "pending"


def test_partial_forward_counts_only_delivered(ctx):
    s, b1, b2, b3, plan = ctx
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=1000000, occurred_at=_dt(1), method="transfer")
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=900000, occurred_at=_dt(5), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    st = asset_state(s, plan)
    assert st["paid_to_date_minor"] == 900000
    assert transfers.outstanding(s, h1) == 100000


def test_multilevel_chain_walks_to_ultimate_origin(ctx):
    s, b1, b2, b3, plan = ctx
    # b3 -> b2 600, b2 adds 400 own and sends 1000 -> b1, b1 sends 900 -> seller
    hA = transfers.create_hop(s, plan=plan, logged_by_user_id=b3.id,
                              from_user_id=b3.id, to_user_id=b2.id,
                              amount_minor=600, occurred_at=_dt(1), method="upi")
    hB = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=1000, occurred_at=_dt(2), method="upi",
                              sources=[{"source_hop_id": hA.id, "amount_minor": 600},
                                       {"source_hop_id": None, "amount_minor": 400}])
    hT = transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                              from_user_id=b1.id, to_name="Seller",
                              amount_minor=900, occurred_at=_dt(3), method="upi",
                              is_terminal=True,
                              sources=[{"source_hop_id": hB.id, "amount_minor": 900}])
    entries = s.query(LedgerEntry).filter_by(source_hop_id=hT.id).all()
    by_user = {e.logged_by_user_id: e.amount_minor for e in entries}
    # greedy oldest-first: 900 from hB = 600 (b3's lineage) + 300 of b2's own 400
    assert by_user == {b3.id: 600, b2.id: 300}


def test_contact_origin_attributed_to_logger(ctx):
    s, b1, b2, b3, plan = ctx
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                              from_name="Uncle", to_user_id=b1.id,
                              amount_minor=500, occurred_at=_dt(1), method="cash")
    hT = transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                              from_user_id=b1.id, to_name="Seller",
                              amount_minor=500, occurred_at=_dt(2), method="cash",
                              is_terminal=True,
                              sources=[{"source_hop_id": h1.id, "amount_minor": 500}])
    entries = s.query(LedgerEntry).filter_by(source_hop_id=hT.id).all()
    assert len(entries) == 1
    assert entries[0].logged_by_user_id == b1.id      # logger stands in for non-user origin
    assert entries[0].amount_minor == 500
