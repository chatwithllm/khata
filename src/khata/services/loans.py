import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from ..models import Plan, Loan, LedgerEntry, User
from ..money import SUPPORTED_CURRENCIES

DIRECTIONS = {"given", "taken"}
INTEREST_TYPES = {"none", "monthly", "yearly"}
LOAN_ENTRY_KINDS = {"interest_payment", "principal_repayment"}
# Loan categories — convey nature + what backs the loan. The secured ones imply collateral
# even before a holding is linked (a gold loan is backed by gold, a home loan by property).
LOAN_KINDS = {"personal", "gold", "home", "vehicle", "education", "business", "other"}


class LoanError(Exception):
    pass


class ValidationError(LoanError):
    pass


def _apply_collateral(loan, c) -> None:
    """Set/clear a loan's inline collateral block (gold weight/rate/value). `None` value
    in the dict clears that field; passing c=None leaves everything untouched."""
    if c is None:
        return
    loan.collateral_qty_micro = c.get("qty_micro")
    loan.collateral_unit = c.get("unit")
    loan.collateral_rate_minor = c.get("rate_minor")
    loan.collateral_rate_basis = c.get("rate_basis")
    loan.collateral_value_minor = c.get("value_minor")


def create_loan_plan(session: Session, *, owner_id, name, currency, direction, interest_type,
                     rate_bps, start_date, counterparty=None, tenure_months=None,
                     kind="personal", collateral=None) -> Plan:
    if direction not in DIRECTIONS:
        raise ValidationError(f"unknown direction: {direction}")
    if interest_type not in INTEREST_TYPES:
        raise ValidationError(f"unknown interest_type: {interest_type}")
    if (kind or "personal") not in LOAN_KINDS:
        raise ValidationError(f"unknown loan kind: {kind}")
    if currency.upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {currency!r}")
    if rate_bps < 0:
        raise ValidationError("rate must be >= 0")
    plan = Plan(owner_user_id=owner_id, type="loan",
                name=(name or "").strip() or "Untitled loan",
                currency=currency.upper(), status="active")
    session.add(plan)
    session.flush()
    loan = Loan(plan_id=plan.id, direction=direction, counterparty=counterparty,
                interest_type=interest_type, kind=kind or "personal",
                rate_bps=rate_bps if interest_type != "none" else 0,
                start_date=start_date, tenure_months=tenure_months)
    _apply_collateral(loan, collateral)
    session.add(loan)
    session.flush()
    return plan


def set_collateral(session: Session, *, plan: Plan, collateral_plan_id):
    loan = plan.loan
    if collateral_plan_id is None:
        loan.secured = False
        loan.collateral_plan_id = None
        session.flush()
        return loan
    coll = session.get(Plan, collateral_plan_id)
    if coll is None or coll.type != "holding":
        raise ValidationError("collateral must be a holding plan")
    if coll.owner_user_id != plan.owner_user_id:
        raise ValidationError("collateral must be owned by you")
    if coll.currency != plan.currency:
        raise ValidationError("collateral must match the loan currency")
    loan.secured = True
    loan.collateral_plan_id = coll.id
    session.flush()
    return loan


def update_loan_terms(session: Session, *, plan: Plan, name=None, direction=None,
                      counterparty=None, interest_type=None, rate_bps=None,
                      start_date=None, tenure_months=None, kind=None, collateral=None) -> Loan:
    """Edit a loan plan's terms in place (owner-only at the API layer). Principal is NOT
    here — it's recorded as disbursements. Only provided fields change."""
    loan = plan.loan
    _apply_collateral(loan, collateral)
    if name is not None:
        n = (name or "").strip()
        if n:
            plan.name = n
    if kind is not None:
        if kind not in LOAN_KINDS:
            raise ValidationError(f"unknown loan kind: {kind}")
        loan.kind = kind
    if direction is not None:
        if direction not in DIRECTIONS:
            raise ValidationError(f"unknown direction: {direction}")
        loan.direction = direction
    if interest_type is not None:
        if interest_type not in INTEREST_TYPES:
            raise ValidationError(f"unknown interest_type: {interest_type}")
        loan.interest_type = interest_type
        if interest_type == "none":
            loan.rate_bps = 0
    if rate_bps is not None:
        if rate_bps < 0:
            raise ValidationError("rate must be >= 0")
        if loan.interest_type != "none":
            loan.rate_bps = rate_bps
    if counterparty is not None:
        loan.counterparty = counterparty or None
    if start_date is not None:
        loan.start_date = start_date
    if tenure_months is not None:
        loan.tenure_months = tenure_months
    session.flush()
    return loan


