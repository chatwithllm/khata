from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, AssetPurchase, Installment, LedgerEntry

METHODS = {"cash", "upi", "transfer", "cheque"}
SOURCES = {"savings", "loan", "borrowed", "sold_asset", "chit_payout", "other"}


class PlanError(Exception):
    pass


class ValidationError(PlanError):
    pass


def create_asset_plan(session: Session, *, owner_id, name, currency, total_price_minor) -> Plan:
    if total_price_minor <= 0:
        raise ValidationError("total_price must be > 0")
    plan = Plan(owner_user_id=owner_id, type="asset",
                name=(name or "").strip() or "Untitled asset",
                currency=currency.upper(), status="active")
    session.add(plan)
    session.flush()
    session.add(AssetPurchase(plan_id=plan.id, total_price_minor=total_price_minor))
    session.flush()
    return plan


def set_installments(session: Session, *, plan: Plan, items) -> None:
    for it in items:
        if it["amount_minor"] <= 0:
            raise ValidationError("installment amount must be > 0")
    for inst in list(plan.installments):
        session.delete(inst)
    session.flush()
    # Expire so the relationship collection is refreshed after the deletes.
    session.expire(plan, ["installments"])
    for i, it in enumerate(items, start=1):
        plan.installments.append(
            Installment(plan_id=plan.id, seq=i, planned_amount_minor=it["amount_minor"],
                        due_date=it.get("due_date"), note=it.get("note")))
    session.flush()


def log_payment(session: Session, *, plan: Plan, user_id, amount_minor, occurred_at,
                method, funding_source, direction="out", proof_ref=None, note=None) -> LedgerEntry:
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    if method not in METHODS:
        raise ValidationError(f"unknown method: {method}")
    if funding_source not in SOURCES:
        raise ValidationError(f"unknown funding_source: {funding_source}")
    if direction not in {"out", "in"}:
        raise ValidationError("direction must be 'out' or 'in'")
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, direction=direction,
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at,
                        method=method, funding_source=funding_source, proof_ref=proof_ref, note=note)
    session.add(entry)
    session.flush()
    return entry


def list_plans(session: Session, owner_id) -> list[Plan]:
    return list(session.scalars(
        select(Plan).where(Plan.owner_user_id == owner_id).order_by(Plan.created_at.desc())))


def asset_state(session: Session, plan: Plan) -> dict:
    total = plan.asset.total_price_minor if plan.asset is not None else 0
    outs = [e for e in plan.ledger_entries if e.direction == "out"]
    paid = sum(e.amount_minor for e in outs)

    pool = paid
    rows = []
    next_due_seq = None
    for inst in sorted(plan.installments, key=lambda i: i.seq):
        applied = min(pool, inst.planned_amount_minor)
        pool -= applied
        if applied == inst.planned_amount_minor:
            status = "paid"
        elif applied > 0:
            status = "partial"
        else:
            status = "due"
        if status != "paid" and next_due_seq is None:
            next_due_seq = inst.seq
        rows.append({"seq": inst.seq,
                     "planned_amount_minor": inst.planned_amount_minor,
                     "applied_minor": applied,
                     "status": status})

    by_source: dict[str, int] = {}
    for e in outs:
        by_source[e.funding_source] = by_source.get(e.funding_source, 0) + e.amount_minor
    # NOTE: pcts are rounded independently and may not sum to exactly 100.
    funding_breakdown = [
        {"source": src, "amount_minor": amt, "pct": round(amt * 100 / paid) if paid else 0}
        for src, amt in sorted(by_source.items(), key=lambda kv: kv[1], reverse=True)
    ]

    return {
        "total_price_minor": total,
        "paid_to_date_minor": paid,
        "remaining_minor": max(0, total - paid),
        "overpaid_minor": max(0, paid - total),
        "next_due_seq": next_due_seq,
        "installments": rows,
        "funding_breakdown": funding_breakdown,
    }
