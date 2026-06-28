from datetime import date, datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request

from ..models import Plan, User, LedgerEntry
from ..money import format_minor, pct_to_bps, to_micro, to_minor
from ..services import assets, attachments, chits, contacts, feed, fx, holdings, loan_groups, loans, retirement, sharing, sharing_links
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


class _FxRateArgError(ValueError):
    """Invalid explicit fx_rate_micro — maps to 422 (not the generic 400)."""


def _fx_rate_arg(data):
    """Optional explicit snapshot rate from the client: a positive int
    (counter-per-entry ×1e6) or None. bool is an int in Python — reject it."""
    v = data.get("fx_rate_micro")
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise _FxRateArgError("fx_rate_micro must be a positive integer (×1e6)")
    return v


def _entry_json(entry, plan):
    audit = [{"action": a.action, "changed_by_user_id": a.changed_by_user_id,
              "changed_at": a.changed_at.isoformat(), "diff": a.diff}
             for a in (entry.audit or []) if a.action != "create"]
    return {"id": entry.id, "kind": entry.kind, "direction": entry.direction,
            "amount_minor": entry.amount_minor,
            "amount_display": format_minor(entry.amount_minor, plan.currency),
            "occurred_at": entry.occurred_at.isoformat(),
            "quantity_micro": entry.quantity_micro,
            "method": entry.method, "funding_source": entry.funding_source,
            # FX snapshot (same trio as the state ledgers — counter value DERIVED)
            "fx_rate_micro": entry.fx_rate_micro,
            "fx_counter_currency": entry.fx_counter_currency,
            "counter_value_minor": (fx.convert(entry.amount_minor, rate_micro=entry.fx_rate_micro)
                                    if entry.fx_rate_micro else None),
            "audit": audit}


def _summary(plan: Plan) -> dict:
    base = {"id": plan.id, "type": plan.type, "name": plan.name,
            "currency": plan.currency, "status": plan.status}
    if plan.type == "loan" and plan.loan is not None:
        base.update({"direction": plan.loan.direction, "interest_type": plan.loan.interest_type,
                     "rate_bps": plan.loan.rate_bps, "counterparty": plan.loan.counterparty,
                     "secured": plan.loan.secured, "kind": plan.loan.kind,
                     "start_date": plan.loan.start_date.isoformat() if plan.loan.start_date else None,
                     "tenure_months": plan.loan.tenure_months,
                     "collateral_qty_micro": plan.loan.collateral_qty_micro,
                     "collateral_unit": plan.loan.collateral_unit,
                     "collateral_rate_minor": plan.loan.collateral_rate_minor,
                     "collateral_rate_basis": plan.loan.collateral_rate_basis,
                     "collateral_value_minor": plan.loan.collateral_value_minor,
                     "contact_id": plan.loan.contact_id})
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
    _u = current_user()
    viewer_id = _u.id if _u else None
    if plan.type == "loan":
        state = loans.loan_state(g.db, plan.loan, as_of=date.today())
    elif plan.type == "holding":
        state = holdings.holding_state(g.db, plan.holding)
    elif plan.type == "chit":
        state = chits.chit_state(g.db, plan.chit)
    elif plan.type == "retirement":
        state = retirement.retirement_state(g.db, plan.retirement)
    else:
        state = assets.asset_state(g.db, plan, viewer_id=viewer_id)
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


def _gold_collateral(data, currency):
    """Build the inline-collateral dict from a request body's gold_* fields (or None when
    there's nothing to set). Weight → micro; rate/value → minor."""
    keys = ("gold_weight", "gold_value", "gold_rate")
    if not any(data.get(k) for k in keys):
        return None
    return {
        "qty_micro": to_micro(data.get("gold_weight")) if data.get("gold_weight") else None,
        "unit": data.get("gold_unit") or "gram",
        "rate_minor": to_minor(data.get("gold_rate"), currency) if data.get("gold_rate") else None,
        "rate_basis": data.get("gold_rate_basis") or "per_gram",
        "value_minor": to_minor(data.get("gold_value"), currency) if data.get("gold_value") else None,
    }


