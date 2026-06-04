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


def loan_state(session: Session, loan: Loan, as_of) -> dict:  # implemented in Task 5
    raise NotImplementedError
