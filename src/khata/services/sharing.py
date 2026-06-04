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
    if plan.owner_user_id == user_id:
        return True
    return any(m.user_id == user_id for m in plan.memberships)


def user_plans(session: Session, user_id: int) -> tuple[list[Plan], list[Plan]]:
    """Return (owned, member) plans for a user; member excludes any owned (dedup).

    Owned plans are newest-first; the member list drops plans already owned so a
    plan is never counted twice.
    """
    owned = list(session.scalars(
        select(Plan).where(Plan.owner_user_id == user_id).order_by(Plan.created_at.desc())))
    owned_ids = {p.id for p in owned}
    member_ids = list(session.scalars(
        select(PlanMembership.plan_id).where(PlanMembership.user_id == user_id)))
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
    if any(m.user_id == user.id for m in plan.memberships):
        raise AlreadyMember(email)
    membership = PlanMembership(plan_id=plan.id, user_id=user.id, role="contributor")
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
    rows = [{"user_id": owner.id, "email": owner.email,
             "display_name": owner.display_name, "role": "owner"}]
    for m in plan.memberships:
        u = session.get(User, m.user_id)
        rows.append({"user_id": u.id, "email": u.email,
                     "display_name": u.display_name, "role": m.role})
    return rows
