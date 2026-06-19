from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.loans import create_loan_plan, add_disbursement
from khata.services import contacts as c, fx
from khata.services.loan_groups import grouped_loans


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="a@b.com", display_name="A", password_hash="x")
        o = User(email="z@z.com", display_name="O", password_hash="x")
        s.add_all([u, o]); s.flush()
        yield s, u, o


def _loan(s, u, name, ccy, direction, principal, rate_bps=300, counterparty=None,
          contact_id=None):
    p = create_loan_plan(s, owner_id=u.id, name=name, currency=ccy, direction=direction,
                         interest_type="monthly", rate_bps=rate_bps,
                         start_date=date(2024, 1, 1), counterparty=counterparty)
    add_disbursement(s, plan=p, user_id=u.id, amount_minor=principal,
                     occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    if contact_id is not None:
        c.assign_loan(s, owner_id=u.id, plan=p, contact_id=contact_id)
    s.flush()
    return p


def test_groups_by_contact_then_counterparty_merge(ctx):
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="Sunil"); s.flush()
    _loan(s, u, "L1", "INR", "given", 100000, contact_id=ct.id)
    _loan(s, u, "L2", "INR", "given", 50000, counterparty="sunil")
    _loan(s, u, "L3", "INR", "taken", 30000, counterparty="Bank")
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    by = {g["name"].lower(): g for g in out["groups"]}
    assert "sunil" in by
    sunil = by["sunil"]
    assert sunil["given"]["count"] == 2 and sunil["given"]["principal_minor"] == 150000
    assert sunil["contact_id"] == ct.id
    assert "bank" in by and by["bank"]["taken"]["count"] == 1


def test_per_side_sums_interest_and_next_due(ctx):
    s, u, o = ctx
    _loan(s, u, "L", "INR", "given", 200000, rate_bps=300, counterparty="K")
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    g = out["groups"][0]["given"]
    assert g["principal_minor"] == 200000
    assert g["interest_monthly_minor"] == 6000
    assert g["next_due_minor"] == g["interest_monthly_minor"]


def test_multi_currency_base_conversion_and_partial(ctx):
    s, u, o = ctx
    fx.set_rate(s, base="USD", quote="INR", rate_micro=83_000_000, as_of=None); s.flush()
    ct = c.create_contact(s, owner_id=u.id, name="X"); s.flush()
    _loan(s, u, "I", "INR", "given", 100000, contact_id=ct.id)
    _loan(s, u, "U", "USD", "given", 2000, contact_id=ct.id)
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    g = [x for x in out["groups"] if x["name"] == "X"][0]
    assert g["given"]["principal_minor"] == 266000
    assert out["partial"] is False


def test_partial_flag_when_rate_missing(ctx):
    s, u, o = ctx
    _loan(s, u, "U", "USD", "given", 2000, counterparty="K")
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    assert out["partial"] is True


def test_sankey_invariant(ctx):
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="S"); s.flush()
    _loan(s, u, "L1", "INR", "given", 100000, contact_id=ct.id)
    _loan(s, u, "L2", "INR", "given", 60000, contact_id=ct.id)
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    sk = out["sankey"]
    contact_nodes = [n for n in sk["nodes"] if n["kind"] == "contact"]
    assert contact_nodes
    cid = contact_nodes[0]["id"]
    incoming = sum(l["value_minor"] for l in sk["links"] if l["target"] == cid)
    outgoing = sum(l["value_minor"] for l in sk["links"] if l["source"] == cid)
    assert incoming == outgoing == 160000
    lent_total = out["base_total"]["lent"]["principal_minor"]
    assert lent_total == 160000


def test_owner_scoping(ctx):
    s, u, o = ctx
    _loan(s, u, "mine", "INR", "given", 100000, counterparty="K")
    _loan(s, o, "theirs", "INR", "given", 999999, counterparty="Z")
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    names = {g["name"] for g in out["groups"]}
    assert names == {"K"} and out["base_total"]["lent"]["principal_minor"] == 100000


def test_empty(ctx):
    s, u, o = ctx
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    assert out["groups"] == [] and out["sankey"]["nodes"] == [] and out["sankey"]["links"] == []


def test_two_different_contacts_same_name_no_contact_id(ctx):
    s, u, o = ctx
    a = c.create_contact(s, owner_id=u.id, name="Ram"); s.flush()
    b = c.create_contact(s, owner_id=u.id, name="ram"); s.flush()  # same normalized name, different id
    _loan(s, u, "L1", "INR", "given", 100000, contact_id=a.id)
    _loan(s, u, "L2", "INR", "given", 50000, contact_id=b.id)
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    ram = [g for g in out["groups"] if g["name"].lower() == "ram"][0]
    assert ram["given"]["count"] == 2          # merged by name
    assert ram["contact_id"] is None           # two different contacts -> no single contact_id


def test_sankey_invariant_mixed_direction(ctx):
    s, u, o = ctx
    ct = c.create_contact(s, owner_id=u.id, name="Mix"); s.flush()
    _loan(s, u, "G", "INR", "given", 100000, contact_id=ct.id)
    _loan(s, u, "T", "INR", "taken", 40000, contact_id=ct.id)
    out = grouped_loans(s, owner_id=u.id, base_currency="INR")
    sk = out["sankey"]
    cnode = [n for n in sk["nodes"] if n["kind"] == "contact"][0]["id"]
    incoming = sum(l["value_minor"] for l in sk["links"] if l["target"] == cnode)
    outgoing = sum(l["value_minor"] for l in sk["links"] if l["source"] == cnode)
    assert incoming == outgoing == 140000      # 100k lent + 40k borrowed, both flow through the contact
    # aggregate: all Direction->Contact links == base_total lent + borrowed
    dir_links = sum(l["value_minor"] for l in sk["links"] if l["source"].startswith("dir:"))
    bt = out["base_total"]
    assert dir_links == bt["lent"]["principal_minor"] + bt["borrowed"]["principal_minor"] == 140000
