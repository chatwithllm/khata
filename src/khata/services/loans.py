import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from ..models import Plan, Loan, LedgerEntry
from ..money import SUPPORTED_CURRENCIES

DIRECTIONS = {"given", "taken"}
INTEREST_TYPES = {"none", "monthly", "yearly"}
LOAN_ENTRY_KINDS = {"interest_payment", "principal_repayment"}


class LoanError(Exception):
    pass


class ValidationError(LoanError):
    pass


def create_loan_plan(session: Session, *, owner_id, name, currency, direction, interest_type,
                     rate_bps, start_date, counterparty=None, tenure_months=None) -> Plan:
    if direction not in DIRECTIONS:
        raise ValidationError(f"unknown direction: {direction}")
    if interest_type not in INTEREST_TYPES:
        raise ValidationError(f"unknown interest_type: {interest_type}")
    if currency.upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {currency!r}")
    if rate_bps < 0:
        raise ValidationError("rate must be >= 0")
    plan = Plan(owner_user_id=owner_id, type="loan",
                name=(name or "").strip() or "Untitled loan",
                currency=currency.upper(), status="active")
    session.add(plan)
    session.flush()
    session.add(Loan(plan_id=plan.id, direction=direction, counterparty=counterparty,
                     interest_type=interest_type,
                     rate_bps=rate_bps if interest_type != "none" else 0,
                     start_date=start_date, tenure_months=tenure_months))
    session.flush()
    return plan


def _direction_for(loan_direction: str, kind: str) -> str:
    if loan_direction == "taken":
        return "in" if kind == "disbursement" else "out"
    return "out" if kind == "disbursement" else "in"


def add_disbursement(session: Session, *, plan: Plan, user_id, amount_minor, occurred_at,
                     note=None) -> LedgerEntry:
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, kind="disbursement",
                        direction=_direction_for(plan.loan.direction, "disbursement"),
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at,
                        method=None, funding_source=None, note=note)
    session.add(entry)
    session.flush()
    return entry


def log_loan_entry(session: Session, *, plan: Plan, user_id, kind, amount_minor, occurred_at,
                   method=None, note=None) -> LedgerEntry:
    if kind not in LOAN_ENTRY_KINDS:
        raise ValidationError(f"unknown loan entry kind: {kind}")
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, kind=kind,
                        direction=_direction_for(plan.loan.direction, kind),
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at,
                        method=method, funding_source=None, note=note)
    session.add(entry)
    session.flush()
    return entry


def _month_add(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    mo = m % 12 + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def _complete_months(start: date, as_of: date) -> int:
    months = (as_of.year - start.year) * 12 + (as_of.month - start.month)
    if as_of.day < start.day:
        months -= 1
    return max(0, months)


def loan_state(session: Session, loan: Loan, as_of: date) -> dict:
    plan = loan.plan
    disb = [(e.occurred_at.date(), e.amount_minor) for e in plan.ledger_entries
            if e.kind == "disbursement"]
    prin = [(e.occurred_at.date(), e.amount_minor) for e in plan.ledger_entries
            if e.kind == "principal_repayment"]
    interest_paid = sum(e.amount_minor for e in plan.ledger_entries
                        if e.kind == "interest_payment")
    principal_outstanding = (sum(a for dt, a in disb if dt <= as_of)
                             - sum(a for dt, a in prin if dt <= as_of))

    if loan.interest_type == "monthly":
        monthly_rate = Decimal(loan.rate_bps) / Decimal(10000)
    elif loan.interest_type == "yearly":
        monthly_rate = Decimal(loan.rate_bps) / Decimal(120000)
    else:
        monthly_rate = Decimal(0)

    schedule = []
    interest_accrued = 0
    if monthly_rate > 0:
        for m in range(_complete_months(loan.start_date, as_of)):
            pm = _month_add(loan.start_date, m)
            opening = (sum(a for dt, a in disb if dt <= pm)
                       - sum(a for dt, a in prin if dt <= pm))
            opening = max(0, opening)
            expected = int((Decimal(opening) * monthly_rate).quantize(
                Decimal(1), rounding=ROUND_HALF_UP))
            interest_accrued += expected
            schedule.append({"month_index": m, "period_start": pm.isoformat(),
                             "expected_minor": expected})

    pool = interest_paid
    next_due_month = None
    months_behind = 0
    for row in schedule:
        expected = row["expected_minor"]
        applied = min(pool, expected)
        pool -= applied
        row["applied_minor"] = applied
        if expected == 0 or applied == expected:
            row["status"] = "paid"
        elif applied > 0:
            row["status"] = "partial"
        else:
            row["status"] = "due"
        if row["status"] != "paid":
            months_behind += 1
            if next_due_month is None:
                next_due_month = row["month_index"]

    interest_due = max(0, interest_accrued - interest_paid)
    return {
        "direction": loan.direction,
        "currency": plan.currency,
        "principal_outstanding_minor": max(0, principal_outstanding),
        "interest_accrued_minor": interest_accrued,
        "interest_paid_minor": interest_paid,
        "interest_due_minor": interest_due,
        "total_minor": max(0, principal_outstanding) + interest_due,
        "as_of": as_of.isoformat(),
        "schedule": schedule,
        "next_due_month": next_due_month,
        "months_behind": months_behind,
    }
