from datetime import date, datetime, timezone

from flask import Blueprint, g, jsonify, request

from ..models import Plan
from ..money import format_minor, to_minor
from ..services import assets
from ..services.assets import PlanError
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


def _summary(plan: Plan) -> dict:
    return {
        "id": plan.id, "type": plan.type, "name": plan.name,
        "currency": plan.currency, "status": plan.status,
        "total_price_minor": plan.asset.total_price_minor if plan.asset else None,
    }


def _detail(plan: Plan) -> dict:
    return {"plan": _summary(plan), "state": assets.asset_state(g.db, plan)}


def _owned_plan(user, plan_id):
    plan = g.db.get(Plan, plan_id)
    if plan is None:
        return None, (jsonify(error="not_found"), 404)
    if plan.owner_user_id != user.id:
        return None, (jsonify(error="forbidden"), 403)
    return plan, None


@bp.post("")
def create():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    currency = (data.get("currency") or "INR").upper()
    try:
        total = to_minor(data.get("total_price", ""), currency)
        plan = assets.create_asset_plan(g.db, owner_id=user.id, name=data.get("name", ""),
                                        currency=currency, total_price_minor=total)
        items = data.get("installments") or []
        if items:
            assets.set_installments(g.db, plan=plan, items=_parse_items(items, currency))
        g.db.commit()
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(_detail(plan)), 201


@bp.get("")
def index():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(plans=[_summary(p) for p in assets.list_plans(g.db, user.id)]), 200


@bp.get("/<int:plan_id>")
def detail(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
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
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        amount = to_minor(data.get("amount", ""), plan.currency)
        occurred = (datetime.fromisoformat(data["occurred_at"])
                    if data.get("occurred_at") else datetime.now(timezone.utc))
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
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