def _direction_for(loan_direction: str, kind: str) -> str:
    if loan_direction == "taken":
        return "in" if kind == "disbursement" else "out"
    return "out" if kind == "disbursement" else "in"


def add_disbursement(session: Session, *, plan: Plan, user_id, amount_minor, occurred_at,
                     note=None, acting_user_id=None) -> LedgerEntry:
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    from .assets import _amount_status_for
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, kind="disbursement",
                        direction=_direction_for(plan.loan.direction, "disbursement"),
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at,
                        method=None, funding_source=None, note=note,
                        amount_status=_amount_status_for(user_id, acting_user_id))
    session.add(entry)
    session.flush()
    return entry


def log_loan_entry(session: Session, *, plan: Plan, user_id, kind, amount_minor, occurred_at,
                   method=None, note=None, acting_user_id=None) -> LedgerEntry:
    if kind not in LOAN_ENTRY_KINDS:
        raise ValidationError(f"unknown loan entry kind: {kind}")
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    from .assets import _amount_status_for
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, kind=kind,
                        direction=_direction_for(plan.loan.direction, kind),
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at,
                        method=method, funding_source=None, note=note,
                        amount_status=_amount_status_for(user_id, acting_user_id))
    session.add(entry)
    session.flush()
    return entry


def _month_add(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    mo = m % 12 + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def _monthly_rate(interest_type: str, rate_bps: int) -> Decimal:
    """Per-month rate as a Decimal (mirrors loan_state's accrual: monthly = bps/10000,
    yearly = bps/120000, none = 0)."""
    if interest_type == "monthly":
        return Decimal(rate_bps) / Decimal(10000)
    if interest_type == "yearly":
        return Decimal(rate_bps) / Decimal(120000)
    return Decimal(0)


def _emi(principal_minor: int, mr: Decimal, n: int) -> int:
    """Level monthly payment (principal+interest) that retires `principal_minor` over `n`
    months at monthly rate `mr`. Integer minor units."""
    if n <= 0:
        return principal_minor
    if mr == 0:
        return -(-principal_minor // n)          # ceil division (interest-free)
    factor = (Decimal(1) + mr) ** n
    emi = Decimal(principal_minor) * mr * factor / (factor - 1)
    return int(emi.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _simulate(principal_minor: int, mr: Decimal, payment_minor: int,
              extra_minor: int = 0, lump_minor: int = 0, lump_month: int = 1,
              cap: int = 1200) -> dict | None:
    """Amortise a balance month by month. Returns months/total-interest/schedule, or None
    if the payment never covers the interest (the balance would diverge)."""
    bal = principal_minor
    total_int = 0
    sched = []
    m = 0
    while bal > 0 and m < cap:
        m += 1
        interest = int((Decimal(bal) * mr).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        principal_part = (payment_minor + extra_minor) - interest
        if lump_minor and m == lump_month:
            principal_part += lump_minor
        if principal_part <= 0:
            return None                          # diverges — payment < interest
        if principal_part > bal:
            principal_part = bal
        bal -= principal_part
        total_int += interest
        sched.append({"month": m, "payment_minor": interest + principal_part,
                      "interest_minor": interest, "principal_minor": principal_part,
                      "balance_minor": bal})
    return {"months": m, "total_interest_minor": total_int,
            "total_paid_minor": principal_minor + total_int, "schedule": sched}


def _apr_bps(net_received_minor: int, payment_minor: int, n: int) -> int | None:
    """Effective annual rate (bps) that equates the cash you actually RECEIVE (principal −
    upfront fee) to the EMI stream — i.e. the true cost of the loan including the fee.
    Monthly IRR via bisection, then annualised. Float math (this is a derived rate, not
    money). Returns None if it can't be solved."""
    if net_received_minor <= 0 or payment_minor <= 0 or n <= 0:
        return None
    net = float(net_received_minor)
    pay = float(payment_minor)

    def pv(i: float) -> float:
        return pay * n if i == 0 else pay * (1 - (1 + i) ** (-n)) / i

    if pv(0.0) <= net:           # payments don't even cover the cash received → ~0% (or free)
        return 0
    lo, hi = 0.0, 1.0            # monthly rate bracket (0%..100%/mo)
    for _ in range(100):
        mid = (lo + hi) / 2
        if pv(mid) > net:
            lo = mid
        else:
            hi = mid
    i = (lo + hi) / 2
    return int(round(((1 + i) ** 12 - 1) * 10000))


def compare_offers(*, principal_minor: int, currency: str, offers: list) -> dict:
    """Compare loan offers on a like-for-like principal. Each offer:
    {label, rate_bps, interest_type, tenure_months, fee_bps?, fee_minor?, principal_minor?}.
    Returns a row per offer with EMI, total interest, upfront fee, TOTAL COST (interest +
    fee), and EFFECTIVE APR (fee-inclusive) — the honest shop-around numbers. The cheapest
    by total cost is flagged `best`, with `vs_first_*` deltas against the first row (the
    user's current loan)."""
    rows = []
    for o in offers:
        P = int(o.get("principal_minor") or principal_minor)
        n = int(o.get("tenure_months") or 0)
        rate_bps = int(o.get("rate_bps") or 0)
        it = o.get("interest_type") or "yearly"
        fee = int(o.get("fee_minor") or 0) + int(round(P * int(o.get("fee_bps") or 0) / 10000))
        if P <= 0 or n <= 0:
            rows.append({"label": o.get("label"), "available": False,
                         "rate_bps": rate_bps, "interest_type": it, "tenure_months": n,
                         "fee_minor": fee})
            continue
        mr = _monthly_rate(it, rate_bps)
        emi = _emi(P, mr, n)
        sim = _simulate(P, mr, emi)
        ti = sim["total_interest_minor"] if sim else 0
        rows.append({
            "label": o.get("label"), "available": True, "principal_minor": P,
            "rate_bps": rate_bps, "interest_type": it, "tenure_months": n,
            "fee_minor": fee, "emi_minor": emi, "total_interest_minor": ti,
            "total_cost_minor": ti + fee, "net_received_minor": P - fee,
            "apr_bps": _apr_bps(P - fee, emi, n),
        })
    avail = [r for r in rows if r.get("available")]
    best = min(avail, key=lambda r: r["total_cost_minor"]) if avail else None
    first = rows[0] if rows and rows[0].get("available") else None
    for r in rows:
        r["best"] = (r is best)
        if r.get("available") and first is not None:
            r["vs_first_cost_minor"] = r["total_cost_minor"] - first["total_cost_minor"]
            if first.get("apr_bps") is not None and r.get("apr_bps") is not None:
                r["vs_first_apr_bps"] = r["apr_bps"] - first["apr_bps"]
    return {"currency": currency, "rows": rows}


def amortize(*, principal_minor: int, rate_bps: int, interest_type: str, tenure_months,
             currency: str, extra_monthly_minor: int = 0, lump_minor: int = 0,
             lump_month: int = 1, target_months=None, as_of: date | None = None) -> dict:
    """Project a repayment plan: the level EMI that retires the current outstanding over
    the loan's tenure, plus an optional what-if (extra-per-month, one-time lump, or a
    target payoff month) showing months-saved and interest-saved vs the baseline.

    This is a forward PROJECTION (planning), independent of the actual ledger — Khata
    loans accrue interest + take manual principal repayments; this answers "what if I
    amortised it on a fixed schedule instead."""
    as_of = as_of or date.today()
    if not tenure_months or int(tenure_months) <= 0 or principal_minor <= 0:
        return {"available": False,
                "reason": "needs_tenure" if (not tenure_months or int(tenure_months or 0) <= 0)
                else "no_principal",
                "currency": currency, "principal_minor": max(0, principal_minor),
                "tenure_months": tenure_months}
    n = int(tenure_months)
    mr = _monthly_rate(interest_type, rate_bps)
    emi = _emi(principal_minor, mr, n)
    base = _simulate(principal_minor, mr, emi)
    out = {
        "available": True, "currency": currency, "principal_minor": principal_minor,
        "tenure_months": n, "rate_bps": rate_bps, "interest_type": interest_type,
        "emi_minor": emi,
        "baseline": {"months": base["months"],
                     "total_interest_minor": base["total_interest_minor"],
                     "total_paid_minor": base["total_paid_minor"],
                     "payoff_date": _month_add(as_of, base["months"]).isoformat()},
        "schedule": base["schedule"][:120],
    }

    # what-if scenario
    lump_month = max(1, int(lump_month or 1))
    sim = None
    required = None
    if target_months:
        k = int(target_months)
        if k > 0:
            required = _emi(principal_minor, mr, k)
            sim = _simulate(principal_minor, mr, required, 0, lump_minor or 0, lump_month)
            extra_monthly_minor = max(0, required - emi)
    elif (extra_monthly_minor or 0) > 0 or (lump_minor or 0) > 0:
        sim = _simulate(principal_minor, mr, emi, extra_monthly_minor or 0,
                        lump_minor or 0, lump_month)

    if sim is not None:
        out["scenario"] = {
            "extra_monthly_minor": extra_monthly_minor or 0,
            "lump_minor": lump_minor or 0, "lump_month": lump_month,
            "required_payment_minor": required,
            "months": sim["months"],
            "months_saved": max(0, base["months"] - sim["months"]),
            "total_interest_minor": sim["total_interest_minor"],
            "interest_saved_minor": max(0, base["total_interest_minor"] - sim["total_interest_minor"]),
            "total_paid_minor": sim["total_paid_minor"],
            "payoff_date": _month_add(as_of, sim["months"]).isoformat(),
            "schedule": sim["schedule"][:120],
        }
    elif target_months or (extra_monthly_minor or 0) > 0 or (lump_minor or 0) > 0:
        out["scenario"] = {"diverges": True}     # payment can't cover interest
    return out


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

    secured = bool(loan.secured)
    collateral = None
    if loan.collateral_plan_id is not None:
        from . import holdings
        cp = session.get(Plan, loan.collateral_plan_id)
        if cp is not None and cp.holding is not None:
            hs = holdings.holding_state(session, cp.holding)
            val = hs["current_value_minor"]
            ltv = (int((Decimal(max(0, principal_outstanding)) * 100 / val)
                       .quantize(Decimal(1), rounding=ROUND_HALF_UP)) if val else None)
            collateral = {"plan_id": cp.id, "name": cp.name, "asset_class": hs["asset_class"],
                          "currency": cp.currency, "value_minor": val, "ltv_pct": ltv}

    # Inline collateral (e.g. a gold loan's weight/rate/value entered on the loan itself).
    gold_collateral = None
    if loan.collateral_value_minor or loan.collateral_qty_micro:
        gval = loan.collateral_value_minor or 0
        gltv = (int((Decimal(max(0, principal_outstanding)) * 100 / gval)
                    .quantize(Decimal(1), rounding=ROUND_HALF_UP)) if gval else None)
        gold_collateral = {
            "qty_micro": loan.collateral_qty_micro, "unit": loan.collateral_unit,
            "rate_minor": loan.collateral_rate_minor, "rate_basis": loan.collateral_rate_basis,
            "value_minor": gval, "ltv_pct": gltv,
        }

    # Surface existing ledger_entries rows in the state JSON (mirrors chit_state.ledger).
    # No new model/migration — these rows already exist; we just include them.
    _names = {}
    for e in plan.ledger_entries:
        if e.logged_by_user_id not in _names:
            _u = session.get(User, e.logged_by_user_id)
            _names[e.logged_by_user_id] = _u.display_name if _u else None
    ledger = [
        {"id": e.id, "kind": e.kind, "direction": e.direction, "amount_minor": e.amount_minor,
         "created_at": e.created_at.isoformat() if e.created_at else None,
         "occurred_at": e.occurred_at.isoformat(), "method": e.method,
         "funding_source": e.funding_source, "note": e.note,
         "has_proof": bool(e.proof_ref),
         "logged_by_user_id": e.logged_by_user_id, "paid_by_name": _names.get(e.logged_by_user_id),
         "amount_status": e.amount_status, "counter_amount_minor": e.counter_amount_minor}
        for e in sorted(plan.ledger_entries, key=lambda x: x.occurred_at.replace(tzinfo=None), reverse=True)
    ]

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
        "secured": secured,
        "collateral": collateral,
        "gold_collateral": gold_collateral,
        "ledger": ledger,
    }
