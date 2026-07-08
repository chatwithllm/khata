from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.assets import create_asset_plan
from khata.services import attachments, transfers
from khata.services.attachments import AttachmentError

# smallest valid PNG (magic bytes pass _sniff)
PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


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
        hop = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                                   from_user_id=b2.id, to_user_id=b1.id,
                                   amount_minor=1000000, occurred_at=_dt(), method="transfer")
        s.commit()
        yield s, b1, b2, plan, hop


def test_attach_to_hop_roundtrip(ctx):
    s, b1, b2, plan, hop = ctx
    att = attachments.add_attachment(s, uploaded_by=b2.id, filename="receipt.png",
                                     raw=PNG, hop=hop)
    assert att.hop_id == hop.id
    assert attachments.list_for_hop(s, hop.id)[0].id == att.id
    assert hop.attachments[0].id == att.id


def test_exactly_one_parent_still_enforced(ctx):
    s, b1, b2, plan, hop = ctx
    from khata.services.assets import log_payment
    entry = log_payment(s, plan=plan, user_id=b1.id, amount_minor=100,
                        occurred_at=_dt(), method="cash", funding_source="savings",
                        acting_user_id=b1.id)
    with pytest.raises(AttachmentError):
        attachments.add_attachment(s, uploaded_by=b1.id, filename="x.png",
                                   raw=PNG, hop=hop, entry=entry)


def test_plan_transfers_reports_attachments(ctx):
    s, b1, b2, plan, hop = ctx
    st = transfers.plan_transfers(s, plan)
    row = st["chains"][0]["hops"][0]
    assert row["attachment_count"] == 0
    assert row["has_proof"] is False
    attachments.add_attachment(s, uploaded_by=b2.id, filename="receipt.png",
                               raw=PNG, hop=hop)
    st = transfers.plan_transfers(s, plan)
    row = st["chains"][0]["hops"][0]
    assert row["attachment_count"] == 1
    assert row["has_proof"] is True
