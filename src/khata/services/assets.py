from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, AssetPurchase, Installment, LedgerEntry, User
from ..money import SUPPORTED_CURRENCIES
from . import fx

METHODS = {"cash", "upi", "transfer", "cheque"}
SOURCES = {"savings", "loan", "borrowed", "sold_asset", "chit_payout", "other"}
_UNSET = object()   # sentinel: "field not provided" vs explicitly set to None (clear)
AMOUNT_STATUSES = {"agreed", "pending", "countered"}


class PlanError(Exception):
    pass


class ValidationError(PlanError):
    pass


def _amount_status_for(attributed_uid, acting_uid) -> str:
    """An entry needs the attributed contributor's confirmation when someone OTHER than
    them recorded the amount on their behalf. Self-logged (or acting unknown) → agreed."""
    if acting_uid is None or attributed_uid == acting_uid:
        return "agreed"
    return "pending"


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
                method, funding_source, direction="out", proof_ref=None, note=None,
                acting_user_id=None, funding_plan_id=None, fx_rate_micro=None) -> LedgerEntry:
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
                        method=method, funding_source=funding_source, proof_ref=proof_ref, note=note,
                        amount_status=_amount_status_for(user_id, acting_user_id),
                        funding_plan_id=funding_plan_id)
    session.add(entry)
    session.flush()
    fx.snapshot_entry_rate(session, entry, explicit_rate_micro=fx_rate_micro)
    return entry


def update_ledger_entry(session: Session, *, plan: Plan, entry_id,
                        amount_minor=None, occurred_at=None, method=None,
                        funding_source=None, note=None, logged_by_user_id=None,
                        acting_user_id=None, funding_plan_id=_UNSET) -> LedgerEntry:
    """Edit an existing ledger entry in-place (owner-only at the API layer).
    Only the provided fields change; kind/direction stay immutable. Derived
    balances recompute on the next *_state call (balances are never stored).

    Changing the amount or the attributed contributor re-opens confirmation: if the
    (possibly new) attributed user isn't the one making the edit, the entry returns to
    'pending' and any prior counter is cleared — a corrected amount needs re-agreement."""
    entry = session.get(LedgerEntry, entry_id)
    if entry is None or entry.plan_id != plan.id:
        raise ValidationError("entry not found")
    amount_changed = amount_minor is not None and amount_minor != entry.amount_minor
    attrib_changed = logged_by_user_id is not None and logged_by_user_id != entry.logged_by_user_id
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
    if logged_by_user_id is not None:
        entry.logged_by_user_id = logged_by_user_id
    if funding_plan_id is not _UNSET:
        entry.funding_plan_id = funding_plan_id      # may be None to unlink
    if amount_changed or attrib_changed:
        entry.amount_status = _amount_status_for(entry.logged_by_user_id, acting_user_id)
        entry.counter_amount_minor = None
    session.flush()
    return entry


def respond_amount(session: Session, *, plan: Plan, entry_id, actor_uid, action,
                   amount_minor=None) -> LedgerEntry:
    """Drive the per-entry amount-agreement loop (see LedgerEntry.amount_status).

    - confirm: the attributed contributor accepts the recorded amount → 'agreed'.
    - counter: the attributed contributor proposes a different amount → 'countered'
      (stored in counter_amount_minor; the recorded amount_minor is untouched).
    - accept:  the owner accepts the contributor's counter → amount_minor = counter,
      'agreed'.
    - recounter (action='counter' by the owner while 'countered'): owner sets a new
      amount_minor and bounces it back to the contributor → 'pending'.
    """
    entry = session.get(LedgerEntry, entry_id)
    if entry is None or entry.plan_id != plan.id:
        raise ValidationError("entry not found")
    is_owner = actor_uid == plan.owner_user_id
    is_attributed = actor_uid == entry.logged_by_user_id

    if action == "confirm":
        if entry.amount_status != "pending" or not is_attributed:
            raise ValidationError("nothing to confirm")
        entry.amount_status = "agreed"
        entry.counter_amount_minor = None
    elif action == "accept":
        if entry.amount_status != "countered" or not is_owner:
            raise ValidationError("no counter to accept")
        entry.amount_minor = entry.counter_amount_minor
        entry.amount_status = "agreed"
        entry.counter_amount_minor = None
    elif action == "counter":
        if amount_minor is None or amount_minor <= 0:
            raise ValidationError("counter amount must be > 0")
        if entry.amount_status == "pending" and is_attributed:
            # Contributor proposes a correction; recorded amount stays until owner accepts.
            entry.counter_amount_minor = amount_minor
            entry.amount_status = "countered"
        elif entry.amount_status == "countered" and is_owner:
            # Owner re-counters: set the new recorded amount, bounce back to contributor.
            entry.amount_minor = amount_minor
            entry.counter_amount_minor = None
            entry.amount_status = "pending"
        else:
            raise ValidationError("not your turn to counter")
    else:
        raise ValidationError(f"unknown action: {action}")
    session.flush()
    return entry


