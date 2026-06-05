from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from ..models import Plan, Chit, LedgerEntry
from ..money import SUPPORTED_CURRENCIES

CHIT_KINDS = {"chit_contribution", "chit_dividend", "chit_prize"}


class ChitError(Exception):
    pass


class ValidationError(ChitError):
    pass


def _round(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def create_chit_plan(session: Session, *, owner_id, name, currency, chit_value_minor, n_members,
                     commission_bps, start_date) -> Plan:
    if (currency or "").upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {currency!r}")
    if n_members < 2:
        raise ValidationError("n_members must be >= 2")
    if chit_value_minor <= 0:
        raise ValidationError("chit_value must be > 0")
    if not (0 <= commission_bps <= 10000):
        raise ValidationError("commission_bps must be 0..10000")
    plan = Plan(owner_user_id=owner_id, type="chit",
                name=(name or "").strip() or "Untitled chit", currency=currency.upper(), status="active")
    session.add(plan)
    session.flush()
    session.add(Chit(plan_id=plan.id, chit_value_minor=chit_value_minor, n_members=n_members,
                     commission_bps=commission_bps, start_date=start_date))
    session.flush()
    return plan


def log_chit_entry(session: Session, *, plan: Plan, user_id, kind, amount_minor, occurred_at, note=None) -> LedgerEntry:
    if kind not in CHIT_KINDS:
        raise ValidationError(f"unknown chit kind: {kind}")
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    direction = "out" if kind == "chit_contribution" else "in"
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, kind=kind, direction=direction,
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at, note=note)
    plan.ledger_entries.append(entry)
    session.flush()
    return entry


def auction_dividend(*, chit_value_minor, commission_bps, n_members, winning_bid_minor) -> dict:
    commission = _round(Decimal(chit_value_minor) * commission_bps / 10000)
    pool = max(0, winning_bid_minor - commission)
    per_member = _round(Decimal(pool) / n_members) if n_members else 0
    return {"commission_minor": commission, "dividend_pool_minor": pool,
            "dividend_per_member_minor": per_member, "prize_minor": chit_value_minor - winning_bid_minor}


def chit_state(session: Session, chit: Chit) -> dict:
    plan = chit.plan
    def total(kind): return sum(e.amount_minor for e in plan.ledger_entries if e.kind == kind)
    contributed = total("chit_contribution")
    dividends = total("chit_dividend")
    prize = total("chit_prize")
    subscription = _round(Decimal(chit.chit_value_minor) / chit.n_members) if chit.n_members else 0
    months_recorded = sum(1 for e in plan.ledger_entries if e.kind == "chit_contribution")
    ledger = [{"kind": e.kind, "direction": e.direction, "amount_minor": e.amount_minor,
               "occurred_at": e.occurred_at.isoformat(), "note": e.note}
              for e in plan.ledger_entries if e.kind in CHIT_KINDS]
    return {
        "currency": plan.currency, "chit_value_minor": chit.chit_value_minor,
        "n_members": chit.n_members, "commission_bps": chit.commission_bps,
        "subscription_minor": subscription,
        "total_contributed_minor": contributed, "total_dividends_minor": dividends,
        "prize_received_minor": prize, "net_contributed_minor": contributed - dividends,
        "net_position_minor": prize + dividends - contributed, "won": prize > 0,
        "months_recorded": months_recorded, "ledger": ledger,
    }
