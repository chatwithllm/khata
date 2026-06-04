from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, PlanMembership
from . import loans


def _user_plans(session: Session, user_id: int):
    owned = list(session.scalars(select(Plan).where(Plan.owner_user_id == user_id)))
    member_ids = list(session.scalars(
        select(PlanMembership.plan_id).where(PlanMembership.user_id == user_id)))
    owned_ids = {p.id for p in owned}
    member = [p for p in (session.get(Plan, pid) for pid in member_ids)
              if p is not None and p.id not in owned_ids]
    return owned, member


def net_position(session: Session, user_id: int) -> dict:
    owned, member = _user_plans(session, user_id)
    i_owe = 0
    owed_to_me = 0
    paid = 0
    plans = []

    for p in owned:
        plans.append({"id": p.id, "type": p.type, "name": p.name,
                      "currency": p.currency, "role": "owner"})
        if p.type == "loan":
            st = loans.loan_state(session, p.loan, as_of=date.today())
            if p.loan.direction == "taken":
                i_owe += st["total_minor"]
            else:
                owed_to_me += st["total_minor"]
    for p in member:
        plans.append({"id": p.id, "type": p.type, "name": p.name,
                      "currency": p.currency, "role": "member"})

    for p in owned + member:
        if p.type == "asset":
            for e in p.ledger_entries:
                if e.direction == "out" and e.logged_by_user_id == user_id:
                    paid += e.amount_minor

    return {
        "net_position_minor": owed_to_me - i_owe,
        "i_owe_minor": i_owe,
        "owed_to_me_minor": owed_to_me,
        "paid_to_date_minor": paid,
        "plans": plans,
    }
