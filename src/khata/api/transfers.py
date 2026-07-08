from flask import Blueprint, g, jsonify, request

from ..money import to_minor
from ..services import sharing, transfers
from ..services.transfers import TransferError
from .auth import current_user
from .plans import _accessible_plan, _writable_plan, _parse_dt, _fx_rate_arg, _FxRateArgError

bp = Blueprint("transfers", __name__, url_prefix="/api/plans")


def _hop_json(hop):
    return {"id": hop.id, "chain_id": hop.chain_id, "amount_minor": hop.amount_minor,
            "is_terminal": hop.is_terminal, "receipt_status": hop.receipt_status,
            "resolution": hop.resolution}


def _auto_terminal(plan, to_user_id, to_contact_id):
    if to_contact_id and plan.asset and plan.asset.seller_contact_id == to_contact_id:
        return True
    if to_user_id and sharing.role_of(g.db, plan=plan, user_id=to_user_id) == "seller":
        return True
    return False


@bp.post("/<int:plan_id>/hops")
def create_hop(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _writable_plan(user, plan_id)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    try:
        to_uid = int(d["to_user_id"]) if d.get("to_user_id") else None
        to_cid = int(d["to_contact_id"]) if d.get("to_contact_id") else None
        sources = [{"source_hop_id": (int(r["source_hop_id"]) if r.get("source_hop_id") else None),
                    "amount_minor": to_minor(r.get("amount", ""), plan.currency)}
                   for r in (d.get("sources") or [])]
        hop = transfers.create_hop(
            g.db, plan=plan, logged_by_user_id=user.id,
            amount_minor=to_minor(d.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(d.get("occurred_at")),
            method=d.get("method", ""),
            to_user_id=to_uid, to_contact_id=to_cid, to_name=d.get("to_name"),
            from_user_id=int(d["from_user_id"]) if d.get("from_user_id") else None,
            from_contact_id=int(d["from_contact_id"]) if d.get("from_contact_id") else None,
            from_name=d.get("from_name"),
            sources=sources or None,
            is_terminal=bool(d.get("is_terminal")) or _auto_terminal(plan, to_uid, to_cid),
            funding_source=d.get("funding_source") or "other",
            proof_ref=d.get("proof_ref"), note=d.get("note"),
            fx_rate_micro=_fx_rate_arg(d))
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
    except (TransferError, ValueError, TypeError, KeyError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(hop=_hop_json(hop), transfers=transfers.plan_transfers(g.db, plan)), 201


@bp.get("/<int:plan_id>/hops")
def list_hops(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return err
    return jsonify(transfers.plan_transfers(g.db, plan)), 200


@bp.patch("/<int:plan_id>/hops/<int:hop_id>")
def patch_hop(plan_id, hop_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _writable_plan(user, plan_id)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    try:
        fields = {}
        if "amount" in d:
            fields["amount_minor"] = to_minor(d.get("amount", ""), plan.currency)
        if "occurred_at" in d:
            fields["occurred_at"] = _parse_dt(d.get("occurred_at"))
        for k in ("method", "proof_ref", "note"):
            if k in d:
                fields[k] = d.get(k)
        if "fx_rate_micro" in d:
            fields["fx_rate_micro"] = _fx_rate_arg(d)
        transfers.update_hop(g.db, plan=plan, hop_id=hop_id,
                             acting_user_id=user.id, **fields)
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
    except (TransferError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(transfers.plan_transfers(g.db, plan)), 200


@bp.delete("/<int:plan_id>/hops/<int:hop_id>")
def delete_hop(plan_id, hop_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _writable_plan(user, plan_id)
    if err:
        return err
    try:
        transfers.delete_hop(g.db, plan=plan, hop_id=hop_id, acting_user_id=user.id)
        g.db.commit()
    except (TransferError, ValueError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(transfers.plan_transfers(g.db, plan)), 200


@bp.post("/<int:plan_id>/hops/<int:hop_id>/receipt")
def receipt(plan_id, hop_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)   # receivers may be seller-role: receipts allowed
    if err:
        return err
    d = request.get_json(silent=True) or {}
    try:
        amt = to_minor(d.get("amount", ""), plan.currency) if d.get("amount") else None
        transfers.respond_receipt(g.db, plan=plan, hop_id=hop_id, actor_uid=user.id,
                                  action=(d.get("action") or "").lower(), amount_minor=amt)
        g.db.commit()
    except (TransferError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(transfers.plan_transfers(g.db, plan)), 200


@bp.post("/<int:plan_id>/hops/<int:hop_id>/resolve")
def resolve(plan_id, hop_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _writable_plan(user, plan_id)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    try:
        amt = to_minor(d.get("amount", ""), plan.currency) if d.get("amount") else None
        transfers.resolve_remainder(
            g.db, plan=plan, hop_id=hop_id, acting_user_id=user.id,
            action=(d.get("action") or "").lower(),
            occurred_at=_parse_dt(d.get("occurred_at")),
            amount_minor=amt, method=d.get("method") or "transfer",
            note=d.get("note"))
        g.db.commit()
    except (TransferError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(transfers.plan_transfers(g.db, plan)), 200
