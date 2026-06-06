from datetime import date

from sqlalchemy.orm import Session

from ..models import User
from . import loans, sharing, fx

_FIELD_TO_KEY = {"i_owe": "i_owe_minor", "owed_to_me": "owed_to_me_minor",
                 "paid": "paid_to_date_minor"}


def net_position(session: Session, user_id: int) -> dict:
    """Cross-plan money summary in the user's BASE currency.

    Each plan's amount is in its own currency; we convert to base via fx. Amounts
    we can't convert (no rate) go into an `unconverted` bucket per currency so the
    figure is never silently wrong or zero — the UI surfaces the remainder.
    """
    user = session.get(User, user_id)
    base = user.base_currency
    owned, member = sharing.user_plans(session, user_id)

    totals = {"i_owe": 0, "owed_to_me": 0, "paid": 0}
    unconverted: dict[str, dict] = {}
    plans = []

    def _add(field: str, ccy: str, amount_minor: int):
        rate = fx.get_rate(session, base, ccy)
        if rate is not None:
            totals[field] += fx.convert(amount_minor, rate_micro=rate)
        else:
            b = unconverted.setdefault(ccy, {"i_owe_minor": 0, "owed_to_me_minor": 0,
                                             "paid_to_date_minor": 0})
            b[_FIELD_TO_KEY[field]] += amount_minor

    for p in owned:
        plans.append({"id": p.id, "type": p.type, "name": p.name,
                      "currency": p.currency, "role": "owner"})
        if p.type == "loan":
            st = loans.loan_state(session, p.loan, as_of=date.today())
            _add("i_owe" if p.loan.direction == "taken" else "owed_to_me",
                 p.currency, st["total_minor"])
    for p in member:
        plans.append({"id": p.id, "type": p.type, "name": p.name,
                      "currency": p.currency, "role": "member"})

    for p in owned + member:
        if p.type == "asset":
            for e in p.ledger_entries:
                if e.direction == "out" and e.logged_by_user_id == user_id:
                    _add("paid", p.currency, e.amount_minor)

    return {
        "base_currency": base,
        "net_position_minor": totals["owed_to_me"] - totals["i_owe"],
        "i_owe_minor": totals["i_owe"],
        "owed_to_me_minor": totals["owed_to_me"],
        "paid_to_date_minor": totals["paid"],
        "unconverted": unconverted,
        "plans": plans,
    }
