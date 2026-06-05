from datetime import date, datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request

from ..models import Plan, User
from ..money import format_minor, pct_to_bps, to_micro, to_minor
from ..services import assets, chits, feed, holdings, loans, retirement, sharing
from ..services.assets import PlanError
from ..services.loans import LoanError
from ..services.holdings import HoldingError
from ..services.chits import ChitError
from ..services.retirement import RetirementError
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
            "quantity_micro": entry.quantity_micro,
            "method": entry.method, "funding_source": entry.funding_source}


def _summary(plan: Plan) -> dict:
    base = {"id": plan.id, "type": plan.type, "name": plan.name,
            "currency": plan.currency, "status": plan.status}
    if plan.type == "loan" and plan.loan is not None:
        base.update({"direction": plan.loan.direction, "interest_type": plan.loan.interest_type,
                     "rate_bps": plan.loan.rate_bps, "counterparty": plan.loan.counterparty,
                     "secured": plan.loan.secured,
                     "start_date": plan.loan.start_date.isoformat() if plan.loan.start_date else None,
                     "tenure_months": plan.loan.tenure_months})
    elif plan.type == "holding" and plan.holding is not None:
        base.update({"asset_class": plan.holding.asset_class, "unit": plan.holding.unit,
                     "symbol": plan.holding.symbol,
                     "current_price_minor": plan.holding.current_price_minor})
    elif plan.type == "chit" and plan.chit is not None:
        base.update({"chit_value_minor": plan.chit.chit_value_minor,
                     "n_members": plan.chit.n_members,
                     "commission_bps": plan.chit.commission_bps})
    elif plan.type == "retirement" and plan.retirement is not None:
        base.update({"current_age": plan.retirement.current_age,
                     "retirement_age": plan.retirement.retirement_age})
    else:
        base["total_price_minor"] = plan.asset.total_price_minor if plan.asset else None
    return base


def _detail(plan: Plan) -> dict:
    if plan.type == "loan":
        state = loans.loan_state(g.db, plan.loan, as_of=date.today())
    elif plan.type == "holding":
        state = holdings.holding_state(g.db, plan.holding)
    elif plan.type == "chit":
        state = chits.chit_state(g.db, plan.chit)
    elif plan.type == "retirement":
        state = retirement.retirement_state(g.db, plan.retirement)
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


def _payer_uid(plan, data, default_uid):
    """Resolve who actually paid/contributed an entry: an optional `paid_by` user id
    that must be attached to the plan; defaults to the caller. Lets joint plans attribute
    each entry to the real contributor (for audit + ownership shares). Uses on_plan so an
    invited-but-not-yet-accepted contributor can still be tagged on entries."""
    pb = data.get("paid_by")
    if pb in (None, ""):
        return default_uid
    uid = int(pb)
    if not sharing.on_plan(g.db, plan=plan, user_id=uid):
        raise ValueError("paid_by must be a member of this plan")
    return uid


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
            if data.get("collateral_plan_id"):
                loans.set_collateral(g.db, plan=plan,
                                     collateral_plan_id=data.get("collateral_plan_id"))
        elif ptype == "holding":
            plan = holdings.create_holding_plan(
                g.db, owner_id=user.id, name=data.get("name", ""), currency=currency,
                asset_class=data.get("asset_class", ""), unit=data.get("unit", ""),
                symbol=data.get("symbol"), purity=data.get("purity"))
        elif ptype == "chit":
            plan = chits.create_chit_plan(
                g.db, owner_id=user.id, name=data.get("name", ""), currency=currency,
                chit_value_minor=to_minor(data.get("chit_value", ""), currency),
                n_members=int(data.get("n_members", 0)),
                commission_bps=pct_to_bps(data.get("commission", "0")),
                start_date=date.fromisoformat(data["start_date"]) if data.get("start_date") else date.today())
        elif ptype == "retirement":
            plan = retirement.create_retirement_plan(
                g.db, owner_id=user.id, name=data.get("name", ""), currency=currency,
                current_age=int(data.get("current_age", 0)),
                retirement_age=int(data.get("retirement_age", 0)),
                current_balance_minor=to_minor(data.get("current_balance", "0"), currency),
                monthly_contribution_minor=to_minor(data.get("monthly_contribution", "0"), currency),
                employer_match_bps=pct_to_bps(data.get("employer_match", "0")),
                annual_return_bps=pct_to_bps(data.get("annual_return", "8")),
                inflation_bps=pct_to_bps(data.get("inflation", "6")))
        else:
            total = to_minor(data.get("total_price", ""), currency)
            plan = assets.create_asset_plan(g.db, owner_id=user.id, name=data.get("name", ""),
                                            currency=currency, total_price_minor=total)
            items = data.get("installments") or []
            if items:
                assets.set_installments(g.db, plan=plan, items=_parse_items(items, currency))
        g.db.commit()
    except (PlanError, LoanError, HoldingError, ChitError, RetirementError, ValueError, TypeError) as e:
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


