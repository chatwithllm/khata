from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, User, PlanMembership


class MemberError(Exception):
    pass


class UserNotFound(MemberError):
    pass


class AlreadyMember(MemberError):
    pass


def accessible(session: Session, *, plan: Plan, user_id: int) -> bool:
    """Can the user VIEW/use the plan — owner, or a member who has accepted (active)."""
    if plan.owner_user_id == user_id:
        return True
    return any(m.user_id == user_id and m.status == "active" for m in plan.memberships)


def on_plan(session: Session, *, plan: Plan, user_id: int) -> bool:
    """Is the user attached to the plan at all (owner, active, or pending invite) —
    used for tagging 'paid by' contributors, who may be invited-but-not-yet-accepted."""
    if plan.owner_user_id == user_id:
        return True
    return any(m.user_id == user_id and m.status != "declined" for m in plan.memberships)


def user_plans(session: Session, user_id: int) -> tuple[list[Plan], list[Plan]]:
    """Return (owned, member) plans for a user; member excludes any owned (dedup).

    Owned plans are newest-first; the member list drops plans already owned so a
    plan is never counted twice.
    """
    owned = list(session.scalars(
        select(Plan).where(Plan.owner_user_id == user_id).order_by(Plan.created_at.desc())))
    owned_ids = {p.id for p in owned}
    member_ids = list(session.scalars(
        select(PlanMembership.plan_id).where(
            PlanMembership.user_id == user_id,
            PlanMembership.status == "active")))
    member = [p for p in (session.get(Plan, pid) for pid in member_ids)
              if p is not None and p.id not in owned_ids]
    return owned, member


def add_member(session: Session, *, plan: Plan, email: str) -> PlanMembership:
    email = (email or "").strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        raise UserNotFound(email)
    if user.id == plan.owner_user_id:
        raise AlreadyMember("owner is already on the plan")
    existing = next((m for m in plan.memberships if m.user_id == user.id), None)
    if existing is not None:
        # Re-inviting someone who previously declined resets them to 'invited';
        # an already-invited or active member is a no-op error.
        if existing.status == "declined":
            existing.status = "invited"
            session.flush()
            return existing
        raise AlreadyMember(email)
    membership = PlanMembership(plan_id=plan.id, user_id=user.id, role="contributor",
                               status="invited")
    plan.memberships.append(membership)
    session.flush()
    return membership


def remove_member(session: Session, *, plan: Plan, user_id: int) -> None:
    membership = next((m for m in plan.memberships if m.user_id == user_id), None)
    if membership is None:
        raise MemberError("not_a_member")
    plan.memberships.remove(membership)
    session.flush()


def list_members(session: Session, plan: Plan) -> list[dict]:
    owner = session.get(User, plan.owner_user_id)
    rows = [{"user_id": owner.id, "email": owner.email, "display_name": owner.display_name,
             "avatar": owner.avatar, "role": "owner", "status": "active"}]
    for m in plan.memberships:
        if m.status == "declined":
            continue
        u = session.get(User, m.user_id)
        rows.append({"user_id": u.id, "email": u.email, "display_name": u.display_name,
                     "avatar": u.avatar, "role": m.role, "status": m.status})
    return rows


def list_invitations(session: Session, user_id: int) -> list[dict]:
    """Pending shares awaiting this user's accept/decline. One row per invited plan,
    carrying who shared it and what it is so the dashboard can render a banner."""
    rows = []
    memberships = session.scalars(
        select(PlanMembership).where(
            PlanMembership.user_id == user_id,
            PlanMembership.status == "invited"))
    for m in memberships:
        plan = session.get(Plan, m.plan_id)
        if plan is None:
            continue
        owner = session.get(User, plan.owner_user_id)
        rows.append({
            "plan_id": plan.id,
            "plan_name": plan.name,
            "plan_type": plan.type,
            "currency": plan.currency,
            "role": m.role,
            "shared_by": owner.display_name if owner else None,
            "shared_by_email": owner.email if owner else None,
            "invited_at": m.created_at.isoformat() if m.created_at else None,
        })
    return rows


def respond_invitation(session: Session, *, user_id: int, plan_id: int, accept: bool) -> dict:
    """Accept or decline a pending share. Accept flips status to 'active' (plan now
    visible to the user); decline flips to 'declined' (hidden, re-invitable)."""
    membership = session.scalar(
        select(PlanMembership).where(
            PlanMembership.user_id == user_id,
            PlanMembership.plan_id == plan_id))
    if membership is None:
        raise MemberError("not_a_member")
    if membership.status != "invited":
        raise MemberError("not_pending")
    membership.status = "active" if accept else "declined"
    session.flush()
    return {"plan_id": plan_id, "status": membership.status}