def _editable_entry(user, plan_id, entry_id):
    """Resolve a ledger entry the user may edit/delete: the plan must be accessible, and
    the user must be the plan OWNER or the entry's own contributor (logged_by_user_id) —
    so a contributor can manage their own contribution. Returns (plan, entry, is_owner, err)."""
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return None, None, False, err
    entry = g.db.get(LedgerEntry, entry_id)
    if entry is None or entry.plan_id != plan.id:
        return None, None, False, (jsonify(error="not_found"), 404)
    is_owner = (user.id == plan.owner_user_id)
    if not is_owner and user.id != entry.logged_by_user_id:
        return None, None, False, (jsonify(error="forbidden",
                                           detail="only the owner or this entry's contributor can edit it"), 403)
    return plan, entry, is_owner, None


def _funding_plan_id(data, user):
    """Resolve an optional `funding_plan_id` (the plan that funded this payment, e.g. the
    loan an asset contribution came from). Must be a plan the user can access. Empty → None."""
    fp = data.get("funding_plan_id")
    if fp in (None, "", 0, "0"):
        return None
    p = g.db.get(Plan, int(fp))
    if p is None or not sharing.accessible(g.db, plan=p, user_id=user.id):
        raise ValueError("funding source must be a plan you can access")
    return p.id


@bp.post("")
def create():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    ptype = (data.get("type") or "asset").lower()
    if ptype not in {"asset", "loan", "holding", "chit", "retirement"}:
        return jsonify(error="invalid", detail=f"unknown plan type: {ptype!r}"), 400
    if not (data.get("name") or "").strip():
        return jsonify(error="invalid", detail="name is required"), 400
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
                tenure_months=data.get("tenure_months"), kind=data.get("loan_kind") or "personal",
                collateral=_gold_collateral(data, currency))
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


@bp.get("/loans/grouped")
def loans_grouped():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    base = getattr(user, "base_currency", None) or "INR"
    return jsonify(loan_groups.grouped_loans(g.db, owner_id=user.id, base_currency=base)), 200


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
            if "loan_kind" in data:
                kw["kind"] = data.get("loan_kind")
            # inline gold collateral: set when gold fields present; clear when the kind
            # is changed away from gold (no longer a secured-by-gold loan)
            if any(k in data for k in ("gold_weight", "gold_value", "gold_rate")):
                kw["collateral"] = _gold_collateral(data, plan.currency) or {}
            elif data.get("loan_kind") and data.get("loan_kind") != "gold":
                kw["collateral"] = {}
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
            proof_ref=data.get("proof_ref"), note=data.get("note"), acting_user_id=user.id,
            funding_plan_id=_funding_plan_id(data, user),
            fx_rate_micro=_fx_rate_arg(data))
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
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
    plan, entry, is_owner, err = _editable_entry(user, plan_id, entry_id)   # owner OR contributor
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
        # only the owner may re-attribute an entry to a different contributor
        if "paid_by" in data and is_owner:
            fields["logged_by_user_id"] = _payer_uid(plan, data, plan.owner_user_id)
        if "funding_plan_id" in data:
            fields["funding_plan_id"] = _funding_plan_id(data, user)
        if "fx_rate_micro" in data:
            fields["fx_rate_micro"] = _fx_rate_arg(data)
        assets.update_ledger_entry(g.db, plan=plan, entry_id=entry_id, acting_user_id=user.id, **fields)
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(_detail(plan)), 200


