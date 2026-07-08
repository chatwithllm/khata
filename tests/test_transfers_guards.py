from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, LedgerEntry, TransferHop
from khata.services.assets import create_asset_plan, asset_state
from khata.services import transfers
from khata.services.transfers import TransferValidationError


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
        h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                                  from_user_id=b2.id, to_user_id=b1.id,
                                  amount_minor=1000000, occurred_at=_dt(1), method="transfer")
        s.commit()
        yield s, b1, b2, plan, h1


def test_cannot_delete_consumed_hop(ctx):
    s, b1, b2, plan, h1 = ctx
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=900000, occurred_at=_dt(5), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    with pytest.raises(TransferValidationError):
        transfers.delete_hop(s, plan=plan, hop_id=h1.id, acting_user_id=b2.id)


def test_delete_terminal_removes_spawned_entries(ctx):
    s, b1, b2, plan, h1 = ctx
    hT = transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                              from_user_id=b1.id, to_name="Seller",
                              amount_minor=900000, occurred_at=_dt(5), method="transfer",
                              is_terminal=True,
                              sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    assert s.query(LedgerEntry).filter_by(source_hop_id=hT.id).count() == 1
    transfers.delete_hop(s, plan=plan, hop_id=hT.id, acting_user_id=b1.id)
    assert s.query(LedgerEntry).filter_by(source_hop_id=hT.id).count() == 0
    assert transfers.outstanding(s, h1) == 1000000    # freed back up


def test_cannot_shrink_amount_below_consumed(ctx):
    s, b1, b2, plan, h1 = ctx
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=900000, occurred_at=_dt(5), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    with pytest.raises(TransferValidationError):
        transfers.update_hop(s, plan=plan, hop_id=h1.id, acting_user_id=b2.id,
                             amount_minor=800000)


def test_return_resolution_closes_outstanding(ctx):
    s, b1, b2, plan, h1 = ctx
    r = transfers.resolve_remainder(s, plan=plan, hop_id=h1.id, acting_user_id=b1.id,
                                    action="return", occurred_at=_dt(9))
    assert r.resolution == "returned"
    assert r.amount_minor == 1000000
    assert r.to_user_id == b2.id            # back to origin party
    assert transfers.outstanding(s, h1) == 0
    assert asset_state(s, plan)["paid_to_date_minor"] == 0


def test_fee_resolution_creates_flagged_entry_not_counted_in_paid(ctx):
    s, b1, b2, plan, h1 = ctx
    transfers.resolve_remainder(s, plan=plan, hop_id=h1.id, acting_user_id=b1.id,
                                action="fee", occurred_at=_dt(9), amount_minor=50000,
                                note="agent commission")
    fee_entries = s.query(LedgerEntry).filter_by(kind="transfer_fee").all()
    assert len(fee_entries) == 1
    assert fee_entries[0].logged_by_user_id == b2.id      # ultimate origin pays the fee
    assert fee_entries[0].amount_minor == 50000
    st = asset_state(s, plan)
    assert st["paid_to_date_minor"] == 0                  # fee never counts as paid
    assert st["fees_minor"] == 50000
    assert transfers.outstanding(s, h1) == 950000
