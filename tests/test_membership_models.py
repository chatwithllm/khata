import pytest
from sqlalchemy.exc import IntegrityError

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, PlanMembership


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_membership_persists_and_is_unique():
    s = _session()
    owner = User(email="o@b.com", display_name="Owner", password_hash="x")
    member = User(email="m@b.com", display_name="Priya", password_hash="x")
    s.add_all([owner, member])
    s.flush()
    plan = Plan(owner_user_id=owner.id, type="asset", name="Plot", currency="INR")
    s.add(plan)
    s.flush()
    s.add(PlanMembership(plan_id=plan.id, user_id=member.id))
    s.commit()

    got = s.get(Plan, plan.id)
    assert len(got.memberships) == 1 and got.memberships[0].role == "contributor"

    s.add(PlanMembership(plan_id=plan.id, user_id=member.id))
    with pytest.raises(IntegrityError):
        s.commit()