def list_amount_confirmations(session: Session, user_id) -> list[dict]:
    """Entries across all the user's plans that are waiting on THEM to act:
    - 'pending' entries attributed to them (they must confirm or counter), and
    - 'countered' entries on plans they own (they must accept or re-counter).
    One row per entry, with both amounts + whose turn + what action is theirs."""
    rows = []
    pending = session.scalars(
        select(LedgerEntry).where(
            LedgerEntry.logged_by_user_id == user_id,
            LedgerEntry.amount_status == "pending"))
    for e in pending:
        plan = session.get(Plan, e.plan_id)
        if plan is None or plan.owner_user_id == user_id:
            continue  # owner attributing to self never needs self-confirmation
        owner = session.get(User, plan.owner_user_id)
        rows.append({
            "plan_id": plan.id, "entry_id": e.id, "plan_name": plan.name,
            "plan_type": plan.type, "currency": plan.currency,
            "amount_minor": e.amount_minor, "counter_amount_minor": None,
            "occurred_at": e.occurred_at.isoformat(),
            "from_name": owner.display_name if owner else None,
            "your_role": "contributor", "actions": ["confirm", "counter"],
        })
    countered = session.scalars(
        select(LedgerEntry).where(LedgerEntry.amount_status == "countered"))
    for e in countered:
        plan = session.get(Plan, e.plan_id)
        if plan is None or plan.owner_user_id != user_id:
            continue
        contrib = session.get(User, e.logged_by_user_id)
        rows.append({
            "plan_id": plan.id, "entry_id": e.id, "plan_name": plan.name,
            "plan_type": plan.type, "currency": plan.currency,
            "amount_minor": e.amount_minor, "counter_amount_minor": e.counter_amount_minor,
            "occurred_at": e.occurred_at.isoformat(),
            "from_name": contrib.display_name if contrib else None,
            "your_role": "owner", "actions": ["accept", "counter"],
        })
    return rows


def delete_ledger_entry(session: Session, *, plan: Plan, entry_id) -> None:
    """Delete a ledger entry (owner-only at the API layer). Derived balances recompute
    on the next *_state call."""
    entry = session.get(LedgerEntry, entry_id)
    if entry is None or entry.plan_id != plan.id:
        raise ValidationError("entry not found")
    session.delete(entry)
    session.flush()


def delete_plan(session: Session, *, plan: Plan) -> None:
    """Delete a whole plan and everything under it (any type). Children are removed
    explicitly so it's correct regardless of relationship cascade config; the 1:1
    type sub-row (asset/loan/…) goes via the Plan relationship cascade."""
    for e in list(plan.ledger_entries):
        session.delete(e)
    for i in list(plan.installments):
        session.delete(i)
    for m in list(plan.memberships):
        session.delete(m)
    session.flush()
    session.delete(plan)
    session.flush()


def list_plans(session: Session, owner_id) -> list[Plan]:
    return list(session.scalars(
        select(Plan).where(Plan.owner_user_id == owner_id).order_by(Plan.created_at.desc())))


def _viewer_can_access(fp: Plan, viewer_id) -> bool:
    """Owner or active member of the funding plan — i.e. the viewer can actually open it."""
    if viewer_id is None or fp is None:
        return False
    if fp.owner_user_id == viewer_id:
        return True
    return any(m.user_id == viewer_id and m.status == "active" for m in fp.memberships)


def asset_state(session: Session, plan: Plan, viewer_id: int | None = None) -> dict:
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
    unconfirmed_uids: set[int] = set()
    for e in outs:
        by_user[e.logged_by_user_id] = by_user.get(e.logged_by_user_id, 0) + e.amount_minor
        if e.amount_status != "agreed":
            unconfirmed_uids.add(e.logged_by_user_id)
    contributors = []
    for uid, amt in sorted(by_user.items(), key=lambda kv: kv[1], reverse=True):
        user = session.get(User, uid)
        contributors.append({"user_id": uid,
                             "display_name": user.display_name if user else None,
                             "avatar": user.avatar if user else None,
                             "paid_minor": amt,
                             "pct": round(amt * 100 / paid) if paid else 0,
                             "unconfirmed": uid in unconfirmed_uids})

    # Surface existing ledger_entries rows in the state JSON (mirrors chit_state.ledger).
    # No new model/migration — these rows already exist; we just include them.
    _users = {}
    _fplans = {}
    for e in plan.ledger_entries:
        if e.logged_by_user_id not in _users:
            _u = session.get(User, e.logged_by_user_id)
            _users[e.logged_by_user_id] = (_u.display_name, _u.avatar) if _u else (None, None)
        if e.funding_plan_id and e.funding_plan_id not in _fplans:
            _fp = session.get(Plan, e.funding_plan_id)
            _fplans[e.funding_plan_id] = ((_fp.name, _fp.type, _viewer_can_access(_fp, viewer_id))
                                          if _fp else (None, None, False))
    ledger = [
        {"id": e.id, "kind": e.kind, "direction": e.direction, "amount_minor": e.amount_minor,
         "created_at": e.created_at.isoformat() if e.created_at else None,
         "occurred_at": e.occurred_at.isoformat(), "method": e.method,
         "funding_source": e.funding_source, "note": e.note,
         "has_proof": bool(e.proof_ref) or bool(e.attachments),
         "attachment_count": len(e.attachments),
         "logged_by_user_id": e.logged_by_user_id,
         "paid_by_name": _users.get(e.logged_by_user_id, (None, None))[0],
         "paid_by_avatar": _users.get(e.logged_by_user_id, (None, None))[1],
         "funding_plan_id": e.funding_plan_id,
         "funding_plan_name": _fplans.get(e.funding_plan_id, (None, None, False))[0],
         "funding_plan_type": _fplans.get(e.funding_plan_id, (None, None, False))[1],
         "funding_plan_accessible": _fplans.get(e.funding_plan_id, (None, None, False))[2],
         "amount_status": e.amount_status, "counter_amount_minor": e.counter_amount_minor}
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
