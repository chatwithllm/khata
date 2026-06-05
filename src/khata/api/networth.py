from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from ..money import SUPPORTED_CURRENCIES, to_micro
from ..services import fx, networth
from .auth import current_user

bp = Blueprint("networth", __name__)


def _as_of(v):
    if not v:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@bp.get("/api/networth")
def get_networth():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(networth.net_worth(g.db, user.id)), 200


@bp.post("/api/base-currency")
def set_base_currency():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    ccy = (data.get("currency") or "").upper()
    if ccy not in SUPPORTED_CURRENCIES:
        return jsonify(error="invalid", detail="unsupported currency"), 400
    user.base_currency = ccy
    g.db.commit()
    return jsonify(base_currency=user.base_currency), 200


@bp.post("/api/fx-rates")
def set_fx_rate():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    try:
        row = fx.set_rate(g.db, base=user.base_currency, quote=(data.get("quote") or ""),
                          rate_micro=to_micro(data.get("rate", "")), as_of=_as_of(data.get("as_of")))
        g.db.commit()
    except (fx.FxError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(base=row.base_currency, quote=row.quote_currency, rate_micro=row.rate_micro), 201
