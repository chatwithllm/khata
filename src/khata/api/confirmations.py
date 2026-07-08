from flask import Blueprint, g, jsonify

from ..models import Plan
from ..services import assets, sharing, transfers
from .auth import current_user

bp = Blueprint("confirmations", __name__, url_prefix="/api/confirmations")


@bp.get("")
def index():
    """Ledger entries waiting on the current user to act in the amount-agreement loop —
    'pending' entries attributed to them, or 'countered' entries on plans they own. Only
    plans the user can actually access are surfaced (so every row is actionable)."""
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    rows = assets.list_amount_confirmations(g.db, user.id)
    out = []
    for r in rows:
        plan = g.db.get(Plan, r["plan_id"])
        if plan is None or not sharing.accessible(g.db, plan=plan, user_id=user.id):
            continue
        out.append(r)
    receipts = transfers.list_receipt_confirmations(g.db, user.id)
    return jsonify(confirmations=out, receipts=receipts), 200
