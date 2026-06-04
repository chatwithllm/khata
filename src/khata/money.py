from decimal import Decimal, ROUND_HALF_UP

SUPPORTED_CURRENCIES = {"INR", "USD"}
_EXP = 2  # both INR and USD use 2 minor digits


def _check_currency(currency: str) -> str:
    c = (currency or "").upper()
    if c not in SUPPORTED_CURRENCIES:
        raise ValueError(f"unsupported currency: {currency!r}")
    return c


def to_minor(value: "str | int", currency: str) -> int:
    """Parse a human amount ("12,40,000", "12.50", 1500) into integer minor units."""
    _check_currency(currency)
    if isinstance(value, float):
        raise TypeError("amounts must be str or int, not float (money is never float)")
    s = str(value).strip().replace(",", "").replace("_", "")
    if not s:
        raise ValueError("empty amount")
    d = Decimal(s)
    if not d.is_finite():
        raise ValueError(f"non-finite amount: {s!r}")
    minor = (d * (10 ** _EXP)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(minor)


def format_minor(amount_minor: int, currency: str) -> str:
    """Western-grouped major.minor string (frontend handles symbol + Indian grouping)."""
    _check_currency(currency)
    sign = "-" if amount_minor < 0 else ""
    major, minor = divmod(abs(int(amount_minor)), 10 ** _EXP)
    return f"{sign}{major:,}.{minor:0{_EXP}d}"