@bp.delete("/<int:plan_id>/entries/<int:entry_id>")
def delete_entry(plan_id, entry_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, entry, is_owner, err = _editable_entry(user, plan_id, entry_id)   # owner OR contributor
    if err:
        return err
    try:
        assets.delete_ledger_entry(g.db, plan=plan, entry_id=entry_id, acting_user_id=user.id)
        g.db.commit()
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(_detail(plan)), 200


@bp.post("/<int:plan_id>/entries/<int:entry_id>/amount")
def respond_amount(plan_id, entry_id):
    """Two-party amount agreement: the attributed contributor confirms/counters, the
    owner accepts/re-counters. Either side of the negotiation may call (accessible)."""
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").lower()
    amount = None
    try:
        if action == "counter":
            amount = to_minor(data.get("amount", ""), plan.currency)
        assets.respond_amount(g.db, plan=plan, entry_id=entry_id, actor_uid=user.id,
                              action=action, amount_minor=amount)
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
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"),
            acting_user_id=user.id,
            fx_rate_micro=_fx_rate_arg(data))
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=loans.loan_state(g.db, plan.loan, as_of=date.today())), 201


@bp.get("/<int:plan_id>/loan/amortization")
def loan_amortization(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return err
    if plan.type != "loan":
        return jsonify(error="not_a_loan"), 400
    loan = plan.loan
    st = loans.loan_state(g.db, loan, as_of=date.today())
    args = request.args
    try:
        extra = to_minor(args.get("extra"), plan.currency) if args.get("extra") else 0
        lump = to_minor(args.get("lump"), plan.currency) if args.get("lump") else 0
        lump_month = int(args.get("lump_month")) if args.get("lump_month") else 1
        target = int(args.get("target_months")) if args.get("target_months") else None
    except (ValueError, TypeError) as e:
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(loans.amortize(
        principal_minor=st["principal_outstanding_minor"], rate_bps=loan.rate_bps,
        interest_type=loan.interest_type, tenure_months=loan.tenure_months,
        currency=plan.currency, extra_monthly_minor=extra, lump_minor=lump,
        lump_month=lump_month, target_months=target)), 200


@bp.post("/<int:plan_id>/loan/compare")
def loan_compare(plan_id):
    """Shop-around comparison: the current loan vs user-supplied offers, on a like-for-like
    principal, ranked by total cost / effective APR (fee-inclusive)."""
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return err
    if plan.type != "loan":
        return jsonify(error="not_a_loan"), 400
    loan = plan.loan
    data = request.get_json(silent=True) or {}
    try:
        if data.get("amount"):
            principal = to_minor(data.get("amount"), plan.currency)
        else:
            principal = loans.loan_state(g.db, loan, as_of=date.today())["principal_outstanding_minor"]
        # the current loan is always the first row (the baseline to beat)
        offers = [{"label": loan.counterparty or "Your current loan", "rate_bps": loan.rate_bps,
                   "interest_type": loan.interest_type, "tenure_months": loan.tenure_months,
                   "fee_minor": 0}]
        for o in (data.get("offers") or []):
            offers.append({
                "label": (o.get("label") or "Offer").strip(),
                "rate_bps": pct_to_bps(o.get("rate", "0")),
                "interest_type": o.get("interest_type") or "yearly",
                "tenure_months": int(o["tenure_months"]) if o.get("tenure_months") else loan.tenure_months,
                "fee_bps": pct_to_bps(o.get("fee_pct", "0")) if o.get("fee_pct") else 0,
                "fee_minor": to_minor(o.get("fee_amount"), plan.currency) if o.get("fee_amount") else 0,
            })
        result = loans.compare_offers(principal_minor=principal, currency=plan.currency, offers=offers)
    except (LoanError, ValueError, TypeError) as e:
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(result), 200


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


@bp.post("/<int:plan_id>/loan/contact")
def assign_loan_contact(plan_id):
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
        contacts.assign_loan(g.db, owner_id=user.id, plan=plan,
                             contact_id=data.get("contact_id"))
        g.db.commit()
    except contacts.ContactError as e:
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
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"),
            fx_rate_micro=_fx_rate_arg(data))
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
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
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"),
            fx_rate_micro=_fx_rate_arg(data))
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
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


