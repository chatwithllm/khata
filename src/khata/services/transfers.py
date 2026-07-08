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


def respond_receipt(session: Session, *, plan, hop_id, actor_uid, action,
                    amount_minor=None) -> TransferHop:
    """Receipt agreement loop, mirroring assets.respond_amount:
    receiver confirms/counters; the LOGGER (not plan owner) accepts/re-counters —
    the hop is a two-party fact between sender-side logger and receiver."""
    hop = session.get(TransferHop, hop_id)
    if hop is None or hop.plan_id != plan.id:
        raise TransferValidationError("hop not found")
    is_receiver = actor_uid == hop.to_user_id
    is_logger = actor_uid == hop.logged_by_user_id

    if action == "confirm":
        if hop.receipt_status != "pending" or not is_receiver:
            raise TransferValidationError("nothing to confirm")
        hop.receipt_status = "agreed"
        hop.counter_amount_minor = None
    elif action == "accept":
        if hop.receipt_status != "countered" or not is_logger:
            raise TransferValidationError("no counter to accept")
        if hop.counter_amount_minor < consumed(session, hop):
            raise TransferValidationError("counter is below the amount already forwarded")
        hop.amount_minor = hop.counter_amount_minor
        _rebase_own_source(session, hop)
        hop.receipt_status = "agreed"
        hop.counter_amount_minor = None
    elif action == "counter":
        if amount_minor is None or amount_minor <= 0:
            raise TransferValidationError("counter amount must be > 0")
        if hop.receipt_status == "pending" and is_receiver:
            hop.counter_amount_minor = amount_minor
            hop.receipt_status = "countered"
        elif hop.receipt_status == "countered" and is_logger:
            if amount_minor < consumed(session, hop):
                raise TransferValidationError("amount is below the amount already forwarded")
            hop.amount_minor = amount_minor
            _rebase_own_source(session, hop)
            hop.counter_amount_minor = None
            hop.receipt_status = "pending"
        else:
            raise TransferValidationError("not your turn to counter")
    else:
        raise TransferValidationError(f"unknown action: {action}")
    session.flush()
    _write_audit(session, hop, "edit", actor_uid,
                 diff={"receipt": {"action": action, "amount_minor": amount_minor}})
    return hop


def _rebase_own_source(session: Session, hop: TransferHop) -> None:
    """After an amount change, resize the hop's own-funds source row so
    sources still sum to amount_minor. Hops whose upstream sources exceed
    the new amount reject the change."""
    own = [s for s in hop.sources if s.source_hop_id is None]
    upstream = [s for s in hop.sources if s.source_hop_id is not None]
    up_total = sum(s.amount_minor for s in upstream)
    if hop.amount_minor < up_total:
        raise TransferValidationError("amount below the upstream money in this hop")
    if own:
        own[0].amount_minor = hop.amount_minor - up_total
        for extra in own[1:]:
            session.delete(extra)
        if own[0].amount_minor == 0:
            session.delete(own[0])
    elif hop.amount_minor != up_total:
        session.add(HopSource(hop_id=hop.id, source_hop_id=None,
                              amount_minor=hop.amount_minor - up_total))
    session.flush()


def list_receipt_confirmations(session: Session, user_id) -> list[dict]:
    """Hops waiting on THIS user: pending receipts where they're the receiver,
    countered receipts where they're the logger."""
    from ..models import Contact, Plan, User as _User
    hops = session.scalars(select(TransferHop).where(
        ((TransferHop.receipt_status == "pending") & (TransferHop.to_user_id == user_id)) |
        ((TransferHop.receipt_status == "countered") & (TransferHop.logged_by_user_id == user_id))
    )).all()
    out = []
    for h in hops:
        plan = session.get(Plan, h.plan_id)
        if h.from_user_id:
            u = session.get(_User, h.from_user_id)
            from_display = u.display_name if u else None
        elif h.from_contact_id:
            c = session.get(Contact, h.from_contact_id)
            from_display = c.name if c else None
        else:
            from_display = h.from_name
        out.append({"hop_id": h.id, "plan_id": h.plan_id,
                    "plan_name": plan.name if plan else None,
                    "amount_minor": h.amount_minor,
                    "counter_amount_minor": h.counter_amount_minor,
                    "status": h.receipt_status, "from_display": from_display,
                    "logged_at": h.created_at.isoformat() if h.created_at else None})
    return out


def _own_party_user(hop: TransferHop) -> int | None:
    """The from-party as a user id, or None when the origin is a contact/name."""
    return hop.from_user_id


def _prior_consumption(session: Session, hop: TransferHop, *, before_source_id: int) -> int:
    """How much of `hop` was consumed by HopSource rows earlier than the given one."""
    rows = session.scalars(
        select(HopSource).where(HopSource.source_hop_id == hop.id,
                                HopSource.id < before_source_id)).all()
    return sum(r.amount_minor for r in rows)


