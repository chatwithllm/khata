from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from ..models import Plan, Retirement
from ..money import SUPPORTED_CURRENCIES

SETTABLE = ("current_balance_minor", "monthly_contribution_minor", "employer_match_bps",
            "annual_return_bps", "inflation_bps", "current_age", "retirement_age")


class RetirementError(Exception):
    pass


class ValidationError(RetirementError):
    pass


def _round(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _validate(*, current_balance_minor, monthly_contribution_minor, employer_match_bps,
              annual_return_bps, inflation_bps, current_age, retirement_age):
    if current_age < 0 or retirement_age < current_age:
        raise ValidationError("retirement_age must be >= current_age >= 0")
    if current_balance_minor < 0 or monthly_contribution_minor < 0:
        raise ValidationError("amounts must be >= 0")
    if employer_match_bps < 0 or annual_return_bps < 0 or inflation_bps < 0:
        raise ValidationError("rates must be >= 0")


def create_retirement_plan(session: Session, *, owner_id, name, currency, current_age, retirement_age,
                           current_balance_minor=0, monthly_contribution_minor=0, employer_match_bps=0,
                           annual_return_bps=800, inflation_bps=600) -> Plan:
    if (currency or "").upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {currency!r}")
    _validate(current_balance_minor=current_balance_minor,
              monthly_contribution_minor=monthly_contribution_minor, employer_match_bps=employer_match_bps,
              annual_return_bps=annual_return_bps, inflation_bps=inflation_bps,
              current_age=current_age, retirement_age=retirement_age)
    plan = Plan(owner_user_id=owner_id, type="retirement",
                name=(name or "").strip() or "Retirement", currency=currency.upper(), status="active")
    session.add(plan)
    session.flush()
    session.add(Retirement(plan_id=plan.id, current_balance_minor=current_balance_minor,
                monthly_contribution_minor=monthly_contribution_minor, employer_match_bps=employer_match_bps,
                annual_return_bps=annual_return_bps, inflation_bps=inflation_bps,
                current_age=current_age, retirement_age=retirement_age))
    session.flush()
    return plan


def update_retirement(session: Session, *, plan: Plan, **fields) -> Retirement:
    r = plan.retirement
    merged = {k: getattr(r, k) for k in SETTABLE}
    for k, v in fields.items():
        if k in SETTABLE and v is not None:
            merged[k] = v
    _validate(**merged)
    for k, v in merged.items():
        setattr(r, k, v)
    session.flush()
    return r


def retirement_state(session: Session, retirement: Retirement) -> dict:
    r = retirement
    n = max(0, r.retirement_age - r.current_age) * 12
    mr = Decimal(r.annual_return_bps) / 120000
    im = Decimal(r.inflation_bps) / 120000
    eff = Decimal(r.monthly_contribution_minor) * (1 + Decimal(r.employer_match_bps) / 10000)
    g = Decimal(1) + mr
    gn = g ** n
    fv_current = Decimal(r.current_balance_minor) * gn
    annuity = ((gn - 1) / mr) if mr > 0 else Decimal(n)
    fv_contrib = eff * annuity
    proj = fv_current + fv_contrib
    infl = (Decimal(1) + im) ** n
    return {
        "currency": r.plan.currency,
        "current_balance_minor": r.current_balance_minor,
        "monthly_contribution_minor": r.monthly_contribution_minor,
        "employer_match_bps": r.employer_match_bps, "annual_return_bps": r.annual_return_bps,
        "inflation_bps": r.inflation_bps, "current_age": r.current_age, "retirement_age": r.retirement_age,
        "months_to_retirement": n, "effective_monthly_minor": _round(eff),
        "total_contributions_minor": _round(eff * n),
        "projected_corpus_minor": _round(proj),
        "projected_corpus_real_minor": _round(proj / infl),
    }
