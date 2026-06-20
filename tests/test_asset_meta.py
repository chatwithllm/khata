import json
import pytest
from datetime import datetime, timezone
from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services import assets, contacts as c, attachments as att

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000154a24f9f0000000049454e44ae426082")


@pytest.fixture
def ctx():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    S = make_session_factory(e)
    with S() as s:
        u = User(email="a@b.com", display_name="A", password_hash="x")
        o = User(email="z@z.com", display_name="O", password_hash="x")
        s.add_all([u, o]); s.flush()
        yield s, u, o


def _asset(s, u, name="1 Acre", price=17500000):
    return assets.create_asset_plan(s, owner_id=u.id, name=name, currency="INR",
                                    total_price_minor=price)


def test_meta_seller_buyer_text_and_contact(ctx):
    s, u, o = ctx
    plan = _asset(s, u); s.flush()
    ct = c.create_contact(s, owner_id=u.id, name="Ramesh"); s.flush()
    assets.update_asset_meta(s, plan=plan, owner_id=u.id, seller_name="Ramesh",
                             seller_contact_id=ct.id, buyer_name="Me")
    s.flush()
    st = assets.asset_state(s, plan)
    assert st["seller"]["name"] == "Ramesh" and st["seller"]["contact_id"] == ct.id
    assert st["seller"]["contact_name"] == "Ramesh"
    assert st["buyer"]["name"] == "Me" and st["buyer"]["contact_id"] is None


def test_meta_rejects_foreign_contact(ctx):
    s, u, o = ctx
    plan = _asset(s, u); foreign = c.create_contact(s, owner_id=o.id, name="X"); s.flush()
    with pytest.raises(assets.PlanError):
        assets.update_asset_meta(s, plan=plan, owner_id=u.id, seller_contact_id=foreign.id)


def test_extra_fields_and_links_roundtrip(ctx):
    s, u, o = ctx
    plan = _asset(s, u); s.flush()
    assets.update_asset_meta(s, plan=plan, owner_id=u.id,
        extra_fields=[{"label":"Survey No","value":"123"}, {"label":"  ","value":"drop me"}],
        links=[{"label":"Walkthrough","url":"https://youtu.be/x","video":True}])
    s.flush()
    st = assets.asset_state(s, plan)
    assert st["extra_fields"] == [{"label":"Survey No","value":"123"}]   # blank-label dropped
    assert st["links"][0]["url"] == "https://youtu.be/x" and st["links"][0]["video"] is True


def test_links_reject_bad_scheme(ctx):
    s, u, o = ctx
    plan = _asset(s, u); s.flush()
    with pytest.raises(assets.PlanError):
        assets.update_asset_meta(s, plan=plan, owner_id=u.id,
                                 links=[{"label":"x","url":"javascript:alert(1)"}])


def test_asset_attachment_three_parents(ctx):
    s, u, o = ctx
    plan = _asset(s, u); s.flush()
    a = att.add_attachment(s, asset_plan=plan, uploaded_by=u.id, filename="deed.png", raw=PNG)
    s.flush()
    assert a.asset_plan_id == plan.id and a.ledger_entry_id is None and a.contact_id is None
    assert [x.id for x in att.list_for_asset(s, plan.id)] == [a.id]
    with pytest.raises(att.AttachmentError):
        att.add_attachment(s, uploaded_by=u.id, filename="x.png", raw=PNG)
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    with pytest.raises(att.AttachmentError):
        att.add_attachment(s, asset_plan=plan, contact=ct, uploaded_by=u.id, filename="x.png", raw=PNG)


def test_delete_asset_cascades_attachments(ctx):
    s, u, o = ctx
    plan = _asset(s, u); s.flush()
    a = att.add_attachment(s, asset_plan=plan, uploaded_by=u.id, filename="d.png", raw=PNG)
    s.commit()
    from khata.models import Attachment, Plan
    s.delete(s.get(Plan, plan.id)); s.commit()
    assert s.get(Attachment, a.id) is None