def _alloc(session: Session, h: TransferHop, take: int, taken_before: int) -> list[tuple[int | None, int]]:
    """Allocate `take` units of hop h's money to ultimate origins, skipping the
    first `taken_before` units (already claimed by earlier consumers). Greedy
    oldest-first over the hop's sources (HopSource.id order)."""
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
                out.extend(_alloc(session, up, grab, overlap_start - pos))
        pos += seg
    return out


def resolve_contributions(session: Session, hop: TransferHop) -> list[tuple[int | None, int]]:
    """(user_id, amount) pairs for a hop's money, walked to ultimate origins.
    user_id None = non-user origin (contact / free-text). Greedy oldest-first:
    each upstream hop's own-funds and lineage portions are consumed in
    HopSource.id order, tracking how much earlier consumers already took."""
    result: list[tuple[int | None, int]] = []
    for src in hop.sources:
        if src.source_hop_id is None:
            result.append((_own_party_user(hop), src.amount_minor))
        else:
            up = session.get(TransferHop, src.source_hop_id)
            prior = _prior_consumption(session, up, before_source_id=src.id)
            result.extend(_alloc(session, up, src.amount_minor, prior))
    # merge duplicates
    merged: dict[int | None, int] = {}
    for uid, amt in result:
        merged[uid] = merged.get(uid, 0) + amt
    return list(merged.items())


def _party_dict(session, user_id, contact_id, name):
    display = name
    if user_id is not None:
        from ..models import User as _User
        u = session.get(_User, user_id)
        display = u.display_name if u else None
    elif contact_id is not None:
        from ..models import Contact
        c = session.get(Contact, contact_id)
        display = c.name if c else None
    return {"user_id": user_id, "contact_id": contact_id, "name": name,
            "display": display}


def _att_count(session: Session, hop_id: int) -> int:
    """Fresh count query — the relationship collection may be stale within a request."""
    from sqlalchemy import func
    from ..models import Attachment
    return session.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.hop_id == hop_id)) or 0


def plan_transfers(session: Session, plan) -> dict:
    from datetime import date
    hops = session.scalars(select(TransferHop)
                           .where(TransferHop.plan_id == plan.id)
                           .order_by(TransferHop.occurred_at, TransferHop.id)).all()
    chains: dict[int, list] = {}
    for h in hops:
        chains.setdefault(h.chain_id, []).append(h)

    in_transit = 0
    out_chains = []
    for cid, chain_hops in chains.items():
        rows, closed = [], True
        for i, h in enumerate(chain_hops):
            out = outstanding(session, h)
            if out > 0:
                closed = False
                in_transit += out
            rows.append({
                "id": h.id, "seq_in_chain": i + 1,
                "from": _party_dict(session, h.from_user_id, h.from_contact_id, h.from_name),
                "to": _party_dict(session, h.to_user_id, h.to_contact_id, h.to_name),
                "amount_minor": h.amount_minor,
                "outstanding_minor": out,
                "consumed_minor": consumed(session, h),
                "occurred_at": h.occurred_at.isoformat(),
                "method": h.method, "note": h.note,
                "has_proof": bool(h.proof_ref) or _att_count(session, h.id) > 0,
                "attachment_count": _att_count(session, h.id),
                "is_terminal": h.is_terminal, "resolution": h.resolution,
                "receipt_status": h.receipt_status,
                "counter_amount_minor": h.counter_amount_minor,
                "days_held": ((date.today() - h.occurred_at.date()).days if out > 0 else 0),
                "logged_by_user_id": h.logged_by_user_id,
                "sources": [{"source_hop_id": s_.source_hop_id,
                             "amount_minor": s_.amount_minor} for s_ in h.sources]})
        out_chains.append({"chain_id": cid, "closed": closed, "hops": rows})
    out_chains.sort(key=lambda c: c["hops"][0]["occurred_at"], reverse=True)

    # in-transit money attributed to its ultimate origin: each open hop's
    # outstanding is the unconsumed TAIL of its money (greedy consumers take the
    # head), so allocate starting after the consumed prefix. Non-user origins
    # fall back to the hop logger (same rule as terminal fan-out).
    transit_by: dict[int, int] = {}
    for h in hops:
        out = outstanding(session, h)
        if out <= 0:
            continue
        for uid, amt in _alloc(session, h, out, consumed(session, h)):
            uid = uid if uid is not None else h.logged_by_user_id
            transit_by[uid] = transit_by.get(uid, 0) + amt
    from ..models import User as _User
    in_transit_by_contributor = []
    for uid, amt in sorted(transit_by.items(), key=lambda kv: kv[1], reverse=True):
        u = session.get(_User, uid)
        in_transit_by_contributor.append({
            "user_id": uid, "display": u.display_name if u else None,
            "amount_minor": amt})

    return {"in_transit_minor": in_transit, "chains": out_chains,
            "in_transit_by_contributor": in_transit_by_contributor}


