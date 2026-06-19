from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.loans import create_loan_plan
from khata.services import contacts as c


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="a@b.com", display_name="Arjun", password_hash="x")
        o = User(email="z@z.com", display_name="Other", password_hash="x")
        s.add_all([u, o]); s.flush()
        yield s, u, o


def test_create_and_get(ctx):
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="Karunakar", phone="+91 99", email="k@x.com")
    s.flush()
    assert ct.id and ct.name == "Karunakar" and ct.owner_user_id == u.id
    got = c.get_contact(s, owner_id=u.id, contact_id=ct.id)
    assert got.id == ct.id


def test_name_required(ctx):
    s, u, o = ctx
    with pytest.raises(c.ContactError):
        c.create_contact(s, owner_id=u.id, name="  ")


def test_owner_scoping(ctx):
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    assert c.get_contact(s, owner_id=o.id, contact_id=ct.id) is None
    assert [x.id for x in c.list_contacts(s, owner_id=o.id)] == []
    with pytest.raises(c.ContactError):
        c.update_contact(s, owner_id=o.id, contact_id=ct.id, name="hack")


def test_assign_loan_links_and_unlinks(ctx):
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    plan = create_loan_plan(s, owner_id=u.id, name="L1", currency="INR",
                            direction="given", interest_type="monthly", rate_bps=200,
                            start_date=date(2024, 1, 1)); s.flush()
    c.assign_loan(s, owner_id=u.id, plan=plan, contact_id=ct.id); s.flush()
    assert plan.loan.contact_id == ct.id
    c.assign_loan(s, owner_id=u.id, plan=plan, contact_id=None); s.flush()
    assert plan.loan.contact_id is None


def test_assign_rejects_foreign_contact(ctx):
    s, u, o = ctx
    foreign = c.create_contact(s, owner_id=o.id, name="X"); s.flush()
    plan = create_loan_plan(s, owner_id=u.id, name="L", currency="INR",
                            direction="given", interest_type="none", rate_bps=0,
                            start_date=date(2024, 1, 1)); s.flush()
    with pytest.raises(c.ContactError):
        c.assign_loan(s, owner_id=u.id, plan=plan, contact_id=foreign.id)


def test_delete_unlinks_loans(ctx):
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    plan = create_loan_plan(s, owner_id=u.id, name="L", currency="INR",
                            direction="given", interest_type="none", rate_bps=0,
                            start_date=date(2024, 1, 1)); s.flush()
    c.assign_loan(s, owner_id=u.id, plan=plan, contact_id=ct.id); s.flush()
    c.delete_contact(s, owner_id=u.id, contact_id=ct.id); s.commit()
    s.expire_all()
    assert plan.loan.contact_id is None
