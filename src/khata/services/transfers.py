"""Payment chains: multi-hop money routing toward a plan's seller.
See docs/specs/2026-07-08-payment-chains-design.md."""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import HopSource, TransferHop, TransferHopAudit
from .assets import METHODS


class TransferError(Exception):
    pass


class TransferValidationError(TransferError):
    pass


def _hop_snapshot(hop: TransferHop) -> str:
    return json.dumps({
        "plan_id": hop.plan_id, "chain_id": hop.chain_id,
        "from_user_id": hop.from_user_id, "from_contact_id": hop.from_contact_id,
        "from_name": hop.from_name,
        "to_user_id": hop.to_user_id, "to_contact_id": hop.to_contact_id,
        "to_name": hop.to_name,
        "amount_minor": hop.amount_minor, "currency": hop.currency,
        "occurred_at": hop.occurred_at.isoformat(), "method": hop.method,
        "proof_ref": hop.proof_ref, "note": hop.note,
        "is_terminal": hop.is_terminal, "receipt_status": hop.receipt_status,
        "resolution": hop.resolution,
        "sources": [{"source_hop_id": src.source_hop_id, "amount_minor": src.amount_minor}
                    for src in hop.sources],
    })


def _write_audit(session, hop, action, actor_uid, diff=None):
    session.add(TransferHopAudit(
        plan_id=hop.plan_id, hop_id=hop.id, action=action,
        changed_by_user_id=actor_uid, snapshot=_hop_snapshot(hop),
        diff=json.dumps(diff) if diff else None))


def _one_party(user_id, contact_id, name, side):
    given = [v for v in (user_id, contact_id, (name or "").strip() or None) if v is not None]
    if len(given) != 1:
        raise TransferValidationError(f"exactly one {side}-party required (user, contact or name)")


def consumed(session: Session, hop: TransferHop) -> int:
    """Total drawn from this hop by downstream hops."""
    rows = session.scalars(select(HopSource).where(HopSource.source_hop_id == hop.id)).all()
    return sum(r.amount_minor for r in rows)


def outstanding(session: Session, hop: TransferHop) -> int:
    """Undelivered remainder sitting with this hop's receiver. Terminal, returned
    and fee hops are endpoints — money stopped there, nothing is outstanding."""
    if hop.is_terminal or hop.resolution in ("returned", "fee"):
        return 0
    return hop.amount_minor - consumed(session, hop)


def _receipt_status_for(to_user_id, logged_by_user_id) -> str:
    if to_user_id is not None and to_user_id != logged_by_user_id:
        return "pending"
    return "agreed"


def create_hop(session: Session, *, plan, logged_by_user_id, amount_minor, occurred_at,
               method, to_user_id=None, to_contact_id=None, to_name=None,
               from_user_id=None, from_contact_id=None, from_name=None,
               sources=None, is_terminal=False, resolution=None,
               proof_ref=None, note=None, fx_rate_micro=None,
               funding_source="other") -> TransferHop:
    if amount_minor <= 0:
        raise TransferValidationError("amount must be > 0")
    if method not in METHODS:
        raise TransferValidationError(f"unknown method: {method}")
    if resolution not in (None, "returned", "fee"):
        raise TransferValidationError(f"unknown resolution: {resolution}")
    if from_user_id is None and from_contact_id is None and not (from_name or "").strip():
        from_user_id = logged_by_user_id     # default: logger sent the money
    _one_party(from_user_id, from_contact_id, from_name, "from")
    _one_party(to_user_id, to_contact_id, to_name, "to")

    src_rows = list(sources or [])
    if not src_rows:
        src_rows = [{"source_hop_id": None, "amount_minor": amount_minor}]
    if sum(r["amount_minor"] for r in src_rows) != amount_minor:
        raise TransferValidationError("sources must sum to the hop amount")
    if any(r["amount_minor"] <= 0 for r in src_rows):
        raise TransferValidationError("source amounts must be > 0")

    chain_id = None
    for r in src_rows:
        if r["source_hop_id"] is None:
            continue
        src_hop = session.get(TransferHop, r["source_hop_id"])
        if src_hop is None or src_hop.plan_id != plan.id:
            raise TransferValidationError("source hop not found on this plan")
        if src_hop.is_terminal:
            raise TransferValidationError("cannot draw from a terminal hop")
        if r["amount_minor"] > outstanding(session, src_hop):
            raise TransferValidationError(
                f"source hop {src_hop.id} has only {outstanding(session, src_hop)} outstanding")
        if chain_id is None:
            chain_id = src_hop.chain_id

    hop = TransferHop(
        plan_id=plan.id, chain_id=chain_id,
        from_user_id=from_user_id, from_contact_id=from_contact_id,
        from_name=(from_name or "").strip() or None,
        to_user_id=to_user_id, to_contact_id=to_contact_id,
        to_name=(to_name or "").strip() or None,
        amount_minor=amount_minor, currency=plan.currency,
        occurred_at=occurred_at, method=method, proof_ref=proof_ref, note=note,
        is_terminal=bool(is_terminal), resolution=resolution,
        receipt_status=_receipt_status_for(to_user_id, logged_by_user_id),
        logged_by_user_id=logged_by_user_id)
    session.add(hop)
    session.flush()
    if hop.chain_id is None:
        hop.chain_id = hop.id
    for r in src_rows:
        session.add(HopSource(hop_id=hop.id, source_hop_id=r["source_hop_id"],
                              amount_minor=r["amount_minor"]))
    session.flush()
    if fx_rate_micro is not None:
        from . import fx
        hop.fx_rate_micro = fx_rate_micro
        hop.fx_counter_currency = fx.counter_currency_for(hop.currency)
        session.flush()
    if hop.is_terminal and hop.resolution is None:
        fan_out_terminal(session, plan=plan, hop=hop,
                         acting_user_id=logged_by_user_id,
                         funding_source=funding_source)
    _write_audit(session, hop, "create", logged_by_user_id)
    return hop