def update_hop(session: Session, *, plan, hop_id, acting_user_id,
               amount_minor=None, occurred_at=None, method=None,
               proof_ref=None, note=None, fx_rate_micro=None) -> TransferHop:
    hop = session.get(TransferHop, hop_id)
    if hop is None or hop.plan_id != plan.id:
        raise TransferValidationError("hop not found")
    diff = {}
    if amount_minor is not None and amount_minor != hop.amount_minor:
        if amount_minor <= 0:
            raise TransferValidationError("amount must be > 0")
        if amount_minor < consumed(session, hop):
            raise TransferValidationError("amount below what downstream hops already consumed")
        if hop.is_terminal:
            raise TransferValidationError(
                "edit a terminal hop by deleting and re-logging it (entries were fanned out)")
        diff["amount_minor"] = {"old": hop.amount_minor, "new": amount_minor}
        hop.amount_minor = amount_minor
        _rebase_own_source(session, hop)
        if hop.to_user_id and hop.to_user_id != acting_user_id:
            hop.receipt_status = "pending"          # re-opens receipt agreement
            hop.counter_amount_minor = None
    if occurred_at is not None:
        diff["occurred_at"] = {"old": hop.occurred_at.isoformat(),
                               "new": occurred_at.isoformat()}
        hop.occurred_at = occurred_at
    if method is not None:
        if method not in METHODS:
            raise TransferValidationError(f"unknown method: {method}")
        diff["method"] = {"old": hop.method, "new": method}
        hop.method = method
    if proof_ref is not None:
        hop.proof_ref = proof_ref
    if note is not None:
        hop.note = note
    if fx_rate_micro is not None:
        from . import fx
        hop.fx_rate_micro = fx_rate_micro
        hop.fx_counter_currency = fx.counter_currency_for(hop.currency)
    session.flush()
    if diff:
        _write_audit(session, hop, "edit", acting_user_id, diff)
    return hop


def delete_hop(session: Session, *, plan, hop_id, acting_user_id) -> None:
    hop = session.get(TransferHop, hop_id)
    if hop is None or hop.plan_id != plan.id:
        raise TransferValidationError("hop not found")
    if consumed(session, hop) > 0:
        raise TransferValidationError("downstream hops draw from this one — unwind them first")
    if hop.is_terminal:
        from .assets import delete_ledger_entry
        from ..models import LedgerEntry
        entries = session.scalars(select(LedgerEntry).where(
            LedgerEntry.source_hop_id == hop.id)).all()
        for e in entries:
            delete_ledger_entry(session, plan=plan, entry_id=e.id,
                                acting_user_id=acting_user_id)
    _write_audit(session, hop, "delete", acting_user_id)
    session.flush()
    session.delete(hop)
    session.flush()


def resolve_remainder(session: Session, *, plan, hop_id, acting_user_id, action,
                      occurred_at, amount_minor=None, method="transfer",
                      note=None) -> TransferHop:
    """Close (part of) a hop's outstanding remainder: send it back to the origin
    party ('return') or write it off as a fee kept by the holder ('fee')."""
    hop = session.get(TransferHop, hop_id)
    if hop is None or hop.plan_id != plan.id:
        raise TransferValidationError("hop not found")
    if action not in ("return", "fee"):
        raise TransferValidationError(f"unknown action: {action}")
    out = outstanding(session, hop)
    amt = amount_minor if amount_minor is not None else out
    if amt <= 0 or amt > out:
        raise TransferValidationError(f"amount must be within outstanding ({out})")

    # Money flows FROM the current holder (hop's receiver) back/off.
    holder = dict(from_user_id=hop.to_user_id, from_contact_id=hop.to_contact_id,
                  from_name=hop.to_name)
    if action == "return":
        dest = dict(to_user_id=hop.from_user_id, to_contact_id=hop.from_contact_id,
                    to_name=hop.from_name)
        resolution = "returned"
    else:
        dest = dict(to_name=(note or "fee"))
        resolution = "fee"

    res_hop = create_hop(session, plan=plan, logged_by_user_id=acting_user_id,
                         amount_minor=amt, occurred_at=occurred_at, method=method,
                         sources=[{"source_hop_id": hop.id, "amount_minor": amt}],
                         resolution=resolution, note=note, **holder, **dest)

    if action == "fee":
        from .assets import log_payment
        for uid, part in resolve_contributions(session, res_hop):
            entry = log_payment(
                session, plan=plan,
                user_id=uid if uid is not None else acting_user_id,
                amount_minor=part, occurred_at=occurred_at, method=method,
                funding_source="other", note=note or "transfer fee",
                acting_user_id=acting_user_id)
            entry.kind = "transfer_fee"
            entry.source_hop_id = res_hop.id
        session.flush()
    return res_hop


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
