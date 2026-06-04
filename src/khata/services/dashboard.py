from datetime import date

from sqlalchemy.orm import Session

from . import loans, sharing


def net_position(session: Session, user_id: int) -> dict:
    owned, member = sharing.user_plans(session, user_id)
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