@bp.patch("/<int:plan_id>/asset/meta")
def asset_meta(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    if plan.type != "asset":
        return jsonify(error="not_an_asset"), 400
    d = request.get_json(silent=True) or {}
    try:
        assets.update_asset_meta(g.db, plan=plan, owner_id=user.id,
            seller_name=d.get("seller_name"), seller_contact_id=d.get("seller_contact_id"),
            buyer_name=d.get("buyer_name"), buyer_contact_id=d.get("buyer_contact_id"),
            extra_fields=d.get("extra_fields"), links=d.get("links"))
        g.db.commit()
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(state=assets.asset_state(g.db, plan, viewer_id=user.id)), 200


@bp.get("/<int:plan_id>/asset/attachments")
def list_asset_docs(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)   # members can view
    if err:
        return err
    if plan.type != "asset":
        return jsonify(error="not_an_asset"), 400
    return jsonify(attachments=[attachments.meta(a) for a in attachments.list_for_asset(g.db, plan.id)]), 200


@bp.post("/<int:plan_id>/asset/attachments")
def upload_asset_doc(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner uploads
    if err:
        return err
    if plan.type != "asset":
        return jsonify(error="not_an_asset"), 400
    f = request.files.get("file")
    if f is None:
        return jsonify(error="invalid", detail="no file"), 400
    try:
        a = attachments.add_attachment(g.db, asset_plan=plan, uploaded_by=user.id,
                                       filename=f.filename, raw=f.read())
        g.db.commit()
    except attachments.AttachmentError as e:
        g.db.rollback()
        code = 413 if "too large" in str(e) else 400
        return jsonify(error="invalid", detail=str(e)), code
    return jsonify(attachment=attachments.meta(a)), 201


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
            g.db, plan=plan, user_id=_payer_uid(plan, data, user.id), kind=data.get("kind", ""),
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")),
            method=data.get("method"), note=data.get("note"), acting_user_id=user.id,
            fx_rate_micro=_fx_rate_arg(data))
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=loans.loan_state(g.db, plan.loan, as_of=date.today())), 201


@bp.post("/<int:plan_id>/loan/backfill")
def loan_backfill(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    if plan.type != "loan":
        return jsonify(error="not_a_loan"), 400
    data = request.get_json(silent=True) or {}
    tm = data.get("through_month")
    td = data.get("through_date")
    try:
        through_month = int(tm) if tm not in (None, "") else None
        through_date = date.fromisoformat(td) if td else None
        result = loans.backfill_loan_interest(
            g.db, plan=plan, user_id=user.id, acting_user_id=user.id,
            through_month=through_month, through_date=through_date)
        g.db.commit()
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(result=result,
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
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"),
            fx_rate_micro=_fx_rate_arg(data))
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
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


@bp.post("/<int:plan_id>/shares")
def create_share(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        sh = sharing_links.create_share(
            g.db, plan=plan, user_id=user.id,
            scope=data.get("scope", "summary"), ttl_days=int(data.get("ttl_days", 30)))
        g.db.commit()
    except (sharing_links.ShareError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    url = request.host_url.rstrip("/") + "/s/" + sh.token
    return jsonify(share={"id": sh.id, "scope": sh.scope, "token": sh.token,
                          "expires_at": sh.expires_at.isoformat()}, url=url), 201


@bp.get("/<int:plan_id>/shares")
def list_shares(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    return jsonify(shares=sharing_links.list_shares(g.db, plan)), 200


@bp.delete("/<int:plan_id>/shares/<int:share_id>")
def revoke_share(plan_id, share_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    try:
        sharing_links.revoke_share(g.db, plan=plan, share_id=share_id)
        g.db.commit()
    except sharing_links.ShareNotFound:
        g.db.rollback()
        return jsonify(error="not_found"), 404
    return "", 204


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
