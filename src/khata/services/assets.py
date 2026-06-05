from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, AssetPurchase, Installment, LedgerEntry, User
from ..money import SUPPORTED_CURRENCIES

METHODS = {"cash", "upi", "transfer", "cheque"}
SOURCES = {"savings", "loan", "borrowed", "sold_asset", "chit_payout", "other"}


class PlanError(Exception):
    pass


class ValidationError(PlanError):
    pass


def create_asset_plan(session: Session, *, owner_id, name, currency, total_price_minor) -> Plan:
    if currency.upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {currency!r}")
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


def update_ledger_entry(session: Session, *, plan: Plan, entry_id,
                        amount_minor=None, occurred_at=None, method=None,
                        funding_source=None, note=None) -> LedgerEntry:
    """Edit an existing ledger entry in-place (owner-only at the API layer).
    Only the provided fields change; kind/direction stay immutable. Derived
    balances recompute on the next *_state call (balances are never stored)."""
    entry = session.get(LedgerEntry, entry_id)
    if entry is None or entry.plan_id != plan.id:
        raise ValidationError("entry not found")
    if amount_minor is not None:
        if amount_minor <= 0:
            raise ValidationError("amount must be > 0")
        entry.amount_minor = amount_minor
    if occurred_at is not None:
        entry.occurred_at = occurred_at
    if method is not None:
        if method not in METHODS:
            raise ValidationError(f"unknown method: {method}")
        entry.method = method
    if funding_source is not None:
        if funding_source not in SOURCES:
            raise ValidationError(f"unknown funding_source: {funding_source}")
        entry.funding_source = funding_source
    if note is not None:
        entry.note = note
    session.flush()
    return entry


def delete_ledger_entry(session: Session, *, plan: Plan, entry_id) -> None:
    """Delete a ledger entry (owner-only at the API layer). Derived balances recompute
    on the next *_state call."""
    entry = session.get(LedgerEntry, entry_id)
    if entry is None or entry.plan_id != plan.id:
        raise ValidationError("entry not found")
    session.delete(entry)
    session.flush()


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
                     "status": status,
                     "due_date": inst.due_date.isoformat() if inst.due_date else None})

    by_source: dict[str, int] = {}
    for e in outs:
        by_source[e.funding_source] = by_source.get(e.funding_source, 0) + e.amount_minor
    # NOTE: pcts are rounded independently and may not sum to exactly 100.
    funding_breakdown = [
        {"source": src, "amount_minor": amt, "pct": round(amt * 100 / paid) if paid else 0}
        for src, amt in sorted(by_source.items(), key=lambda kv: kv[1], reverse=True)
    ]

    by_user: dict[int, int] = {}
    for e in outs:
        by_user[e.logged_by_user_id] = by_user.get(e.logged_by_user_id, 0) + e.amount_minor
    contributors = []
    for uid, amt in sorted(by_user.items(), key=lambda kv: kv[1], reverse=True):
        user = session.get(User, uid)
        contributors.append({"user_id": uid,
                             "display_name": user.display_name if user else None,
                             "paid_minor": amt,
                             "pct": round(amt * 100 / paid) if paid else 0})

    # Surface existing ledger_entries rows in the state JSON (mirrors chit_state.ledger).
    # No new model/migration — these rows already exist; we just include them.
    ledger = [
        {"id": e.id, "kind": e.kind, "direction": e.direction, "amount_minor": e.amount_minor,
         "created_at": e.created_at.isoformat() if e.created_at else None,
         "occurred_at": e.occurred_at.isoformat(), "method": e.method,
         "funding_source": e.funding_source, "note": e.note,
         "has_proof": bool(e.proof_ref)}
        for e in sorted(plan.ledger_entries, key=lambda x: x.occurred_at.replace(tzinfo=None), reverse=True)
    ]

    return {
        "total_price_minor": total,
        "paid_to_date_minor": paid,
        "remaining_minor": max(0, total - paid),
        "overpaid_minor": max(0, paid - total),
        "next_due_seq": next_due_seq,
        "installments": rows,
        "funding_breakdown": funding_breakdown,
        "contributors": contributors,
        "ledger": ledger,
    }
