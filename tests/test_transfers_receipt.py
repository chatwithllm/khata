from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.assets import create_asset_plan
from khata.services import transfers
from khata.services.transfers import TransferValidationError


def _dt():
    return datetime(2026, 7, 1, tzinfo=timezone.utc)


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
        h = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                                 from_user_id=b2.id, to_user_id=b1.id,
                                 amount_minor=1000000, occurred_at=_dt(), method="transfer")
        s.commit()
        yield s, b1, b2, plan, h


def test_receiver_confirms(ctx):
    s, b1, b2, plan, h = ctx
    transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b1.id, action="confirm")
    assert h.receipt_status == "agreed"


def test_stranger_cannot_confirm(ctx):
    s, b1, b2, plan, h = ctx
    with pytest.raises(TransferValidationError):
        transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b2.id, action="confirm")


def test_counter_then_accept_updates_amount(ctx):
    s, b1, b2, plan, h = ctx
    transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b1.id,
                              action="counter", amount_minor=900000)
    assert h.receipt_status == "countered"
    assert h.counter_amount_minor == 900000
    assert h.amount_minor == 1000000
    transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b2.id, action="accept")
    assert h.amount_minor == 900000
    assert h.receipt_status == "agreed"


def test_accept_blocked_if_counter_below_consumed(ctx):
    s, b1, b2, plan, h = ctx
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=950000, occurred_at=_dt(), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h.id, "amount_minor": 950000}])
    transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b1.id,
                              action="counter", amount_minor=900000)
    with pytest.raises(TransferValidationError):
        transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b2.id, action="accept")


def test_pending_receipt_listed_for_receiver(ctx):
    s, b1, b2, plan, h = ctx
    rows = transfers.list_receipt_confirmations(s, b1.id)
    assert any(r["hop_id"] == h.id for r in rows)
    assert transfers.list_receipt_confirmations(s, b2.id) == []
