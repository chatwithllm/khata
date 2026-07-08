from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, TransferHop
from khata.services.assets import create_asset_plan
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
        s.commit()
        yield s, b1, b2, plan


def _hop(s, plan, **kw):
    base = dict(logged_by_user_id=kw.get("logged_by_user_id"),
                amount_minor=1000000, occurred_at=_dt(), method="transfer")
    base.update(kw)
    return transfers.create_hop(s, plan=plan, **base)


def test_root_hop_gets_own_chain_and_own_funds_source(ctx):
    s, b1, b2, plan = ctx
    h = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_user_id=b1.id)
    assert h.chain_id == h.id
    assert len(h.sources) == 1
    assert h.sources[0].source_hop_id is None
    assert h.sources[0].amount_minor == 1000000


def test_receipt_pending_only_for_other_user_receiver(ctx):
    s, b1, b2, plan = ctx
    to_user = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_user_id=b1.id)
    to_name = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_name="Agent")
    to_self = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b1.id, to_user_id=b2.id)
    assert to_user.receipt_status == "pending"
    assert to_name.receipt_status == "agreed"
    assert to_self.receipt_status == "agreed"


def test_exactly_one_party_per_side(ctx):
    s, b1, b2, plan = ctx
    with pytest.raises(TransferValidationError):
        _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id)   # no to-party
    with pytest.raises(TransferValidationError):
        _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id,
             to_user_id=b1.id, to_name="also a name")                 # two to-parties


def test_consuming_hop_joins_chain_and_outstanding_drops(ctx):
    s, b1, b2, plan = ctx
    h1 = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_user_id=b1.id)
    h2 = _hop(s, plan, logged_by_user_id=b1.id, from_user_id=b1.id, to_name="Seller",
              amount_minor=900000, is_terminal=True,
              sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    assert h2.chain_id == h1.chain_id
    assert transfers.outstanding(s, h1) == 100000
    assert transfers.outstanding(s, h2) == 0     # terminal = delivered, nothing to consume


def test_cannot_overconsume_source(ctx):
    s, b1, b2, plan = ctx
    h1 = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_user_id=b1.id)
    with pytest.raises(TransferValidationError):
        _hop(s, plan, logged_by_user_id=b1.id, from_user_id=b1.id, to_name="Seller",
             amount_minor=1100000, is_terminal=True,
             sources=[{"source_hop_id": h1.id, "amount_minor": 1100000}])


def test_sources_must_sum_to_amount(ctx):
    s, b1, b2, plan = ctx
    h1 = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_user_id=b1.id)
    with pytest.raises(TransferValidationError):
        _hop(s, plan, logged_by_user_id=b1.id, from_user_id=b1.id, to_name="Seller",
             amount_minor=2000000, is_terminal=True,
             sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
