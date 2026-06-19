import pytest
from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Attachment
from khata.services import contacts as c, attachments as att

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000154a24f9f0000000049454e44ae426082")

@pytest.fixture
def ctx():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    S = make_session_factory(e)
    with S() as s:
        u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
        yield s, u

def test_add_list_contact_attachment(ctx):
    s, u = ctx
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    a = att.add_attachment(s, contact=ct, uploaded_by=u.id, filename="id.png", raw=PNG)
    s.flush()
    assert a.contact_id == ct.id and a.ledger_entry_id is None and a.mime == "image/png"
    rows = att.list_for_contact(s, ct.id)
    assert len(rows) == 1 and rows[0].id == a.id

def test_requires_exactly_one_parent(ctx):
    s, u = ctx
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    with pytest.raises(att.AttachmentError):
        att.add_attachment(s, uploaded_by=u.id, filename="x.png", raw=PNG)  # no parent

def test_delete_contact_cascades_attachments(ctx):
    s, u = ctx
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    a = att.add_attachment(s, contact=ct, uploaded_by=u.id, filename="id.png", raw=PNG)
    s.commit()
    c.delete_contact(s, owner_id=u.id, contact_id=ct.id); s.commit()
    assert s.get(Attachment, a.id) is None
