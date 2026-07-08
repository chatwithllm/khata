from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, TransferHop, HopSource, LedgerEntry
from khata.services.assets import create_asset_plan


def _dt():
    return datetime(2026, 7, 1, tzinfo=timezone.utc)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u1 = User(email="a@b.com", display_name="B1", password_hash="x")
        u2 = User(email="c@d.com", display_name="B2", password_hash="x")
        s.add_all([u1, u2]); s.flush()
        plan = create_asset_plan(s, owner_id=u1.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        s.commit()
        yield s, u1, u2, plan


def test_hop_roundtrip(ctx):
    s, u1, u2, plan = ctx
    hop = TransferHop(plan_id=plan.id, from_user_id=u2.id, to_user_id=u1.id,
                      amount_minor=1000000, currency="INR", occurred_at=_dt(),
                      method="transfer", logged_by_user_id=u2.id,
                      receipt_status="pending")
    s.add(hop); s.flush()
    hop.chain_id = hop.id
    s.flush()
    got = s.get(TransferHop, hop.id)
    assert got.chain_id == hop.id
    assert got.is_terminal is False
    assert got.resolution is None
    assert got.sources == []


def test_hop_source_links(ctx):
    s, u1, u2, plan = ctx
    h1 = TransferHop(plan_id=plan.id, from_user_id=u2.id, to_user_id=u1.id,
                     amount_minor=1000000, currency="INR", occurred_at=_dt(),
                     method="transfer", logged_by_user_id=u2.id)
    s.add(h1); s.flush(); h1.chain_id = h1.id
    h2 = TransferHop(plan_id=plan.id, from_user_id=u1.id, to_name="Seller",
                     amount_minor=900000, currency="INR", occurred_at=_dt(),
                     method="transfer", logged_by_user_id=u1.id,
                     chain_id=h1.id, is_terminal=True)
    s.add(h2); s.flush()
    s.add(HopSource(hop_id=h2.id, source_hop_id=h1.id, amount_minor=900000))
    s.flush()
    assert h2.sources[0].source_hop_id == h1.id
    assert h1.consumers[0].hop_id == h2.id


def test_ledger_entry_source_hop(ctx):
    s, u1, u2, plan = ctx
    h = TransferHop(plan_id=plan.id, from_user_id=u1.id, to_name="Seller",
                    amount_minor=100, currency="INR", occurred_at=_dt(),
                    method="cash", logged_by_user_id=u1.id, is_terminal=True)
    s.add(h); s.flush(); h.chain_id = h.id
    e = LedgerEntry(plan_id=plan.id, logged_by_user_id=u1.id, direction="out",
                    amount_minor=100, currency="INR", occurred_at=_dt(),
                    source_hop_id=h.id)
    s.add(e); s.flush()
    assert s.get(LedgerEntry, e.id).source_hop_id == h.id
