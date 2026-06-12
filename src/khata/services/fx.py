from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from ..models import FxRate, FxRefreshState
from ..money import SUPPORTED_CURRENCIES
from . import fx_live

MICRO = 1_000_000


class FxError(Exception):
    pass


class ValidationError(FxError):
    pass


def convert(amount_minor: int, *, rate_micro: int) -> int:
    """Convert an integer minor amount by a base-per-quote rate (×1e6). Exact Decimal."""
    return int((Decimal(amount_minor) * rate_micro / MICRO).quantize(Decimal(1),
                                                                      rounding=ROUND_HALF_UP))


def get_rate(session: Session, base: str, quote: str) -> int | None:
    """quote-per-base rate (×1e6). Same currency → identity. If only the reverse
    rate (quote→base) is stored, derive the inverse so a single stored row works
    both directions — a USD-base user with an INR→USD rate still gets converted."""
    base = (base or "").upper()
    quote = (quote or "").upper()
    if base == quote:
        return MICRO
    row = session.scalar(select(FxRate).where(
        FxRate.base_currency == base, FxRate.quote_currency == quote))
    if row is not None and row.rate_micro:
        return row.rate_micro
    inv = session.scalar(select(FxRate).where(
        FxRate.base_currency == quote, FxRate.quote_currency == base))
    if inv is not None and inv.rate_micro:
        return int((Decimal(MICRO) * MICRO / inv.rate_micro).quantize(
            Decimal(1), rounding=ROUND_HALF_UP))
    return None


def list_rates(session: Session) -> list[dict]:
    """All stored fx rates (raw direction as entered)."""
    rows = session.scalars(select(FxRate).order_by(FxRate.base_currency, FxRate.quote_currency))
    return [{"base": r.base_currency, "quote": r.quote_currency,
             "rate_micro": r.rate_micro, "as_of": r.as_of.isoformat() if r.as_of else None}
            for r in rows]


def set_rate(session: Session, *, base: str, quote: str, rate_micro: int, as_of) -> FxRate:
    base = (base or "").upper()
    quote = (quote or "").upper()
    if base not in SUPPORTED_CURRENCIES or quote not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {base!r}/{quote!r}")
    if base == quote:
        raise ValidationError("base and quote must differ")
    if rate_micro <= 0:
        raise ValidationError("rate must be > 0")
    # A currency PAIR holds exactly one canonical row. Drop any existing row in EITHER
    # direction first, so a reverse entry can't leave two contradictory rows behind
    # (e.g. INR→USD=98 and USD→INR=98, which means "1 USD=₹98" AND "1 INR=$98").
    for existing in session.scalars(select(FxRate).where(
            ((FxRate.base_currency == base) & (FxRate.quote_currency == quote)) |
            ((FxRate.base_currency == quote) & (FxRate.quote_currency == base)))).all():
        session.delete(existing)
    session.flush()
    row = FxRate(base_currency=base, quote_currency=quote, rate_micro=rate_micro, as_of=as_of)
    session.add(row)
    session.flush()
    return row


def counter_currency_for(currency: str) -> str:
    """The other member of SUPPORTED_CURRENCIES. Two-currency assumption lives
    HERE only (spec §3): if support grows, this becomes the user's base currency."""
    others = SUPPORTED_CURRENCIES - {(currency or "").upper()}
    return next(iter(others))


def snapshot_entry_rate(session: Session, entry, explicit_rate_micro: int | None = None) -> None:
    """Stamp entry.fx_rate_micro / fx_counter_currency (counter-per-entry ×1e6).
    Fallback chain: explicit client rate > frankfurter at occurred_at date >
    stored manual rate (inverted to entry→counter) > None. Never raises —
    entry creation must not block on FX (spec §3, §9)."""
    counter = counter_currency_for(entry.currency)
    rate = int(explicit_rate_micro) if explicit_rate_micro else None
    if rate is None:
        try:
            rate = fx_live.fetch_rate(entry.occurred_at.date(),
                                      base=entry.currency, quote=counter)
        except Exception:
            rate = None
    if rate is None:
        # get_rate(X, Y) = X-per-Y; counter-per-entry = get_rate(counter, entry ccy).
        # Handles inversion of the canonical INR/USD row internally.
        rate = get_rate(session, counter, entry.currency)
    if rate:
        entry.fx_rate_micro = rate
        entry.fx_counter_currency = counter


def _refresh_state(session: Session) -> "FxRefreshState":
    """Get-or-create the single claim row (id=1). create_all'd DBs have no seed row."""
    row = session.get(FxRefreshState, 1)
    if row is None:
        row = FxRefreshState(id=1)
        session.add(row)
        session.commit()
    return row


def refresh_last_run(session: Session) -> "datetime | None":
    return _refresh_state(session).last_run_at


def claim_daily_refresh(session: Session, *, now: datetime) -> bool:
    """Atomically claim today's live-FX refresh (mirrors backup_store.claim_due):
    the UPDATE's WHERE makes exactly one concurrent caller win per calendar day."""
    _refresh_state(session)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    res = session.execute(
        update(FxRefreshState).where(
            FxRefreshState.id == 1,
            or_(FxRefreshState.last_run_at.is_(None),
                FxRefreshState.last_run_at < start_of_day),
        ).values(last_run_at=now))
    session.commit()
    return res.rowcount == 1


def release_refresh_claim(session: Session, *, previous) -> None:
    """Give the slot back after a failed fetch so a later hourly tick retries today."""
    session.execute(update(FxRefreshState).where(FxRefreshState.id == 1)
                    .values(last_run_at=previous))
    session.commit()
