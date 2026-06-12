from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from ..models import Plan, Holding, LedgerEntry
from ..money import SUPPORTED_CURRENCIES
from . import fx

MICRO = 1_000_000
ASSET_CLASSES = {"gold", "silver", "equity", "mf", "cash", "other"}


class HoldingError(Exception):
    pass


class ValidationError(HoldingError):
    pass


def create_holding_plan(session: Session, *, owner_id, name, currency, asset_class, unit,
                        symbol=None, purity=None) -> Plan:
    if asset_class not in ASSET_CLASSES:
        raise ValidationError(f"unknown asset_class: {asset_class}")
    if not (unit or "").strip():
        raise ValidationError("unit is required")
    if (currency or "").upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {currency!r}")
    plan = Plan(owner_user_id=owner_id, type="holding",
                name=(name or "").strip() or "Untitled holding",
                currency=currency.upper(), status="active")
    session.add(plan)
    session.flush()
    session.add(Holding(plan_id=plan.id, asset_class=asset_class, unit=unit.strip(),
                        symbol=symbol, purity=purity))
    session.flush()
    return plan


def _qty_held_micro(plan: Plan) -> int:
    bought = sum(e.quantity_micro or 0 for e in plan.ledger_entries if e.kind == "buy")
    sold = sum(e.quantity_micro or 0 for e in plan.ledger_entries if e.kind == "sell")
    return bought - sold


def _add_entry(session, plan, *, user_id, kind, direction, quantity_micro, amount_minor,
               occurred_at, note, fx_rate_micro=None) -> LedgerEntry:
    if quantity_micro is None or amount_minor is None:
        raise ValidationError("quantity and amount are required")
    if quantity_micro <= 0:
        raise ValidationError("quantity must be > 0")
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, kind=kind, direction=direction,
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at,
                        quantity_micro=quantity_micro, note=note)
    # append through the relationship so a freshly-loaded collection stays consistent
    # when holding_state is read between mutations (avoids stale-collection reads).
    plan.ledger_entries.append(entry)
    session.flush()
    fx.snapshot_entry_rate(session, entry, explicit_rate_micro=fx_rate_micro)
    return entry


def add_buy(session: Session, *, plan: Plan, user_id, quantity_micro, amount_minor, occurred_at,
            note=None, fx_rate_micro=None) -> LedgerEntry:
    return _add_entry(session, plan, user_id=user_id, kind="buy", direction="out",
                      quantity_micro=quantity_micro, amount_minor=amount_minor,
                      occurred_at=occurred_at, note=note, fx_rate_micro=fx_rate_micro)


def add_sell(session: Session, *, plan: Plan, user_id, quantity_micro, amount_minor, occurred_at,
             note=None, fx_rate_micro=None) -> LedgerEntry:
    if quantity_micro is not None and quantity_micro > _qty_held_micro(plan):
        raise ValidationError("cannot sell more than currently held")
    return _add_entry(session, plan, user_id=user_id, kind="sell", direction="in",
                      quantity_micro=quantity_micro, amount_minor=amount_minor,
                      occurred_at=occurred_at, note=note, fx_rate_micro=fx_rate_micro)


def set_quote(session: Session, *, plan: Plan, price_minor, as_of) -> Holding:
    if price_minor < 0:
        raise ValidationError("price must be >= 0")
    holding = plan.holding
    holding.current_price_minor = price_minor
    holding.price_as_of = as_of
    session.flush()
    return holding


def _round(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def holding_state(session: Session, holding: Holding) -> dict:
    plan = holding.plan
    buys = [e for e in plan.ledger_entries if e.kind == "buy"]
    sells = [e for e in plan.ledger_entries if e.kind == "sell"]
    qty_bought = sum(e.quantity_micro or 0 for e in buys)
    qty_sold = sum(e.quantity_micro or 0 for e in sells)
    qty_held = qty_bought - qty_sold
    cost_bought = sum(e.amount_minor for e in buys)
    avg = (Decimal(cost_bought) * MICRO / qty_bought) if qty_bought else Decimal(0)
    cost_of_held = _round(avg * qty_held / MICRO)
    proceeds = sum(e.amount_minor for e in sells)
    realized = proceeds - _round(avg * qty_sold / MICRO)

    price = holding.current_price_minor
    if price is not None:
        current_value = _round(Decimal(price) * qty_held / MICRO)
        unrealized = current_value - cost_of_held
    else:
        current_value = None
        unrealized = None

    return {
        "asset_class": holding.asset_class, "unit": holding.unit, "symbol": holding.symbol,
        "purity": holding.purity, "currency": plan.currency,
        "qty_held_micro": qty_held,
        "avg_cost_per_unit_minor": _round(avg),
        "cost_of_held_minor": cost_of_held,
        "current_price_minor": price,
        "price_as_of": holding.price_as_of.isoformat() if holding.price_as_of else None,
        "current_value_minor": current_value,
        "unrealized_gain_minor": unrealized,
        "realized_gain_minor": realized,
        "proceeds_minor": proceeds,
    }