def _own_party_user(hop: TransferHop) -> int | None:
    """The from-party as a user id, or None when the origin is a contact/name."""
    return hop.from_user_id


def _prior_consumption(session: Session, hop: TransferHop, *, before_source_id: int) -> int:
    """How much of `hop` was consumed by HopSource rows earlier than the given one."""
    rows = session.scalars(
        select(HopSource).where(HopSource.source_hop_id == hop.id,
                                HopSource.id < before_source_id)).all()
    return sum(r.amount_minor for r in rows)


def resolve_contributions(session: Session, hop: TransferHop) -> list[tuple[int | None, int]]:
    """(user_id, amount) pairs for a hop's money, walked to ultimate origins.
    user_id None = non-user origin (contact / free-text). Greedy oldest-first:
    each upstream hop's own-funds and lineage portions are consumed in
    HopSource.id order, tracking how much earlier consumers already took."""
    def _alloc(h: TransferHop, take: int, taken_before: int) -> list[tuple[int | None, int]]:
        """Allocate `take` units of hop h's money, skipping the first
        `taken_before` units (already claimed by earlier consumers)."""
        out: list[tuple[int | None, int]] = []
        pos = 0
        for src in h.sources:                    # ordered by HopSource.id
            if take <= 0:
                break
            seg = src.amount_minor
            overlap_start = max(pos, taken_before)
            overlap_end = min(pos + seg, taken_before + take)
            grab = overlap_end - overlap_start
            if grab > 0:
                if src.source_hop_id is None:
                    out.append((_own_party_user(h), grab))
                else:
                    up = session.get(TransferHop, src.source_hop_id)
                    out.extend(_alloc(up, grab, overlap_start - pos))
            pos += seg
        return out

    result: list[tuple[int | None, int]] = []
    for src in hop.sources:
        if src.source_hop_id is None:
            result.append((_own_party_user(hop), src.amount_minor))
        else:
            up = session.get(TransferHop, src.source_hop_id)
            prior = _prior_consumption(session, up, before_source_id=src.id)
            result.extend(_alloc(up, src.amount_minor, prior))
    # merge duplicates
    merged: dict[int | None, int] = {}
    for uid, amt in result:
        merged[uid] = merged.get(uid, 0) + amt
    return list(merged.items())


def fan_out_terminal(session: Session, *, plan, hop: TransferHop, acting_user_id,
                     funding_source="other"):
    """Spawn one LedgerEntry per ultimate contributor of a terminal hop.
    Non-user origins are attributed to the hop logger (spec §Attribution)."""
    from .assets import log_payment
    entries = []
    for uid, amt in resolve_contributions(session, hop):
        entry = log_payment(
            session, plan=plan, user_id=uid if uid is not None else hop.logged_by_user_id,
            amount_minor=amt, occurred_at=hop.occurred_at,
            method=hop.method, funding_source=funding_source,
            proof_ref=hop.proof_ref, note=hop.note,
            acting_user_id=acting_user_id)
        entry.source_hop_id = hop.id
        entries.append(entry)
    session.flush()
    return entries
