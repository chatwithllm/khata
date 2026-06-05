import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan
from khata.services.sharing import (
    add_member, remove_member, list_members, accessible, on_plan,
    list_invitations, respond_invitation,
    UserNotFound, AlreadyMember, MemberError,
)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        owner = User(email="o@b.com", display_name="Owner", password_hash="x")
        member = User(email="m@b.com", display_name="Priya", password_hash="x")
        stranger = User(email="s@b.com", display_name="Stranger", password_hash="x")
        s.add_all([owner, member, stranger])
        s.flush()
        plan = Plan(owner_user_id=owner.id, type="asset", name="Plot", currency="INR")
        s.add(plan)
        s.flush()
        yield s, owner, member, stranger, plan


def test_add_list_remove_and_accessible(ctx):
    s, owner, member, stranger, plan = ctx
    add_member(s, plan=plan, email="m@b.com")
    s.commit()
    assert accessible(s, plan=plan, user_id=owner.id) is True
    # Invited-but-not-yet-accepted: NOT accessible (can't view), but on_plan (taggable).
    assert accessible(s, plan=plan, user_id=member.id) is False
    assert on_plan(s, plan=plan, user_id=member.id) is True
    assert accessible(s, plan=plan, user_id=stranger.id) is False

    rows = list_members(s, plan)
    assert {r["role"] for r in rows} == {"owner", "contributor"}
    assert any(r["display_name"] == "Priya" and r["role"] == "contributor"
               and r["status"] == "invited" for r in rows)

    # After accepting, the member can view the plan.
    respond_invitation(s, user_id=member.id, plan_id=plan.id, accept=True)
    s.commit()
    assert accessible(s, plan=plan, user_id=member.id) is True

    remove_member(s, plan=plan, user_id=member.id)
    s.commit()
    assert accessible(s, plan=plan, user_id=member.id) is False


def test_invitation_accept_decline_and_reinvite(ctx):
    s, owner, member, stranger, plan = ctx
    add_member(s, plan=plan, email="m@b.com")
    s.commit()

    # Pending invitation surfaces for the member.
    invs = list_invitations(s, member.id)
    assert len(invs) == 1
    assert invs[0]["plan_id"] == plan.id
    assert invs[0]["plan_name"] == "Plot"
    assert invs[0]["shared_by"] == "Owner"

    # Decline hides the plan and clears the invitation.
    respond_invitation(s, user_id=member.id, plan_id=plan.id, accept=False)
    s.commit()
    assert accessible(s, plan=plan, user_id=member.id) is False
    assert list_invitations(s, member.id) == []
    # Declined members are hidden from the member list.
    assert all(r["display_name"] != "Priya" for r in list_members(s, plan))

    # Re-inviting a declined user resets them to pending (not an error).
    add_member(s, plan=plan, email="m@b.com")
    s.commit()
    assert len(list_invitations(s, member.id)) == 1

    # Responding to a non-pending invitation raises.
    respond_invitation(s, user_id=member.id, plan_id=plan.id, accept=True)
    s.commit()
    with pytest.raises(MemberError):
        respond_invitation(s, user_id=member.id, plan_id=plan.id, accept=True)


def test_add_member_errors(ctx):
    s, owner, member, stranger, plan = ctx
    with pytest.raises(UserNotFound):
        add_member(s, plan=plan, email="nobody@x.com")
    with pytest.raises(AlreadyMember):
        add_member(s, plan=plan, email="o@b.com")  # owner can't be a member
    add_member(s, plan=plan, email="m@b.com")
    s.commit()
    with pytest.raises(AlreadyMember):
        add_member(s, plan=plan, email="m@b.com")  # dup


def test_remove_nonmember_raises(ctx):
    s, owner, member, stranger, plan = ctx
    with pytest.raises(MemberError):
        remove_member(s, plan=plan, user_id=stranger.id)
