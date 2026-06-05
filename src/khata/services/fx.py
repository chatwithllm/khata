from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FxRate
from ..money import SUPPORTED_CURRENCIES

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
    base = (base or "").upper()
    quote = (quote or "").upper()
    if base == quote:
        return MICRO
    row = session.scalar(select(FxRate).where(
        FxRate.base_currency == base, FxRate.quote_currency == quote))
    return row.rate_micro if row else None


def set_rate(session: Session, *, base: str, quote: str, rate_micro: int, as_of) -> FxRate:
    base = (base or "").upper()
    quote = (quote or "").upper()
    if base not in SUPPORTED_CURRENCIES or quote not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {base!r}/{quote!r}")
    if base == quote:
        raise ValidationError("base and quote must differ")
    if rate_micro <= 0:
        raise ValidationError("rate must be > 0")
    row = session.scalar(select(FxRate).where(
        FxRate.base_currency == base, FxRate.quote_currency == quote))
    if row is None:
        row = FxRate(base_currency=base, quote_currency=quote, rate_micro=rate_micro, as_of=as_of)
        session.add(row)
    else:
        row.rate_micro = rate_micro
        row.as_of = as_of
    session.flush()
    return row
