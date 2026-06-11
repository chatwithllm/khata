"""Admin / user management.

Admin = `users.is_admin` (the first registered user is bootstrapped admin by migration
de8admin01). Admins manage other users and run whole-instance backup/restore.

Hard invariant: the instance must always keep at least one ENABLED admin. Every mutation
that could remove the last reachable admin (demote / disable / delete) is refused.
"""
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..models import User, Plan, PlanMembership
from ..security import hash_password
from . import assets


class AdminError(Exception):
    pass


def is_admin(user: User | None) -> bool:
    return bool(user and user.is_admin and not user.disabled)


def _enabled_admin_count(session: Session, *, excluding: int | None = None) -> int:
    q = select(func.count()).select_from(User).where(
        User.is_admin.is_(True), User.disabled.is_(False))
    if excluding is not None:
        q = q.where(User.id != excluding)
    return session.scalar(q) or 0


def list_users(session: Session) -> list[dict]:
    rows = session.scalars(select(User).order_by(User.id)).all()
    # owned-plan counts in one pass (for the delete-impact hint)
    counts = dict(session.execute(
        select(Plan.owner_user_id, func.count(Plan.id)).group_by(Plan.owner_user_id)).all())
    out = []
    for u in rows:
        out.append({
            "id": u.id, "email": u.email, "display_name": u.display_name,
            "is_admin": u.is_admin, "disabled": u.disabled,
            "has_password": bool(u.password_hash), "has_google": bool(u.google_sub),
            "avatar": u.avatar, "owned_plans": int(counts.get(u.id, 0)),
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })
    return out


def _get(session: Session, user_id: int) -> User:
    u = session.get(User, user_id)
    if u is None:
        raise AdminError("user not found")
    return u


def set_disabled(session: Session, *, actor: User, user_id: int, disabled: bool) -> User:
    target = _get(session, user_id)
    if target.id == actor.id and disabled:
        raise AdminError("you cannot disable your own account")
    if disabled and target.is_admin and _enabled_admin_count(session, excluding=target.id) == 0:
        raise AdminError("cannot disable the last remaining admin")
    target.disabled = disabled
    session.flush()
    return target


def set_admin(session: Session, *, actor: User, user_id: int, make_admin: bool) -> User:
    target = _get(session, user_id)
    if not make_admin and target.is_admin and _enabled_admin_count(session, excluding=target.id) == 0:
        raise AdminError("cannot remove the last remaining admin")
    target.is_admin = make_admin
    session.flush()
    return target


def reset_password(session: Session, *, user_id: int, new_password: str) -> User:
    if len(new_password or "") < 6:
        raise AdminError("password too short (min 6)")
    target = _get(session, user_id)
    target.password_hash = hash_password(new_password)
    session.flush()
    return target


def delete_user(session: Session, *, actor: User, user_id: int) -> dict:
    """Delete a user and everything they own: their plans (cascades ledger entries,
    attachments, installments, memberships on those plans) plus their memberships on
    OTHER people's plans. Irreversible."""
    target = _get(session, user_id)
    if target.id == actor.id:
        raise AdminError("you cannot delete your own account")
    if target.is_admin and _enabled_admin_count(session, excluding=target.id) == 0:
        raise AdminError("cannot delete the last remaining admin")

    owned = session.scalars(select(Plan).where(Plan.owner_user_id == target.id)).all()
    plans_deleted = len(owned)
    for plan in owned:
        assets.delete_plan(session, plan=plan)   # cascades the plan's children
    # memberships this user holds on plans owned by others
    for m in session.scalars(select(PlanMembership).where(PlanMembership.user_id == target.id)).all():
        session.delete(m)
    session.delete(target)
    session.flush()
    return {"deleted_user": user_id, "plans_deleted": plans_deleted}
