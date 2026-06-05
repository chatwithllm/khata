from decimal import Decimal, ROUND_HALF_UP



class AnalysisError(Exception):
    pass


def _round(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def hold_vs_sell(*, asset_value_minor: int, appreciation_bps: int, borrow_amount_minor: int,
                 interest_bps: int, horizon_months: int) -> dict:
    """Hold-an-appreciating-asset-and-borrow vs sell-it. Pure; derived; no float."""
    if asset_value_minor <= 0:
        raise AnalysisError("asset value must be > 0")
    if horizon_months <= 0:
        raise AnalysisError("horizon must be > 0 months")
    if appreciation_bps < 0 or interest_bps < 0 or borrow_amount_minor < 0:
        raise AnalysisError("rates and amounts must be >= 0")
    monthly_appr = Decimal(appreciation_bps) / 120000
    future = _round(Decimal(asset_value_minor) * ((Decimal(1) + monthly_appr) ** horizon_months))
    appreciation_gain = future - asset_value_minor
    # simple interest on the borrowed principal over the horizon (bullet gold-loan style)
    interest_cost = _round(Decimal(borrow_amount_minor) * Decimal(interest_bps) / 10000
                           * Decimal(horizon_months) / 12)
    net = appreciation_gain - interest_cost
    return {
        "asset_value_minor": asset_value_minor, "borrow_amount_minor": borrow_amount_minor,
        "horizon_months": horizon_months, "future_value_minor": future,
        "appreciation_gain_minor": appreciation_gain, "interest_cost_minor": interest_cost,
        "net_hold_advantage_minor": net, "verdict": "hold" if net > 0 else "sell",
    }
