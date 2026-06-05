from datetime import date

from sqlalchemy.orm import Session

from ..models import User
from . import sharing, loans, holdings, fx


def net_worth(session: Session, user_id: int) -> dict:
    user = session.get(User, user_id)
    base = user.base_currency
    owned, _member = sharing.user_plans(session, user_id)

    assets = 0
    liabilities = 0
    holdings_rows = []
    unpriced = []
    unconverted: dict[str, dict] = {}

    def _apply(side: str, ccy: str, amount_minor: int):
        """Add amount to base totals if convertible, else to the unconverted bucket.
        Returns the base-converted amount, or None if no rate."""
        nonlocal assets, liabilities
        rate = fx.get_rate(session, base, ccy)
        if rate is not None:
            converted = fx.convert(amount_minor, rate_micro=rate)
            if side == "assets":
                assets += converted
            else:
                liabilities += converted
            return converted
        bucket = unconverted.setdefault(ccy, {"assets_minor": 0, "liabilities_minor": 0})
        bucket[side + "_minor"] += amount_minor
        return None

    for p in owned:
        if p.type == "holding":
            st = holdings.holding_state(session, p.holding)
            priced = st["current_value_minor"] is not None
            value_in_base = None
            if priced:
                value_in_base = _apply("assets", p.currency, st["current_value_minor"])
            else:
                unpriced.append({"id": p.id, "name": p.name, "asset_class": st["asset_class"]})
            holdings_rows.append({
                "id": p.id, "name": p.name, "asset_class": st["asset_class"],
                "currency": p.currency, "qty_held_micro": st["qty_held_micro"],
                "current_value_minor": st["current_value_minor"],
                "value_in_base_minor": value_in_base,
                "unrealized_gain_minor": st["unrealized_gain_minor"],
                "priced": priced,
            })
        elif p.type == "loan":
            st = loans.loan_state(session, p.loan, as_of=date.today())
            side = "assets" if p.loan.direction == "given" else "liabilities"
            _apply(side, p.currency, st["total_minor"])
        # asset-purchase plans are excluded from net worth (acquisition goals)

    return {
        "base_currency": base,
        "assets_minor": assets,
        "liabilities_minor": liabilities,
        "net_worth_minor": assets - liabilities,
        "holdings": holdings_rows,
        "unpriced": unpriced,
        "unconverted": unconverted,
    }
