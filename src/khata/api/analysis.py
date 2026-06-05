from flask import Blueprint, jsonify, request

from ..money import pct_to_bps, to_minor
from ..services import analysis
from .auth import current_user

bp = Blueprint("analysis", __name__)


@bp.get("/api/analysis/hold-vs-sell")
def hold_vs_sell():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    a = request.args
    try:
        result = analysis.hold_vs_sell(
            asset_value_minor=to_minor(a.get("asset_value", ""), "INR"),
            appreciation_bps=pct_to_bps(a.get("appreciation", "0")),
            borrow_amount_minor=to_minor(a.get("borrow", "0"), "INR"),
            interest_bps=pct_to_bps(a.get("interest", "0")),
            horizon_months=int(a.get("horizon", "0")))
    except (analysis.AnalysisError, ValueError, TypeError) as e:
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(result), 200