@bp.patch("/<int:plan_id>")
def update_plan(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        if plan.type == "loan":
            kw = {}
            if "name" in data:
                kw["name"] = data.get("name")
            for k in ("direction", "counterparty", "interest_type"):
                if k in data:
                    kw[k] = data.get(k)
            if "rate" in data:
                kw["rate_bps"] = pct_to_bps(data.get("rate", "0"))
            if "start_date" in data:
                kw["start_date"] = date.fromisoformat(data["start_date"]) if data.get("start_date") else None
            if "tenure_months" in data:
                kw["tenure_months"] = int(data["tenure_months"]) if data.get("tenure_months") not in (None, "") else None
            loans.update_loan_terms(g.db, plan=plan, **kw)
        else:
            if "name" in data and (data.get("name") or "").strip():
                plan.name = data.get("name").strip()
        g.db.commit()
    except (LoanError, PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(_detail(plan)), 200


@bp.delete("/<int:plan_id>")
def delete_plan_route(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    try:
        assets.delete_plan(g.db, plan=plan)
        g.db.commit()
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(ok=True), 200


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
            g.db, plan=plan, user_id=_payer_uid(plan, data, user.id), amount_minor=amount, occurred_at=occurred,
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


@bp.patch("/<int:plan_id>/entries/<int:entry_id>")
def update_entry(plan_id, entry_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only mutation
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        fields = {}
        if "amount" in data:
            fields["amount_minor"] = to_minor(data.get("amount", ""), plan.currency)
        if "occurred_at" in data:
            fields["occurred_at"] = _parse_dt(data.get("occurred_at"))
        for k in ("method", "funding_source", "note"):
            if k in data:
                fields[k] = data.get(k)
        if "paid_by" in data:
            fields["logged_by_user_id"] = _payer_uid(plan, data, plan.owner_user_id)
        assets.update_ledger_entry(g.db, plan=plan, entry_id=entry_id, **fields)
        g.db.commit()
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(_detail(plan)), 200


@bp.delete("/<int:plan_id>/entries/<int:entry_id>")
def delete_entry(plan_id, entry_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    try:
        assets.delete_ledger_entry(g.db, plan=plan, entry_id=entry_id)
        g.db.commit()
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(_detail(plan)), 200


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
            g.db, plan=plan, user_id=_payer_uid(plan, data, user.id),
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"))
        g.db.commit()
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=loans.loan_state(g.db, plan.loan, as_of=date.today())), 201


@bp.post("/<int:plan_id>/loan/collateral")
def loan_collateral(plan_id):
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
        loans.set_collateral(g.db, plan=plan, collateral_plan_id=data.get("collateral_plan_id"))
        g.db.commit()
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(state=loans.loan_state(g.db, plan.loan, as_of=date.today())), 200


@bp.post("/<int:plan_id>/holding/buys")
def holding_buy(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "holding":
        return jsonify(error="not_a_holding"), 400
    data = request.get_json(silent=True) or {}
    try:
        entry = holdings.add_buy(
            g.db, plan=plan, user_id=user.id,
            quantity_micro=to_micro(data.get("quantity", "")),
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"))
        g.db.commit()
    except (HoldingError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=holdings.holding_state(g.db, plan.holding)), 201


@bp.post("/<int:plan_id>/holding/sells")
def holding_sell(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "holding":
        return jsonify(error="not_a_holding"), 400
    data = request.get_json(silent=True) or {}
    try:
        entry = holdings.add_sell(
            g.db, plan=plan, user_id=user.id,
            quantity_micro=to_micro(data.get("quantity", "")),
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"))
        g.db.commit()
    except (HoldingError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=holdings.holding_state(g.db, plan.holding)), 201


@bp.post("/<int:plan_id>/holding/quote")
def holding_quote(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "holding":
        return jsonify(error="not_a_holding"), 400
    data = request.get_json(silent=True) or {}
    try:
        holdings.set_quote(g.db, plan=plan,
                           price_minor=to_minor(data.get("price", ""), plan.currency),
                           as_of=_parse_dt(data.get("as_of")))
        g.db.commit()
    except (HoldingError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(state=holdings.holding_state(g.db, plan.holding)), 200


@bp.post("/<int:plan_id>/holding/refresh-quote")
def holding_refresh_quote(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "holding":
        return jsonify(error="not_a_holding"), 400
    cfg = current_app.config["KHATA"]
    if not feed.feed_enabled(cfg):
        return jsonify(error="feed_not_configured"), 503
    provider = current_app.config["PRICE_PROVIDER"]
    try:
        price = provider(plan.holding.asset_class, plan.holding.symbol, plan.currency, cfg.price_feed)
        holdings.set_quote(g.db, plan=plan, price_minor=price, as_of=_parse_dt(None))
        g.db.commit()
    except (feed.FeedError, HoldingError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="feed_error", detail=str(e)), 502
    return jsonify(state=holdings.holding_state(g.db, plan.holding)), 200


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
                           "display_name": u.display_name, "role": m.role,
                           "status": m.status}), 201


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


@bp.post("/<int:plan_id>/chit/entries")
def chit_entry(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "chit":
        return jsonify(error="not_a_chit"), 400
    data = request.get_json(silent=True) or {}
    try:
        entry = chits.log_chit_entry(
            g.db, plan=plan, user_id=user.id, kind=data.get("kind", ""),
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"))
        g.db.commit()
    except (ChitError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=chits.chit_state(g.db, plan.chit)), 201


@bp.get("/<int:plan_id>/chit/dividend")
def chit_dividend(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return err
    if plan.type != "chit":
        return jsonify(error="not_a_chit"), 400
    try:
        bid = to_minor(request.args.get("bid", ""), plan.currency)
    except (ValueError, TypeError) as e:
        return jsonify(error="invalid", detail=str(e)), 400
    if bid <= 0 or bid > plan.chit.chit_value_minor:
        return jsonify(error="invalid", detail="bid must be > 0 and <= chit value"), 400
    return jsonify(chits.auction_dividend(
        chit_value_minor=plan.chit.chit_value_minor, commission_bps=plan.chit.commission_bps,
        n_members=plan.chit.n_members, winning_bid_minor=bid)), 200


@bp.post("/<int:plan_id>/retirement/update")
def retirement_update(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "retirement":
        return jsonify(error="not_a_retirement"), 400
    data = request.get_json(silent=True) or {}
    fields = {}
    for src, dst, conv in [
            ("current_balance", "current_balance_minor", lambda v: to_minor(v, plan.currency)),
            ("monthly_contribution", "monthly_contribution_minor", lambda v: to_minor(v, plan.currency)),
            ("employer_match", "employer_match_bps", pct_to_bps),
            ("annual_return", "annual_return_bps", pct_to_bps),
            ("inflation", "inflation_bps", pct_to_bps),
            ("current_age", "current_age", int), ("retirement_age", "retirement_age", int)]:
        if data.get(src) not in (None, ""):
            fields[dst] = conv(data.get(src))
    try:
        retirement.update_retirement(g.db, plan=plan, **fields)
        g.db.commit()
    except (RetirementError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(state=retirement.retirement_state(g.db, plan.retirement)), 200
