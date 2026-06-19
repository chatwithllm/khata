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


def test_contact_state_per_currency_and_base(ctx):
    from khata.services.loans import add_disbursement
    from khata.services import fx
    s, u, o = ctx
    # seed an INR<->USD rate so the base total is meaningful (1 USD = 83 INR)
    fx.set_rate(s, base="USD", quote="INR", rate_micro=83_000_000, as_of=None)
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    for nm, ccy, amt in [("A", "INR", 100000), ("B", "INR", 50000), ("C", "USD", 2000)]:
        p = create_loan_plan(s, owner_id=u.id, name=nm, currency=ccy, direction="given",
                             interest_type="none", rate_bps=0, start_date=date(2024,1,1))
        add_disbursement(s, plan=p, user_id=u.id, amount_minor=amt,
                         occurred_at=datetime(2024,1,1,tzinfo=timezone.utc))
        c.assign_loan(s, owner_id=u.id, plan=p, contact_id=ct.id)
    s.flush()
    st = c.contact_state(s, ct, base_currency="INR")
    by = {r["currency"]: r for r in st["by_currency"]}
    assert by["INR"]["loan_count"] == 2 and by["INR"]["principal_outstanding_minor"] == 150000
    assert by["USD"]["loan_count"] == 1 and by["USD"]["principal_outstanding_minor"] == 2000
    assert st["loan_count"] == 3 and st["given_count"] == 3 and st["taken_count"] == 0
    assert st["base_currency"] == "INR"
    # base total = 150000 INR + 2000 USD*83 = 150000 + 166000 = 316000
    assert st["base_total"]["principal_outstanding_minor"] == 316000
    assert len(st["loans"]) == 3


def test_contact_state_empty(ctx):
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    st = c.contact_state(s, ct, base_currency="INR")
    assert st["loan_count"] == 0 and st["by_currency"] == [] and st["loans"] == []
    assert st["base_total"]["principal_outstanding_minor"] == 0


def test_contact_state_partial_flag_when_rate_missing(ctx):
    # USD loan with no USD→INR rate seeded → bucket is skipped, partial=True.
    # Only INR and USD are SUPPORTED_CURRENCIES, so we use USD as the
    # foreign currency and deliberately omit fx.set_rate to exercise the
    # missing-rate branch in contact_state.
    from khata.services.loans import add_disbursement
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    p = create_loan_plan(s, owner_id=u.id, name="E", currency="USD", direction="given",
                         interest_type="none", rate_bps=0, start_date=date(2024, 1, 1))
    add_disbursement(s, plan=p, user_id=u.id, amount_minor=5000,
                     occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    c.assign_loan(s, owner_id=u.id, plan=p, contact_id=ct.id)
    s.flush()
    st = c.contact_state(s, ct, base_currency="INR")
    assert st["base_total_partial"] is True
    assert st["base_total"]["principal_outstanding_minor"] == 0
