from datetime import date, datetime, timezone

from flask import Blueprint, g, jsonify, request

from ..models import Plan, User
from ..money import format_minor, pct_to_bps, to_minor
from ..services import assets, loans, sharing
from ..services.assets import PlanError
from ..services.loans import LoanError
from .auth import current_user

bp = Blueprint("plans", __name__, url_prefix="/api/plans")


def _parse_items(items, currency):
    out = []
    for it in items:
        out.append({
            "amount_minor": to_minor(it.get("amount", ""), currency),
            "due_date": date.fromisoformat(it["due_date"]) if it.get("due_date") else None,
            "note": it.get("note"),
        })
    return out


def _parse_dt(v):
    dt = datetime.fromisoformat(v) if v else datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _entry_json(entry, plan):
    return {"id": entry.id, "kind": entry.kind, "direction": entry.direction,
            "amount_minor": entry.amount_minor,
            "amount_display": format_minor(entry.amount_minor, plan.currency),
            "occurred_at": entry.occurred_at.isoformat(),
            "method": entry.method, "funding_source": entry.funding_source}


def _summary(plan: Plan) -> dict:
    base = {"id": plan.id, "type": plan.type, "name": plan.name,
            "currency": plan.currency, "status": plan.status}
    if plan.type == "loan" and plan.loan is not None:
        base.update({"direction": plan.loan.direction, "interest_type": plan.loan.interest_type,
                     "rate_bps": plan.loan.rate_bps, "counterparty": plan.loan.counterparty})
    else:
        base["total_price_minor"] = plan.asset.total_price_minor if plan.asset else None
    return base


def _detail(plan: Plan) -> dict:
    if plan.type == "loan":
        state = loans.loan_state(g.db, plan.loan, as_of=date.today())
    else:
        state = assets.asset_state(g.db, plan)
    return {"plan": _summary(plan), "state": state}


def _owned_plan(user, plan_id):
    plan = g.db.get(Plan, plan_id)
    if plan is None:
        return None, (jsonify(error="not_found"), 404)
    if plan.owner_user_id != user.id:
        return None, (jsonify(error="forbidden"), 403)
    return plan, None


def _accessible_plan(user, plan_id):
    plan = g.db.get(Plan, plan_id)
    if plan is None:
        return None, (jsonify(error="not_found"), 404)
    if not sharing.accessible(g.db, plan=plan, user_id=user.id):
        return None, (jsonify(error="forbidden"), 403)
    return plan, None


@bp.post("")
def create():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    ptype = (data.get("type") or "asset").lower()
    currency = (data.get("currency") or "INR").upper()
    try:
        if ptype == "loan":
            interest_type = (data.get("interest_type") or "none")
            plan = loans.create_loan_plan(
                g.db, owner_id=user.id, name=data.get("name", ""), currency=currency,
                direction=data.get("direction", ""), counterparty=data.get("counterparty"),
                interest_type=interest_type,
                rate_bps=pct_to_bps(data.get("rate", "0")) if interest_type != "none" else 0,
                start_date=date.fromisoformat(data["start_date"]) if data.get("start_date") else date.today(),
                tenure_months=data.get("tenure_months"))
        else:
            total = to_minor(data.get("total_price", ""), currency)
            plan = assets.create_asset_plan(g.db, owner_id=user.id, name=data.get("name", ""),
                                            currency=currency, total_price_minor=total)
            items = data.get("installments") or []
            if items:
                assets.set_installments(g.db, plan=plan, items=_parse_items(items, currency))
        g.db.commit()
    except (PlanError, LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(_detail(plan)), 201


@bp.get("")
def index():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    owned, member = sharing.user_plans(g.db, user.id)
    return jsonify(plans=[_summary(p) for p in owned + member]), 200


@bp.get("/<int:plan_id>")
def detail(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return err
    return jsonify(_detail(plan)), 200


@bp.post("/<int:plan_id>/installments")
def installments(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        assets.set_installments(g.db, plan=plan,
                                items=_parse_items(data.get("installments") or [], plan.currency))
        g.db.commit()
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(_detail(plan)), 200


@bp.post("/<int:plan_id>/payments")
def payment(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        amount = to_minor(data.get("amount", ""), plan.currency)
        occurred = _parse_dt(data.get("occurred_at"))
        entry = assets.log_payment(
            g.db, plan=plan, user_id=user.id, amount_minor=amount, occurred_at=occurred,
            method=data.get("method", ""), funding_source=data.get("funding_source", ""),
            proof_ref=data.get("proof_ref"), note=data.get("note"))
        g.db.commit()
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(
        entry={"id": entry.id, "amount_minor": entry.amount_minor,
               "amount_display": format_minor(entry.amount_minor, plan.currency),
               "method": entry.method, "funding_source": entry.funding_source},
        state=assets.asset_state(g.db, plan)), 201


@bp.post("/<int:plan_id>/loan/disbursements")
def loan_disbursement(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "loan":
        return jsonify(error="not_a_loan"), 400
    data = request.get_json(silent=True) or {}
    try:
        entry = loans.add_disbursement(
            g.db, plan=plan, user_id=user.id,
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"))
        g.db.commit()
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=loans.loan_state(g.db, plan.loan, as_of=date.today())), 201


@bp.post("/<int:plan_id>/members")
def add_member(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        m = sharing.add_member(g.db, plan=plan, email=data.get("email", ""))
        g.db.commit()
    except sharing.UserNotFound:
        g.db.rollback()
        return jsonify(error="user_not_found"), 404
    except sharing.AlreadyMember:
        g.db.rollback()
        return jsonify(error="already_member"), 409
    except sharing.MemberError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    u = g.db.get(User, m.user_id)
    return jsonify(member={"user_id": u.id, "email": u.email,
                           "display_name": u.display_name, "role": m.role}), 201


@bp.get("/<int:plan_id>/members")
def get_members(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return err
    return jsonify(members=sharing.list_members(g.db, plan)), 200


@bp.delete("/<int:plan_id>/members/<int:member_user_id>")
def delete_member(plan_id, member_user_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    try:
        sharing.remove_member(g.db, plan=plan, user_id=member_user_id)
        g.db.commit()
    except sharing.MemberError:
        g.db.rollback()
        return jsonify(error="not_a_member"), 404
    return jsonify(ok=True), 200


@bp.post("/<int:plan_id>/loan/entries")
def loan_entry(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "loan":
        return jsonify(error="not_a_loan"), 400
    data = request.get_json(silent=True) or {}
    try:
        entry = loans.log_loan_entry(
            g.db, plan=plan, user_id=user.id, kind=data.get("kind", ""),
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")),
            method=data.get("method"), note=data.get("note"))
        g.db.commit()
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=loans.loan_state(g.db, plan.loan, as_of=date.today())), 201
