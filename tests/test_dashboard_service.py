from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.assets import create_asset_plan, log_payment
from khata.services.loans import create_loan_plan, add_disbursement
from khata.services.sharing import add_member, respond_invitation
from khata.services.dashboard import net_position


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="a@b.com", display_name="Arjun", password_hash="x")
        s.add(u)
        s.flush()
        yield s, u


def _dt():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_net_position_rollup(ctx):
    s, u = ctx
    # loan TAKEN, no interest, 1L principal -> i_owe 1L
    taken = create_loan_plan(s, owner_id=u.id, name="GL", currency="INR", direction="taken",
                             interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=taken, user_id=u.id, amount_minor=10000000, occurred_at=_dt())
    # loan GIVEN, no interest, 0.4L -> owed_to_me 0.4L
    given = create_loan_plan(s, owner_id=u.id, name="Lent", currency="INR", direction="given",
                             interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=given, user_id=u.id, amount_minor=4000000, occurred_at=_dt())
    # asset, u pays 1L -> paid_to_date 1L
    asset = create_asset_plan(s, owner_id=u.id, name="Plot", currency="INR",
                              total_price_minor=50000000)
    log_payment(s, plan=asset, user_id=u.id, amount_minor=10000000, occurred_at=_dt(),
                method="upi", funding_source="savings")
    s.commit()

    d = net_position(s, u.id)
    assert d["i_owe_minor"] == 10000000
    assert d["owed_to_me_minor"] == 4000000
    assert d["paid_to_date_minor"] == 10000000
    assert d["net_position_minor"] == 4000000 - 10000000
    assert len(d["plans"]) == 3
    assert all(p["role"] == "owner" for p in d["plans"])


def test_member_shared_plan_appears(ctx):
    s, u = ctx
    other = User(email="o@b.com", display_name="Owner", password_hash="x")
    s.add(other)
    s.flush()
    plan = create_asset_plan(s, owner_id=other.id, name="Joint", currency="INR",
                             total_price_minor=20000000)
    add_member(s, plan=plan, email="a@b.com")  # u is invited
    respond_invitation(s, user_id=u.id, plan_id=plan.id, accept=True)  # u accepts → active member
    log_payment(s, plan=plan, user_id=u.id, amount_minor=5000000, occurred_at=_dt(),
                method="upi", funding_source="savings")
    s.commit()

    d = net_position(s, u.id)
    assert any(p["id"] == plan.id and p["role"] == "member" for p in d["plans"])
    assert d["paid_to_date_minor"] == 5000000  # u's contribution to the shared asset
