from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

SUPPORTED_CURRENCIES = {"INR", "USD"}
_EXP = 2  # both INR and USD use 2 minor digits
_MICRO_EXP = 6  # quantities: integer micro-units (x1_000_000)

# Domain bound on a parsed human number BEFORE scaling. Keeps the scaled result
# inside SQLite's signed 64-bit column range and stops absurd inputs ("1e9999")
# from blowing past Decimal's quantize precision — which raises InvalidOperation,
# an ArithmeticError that is NOT a ValueError and would otherwise surface as 500.
_MAX_INPUT = Decimal("1e15")
_INT64_MAX = 2 ** 63 - 1


def _check_currency(currency: str) -> str:
    c = (currency or "").upper()
    if c not in SUPPORTED_CURRENCIES:
        raise ValueError(f"unsupported currency: {currency!r}")
    return c


def _parse_decimal(value, noun: str, *, strip_pct: bool = False) -> Decimal:
    """Shared parse: reject float, empty, junk, non-finite, and absurd magnitude.
    Every failure path raises ValueError so the API turns it into 400, never 500."""
    s = str(value).strip().replace(",", "").replace("_", "")
    if strip_pct:
        s = s.rstrip("%").strip()
    if not s:
        raise ValueError(f"empty {noun}")
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid number: {s!r}")
    if not d.is_finite():
        raise ValueError(f"non-finite {noun}: {s!r}")
    if abs(d) >= _MAX_INPUT:
        raise ValueError(f"{noun} out of range: {s!r}")
    return d


def _scaled_int(d: Decimal, scale_exp: int, noun: str) -> int:
    try:
        scaled = (d * (10 ** scale_exp)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        n = int(scaled)
    except (InvalidOperation, ArithmeticError, OverflowError):
        raise ValueError(f"{noun} out of range")
    if abs(n) > _INT64_MAX:
        raise ValueError(f"{noun} out of range")
    return n


def to_minor(value: "str | int", currency: str) -> int:
    """Parse a human amount ("12,40,000", "12.50", 1500) into integer minor units."""
    _check_currency(currency)
    if isinstance(value, float):
        raise TypeError("amounts must be str or int, not float (money is never float)")
    return _scaled_int(_parse_decimal(value, "amount"), _EXP, "amount")


def format_minor(amount_minor: int, currency: str) -> str:
    """Western-grouped major.minor string (frontend handles symbol + Indian grouping)."""
    _check_currency(currency)
    sign = "-" if amount_minor < 0 else ""
    major, minor = divmod(abs(int(amount_minor)), 10 ** _EXP)
    return f"{sign}{major:,}.{minor:0{_EXP}d}"


def pct_to_bps(value) -> int:
    """Parse a human percent ("8.5", "8.5%", 2) into integer basis points (8.5 -> 850)."""
    if isinstance(value, float):
        raise TypeError("rate must be str or int, not float (rates are exact basis points)")
    return _scaled_int(_parse_decimal(value, "rate", strip_pct=True), 2, "rate")


def format_bps(bps: int) -> str:
    """Integer basis points -> percent string (850 -> '8.5')."""
    sign = "-" if bps < 0 else ""
    whole, frac = divmod(abs(int(bps)), 100)
    body = f"{whole}.{frac:02d}".rstrip("0").rstrip(".")
    return f"{sign}{body}"


def to_micro(value: "str | int") -> int:
    """Parse a human quantity ("92.5", 10) into integer micro-units (x1e6). Rejects float."""
    if isinstance(value, float):
        raise TypeError("quantities must be str or int, not float (no float)")
    return _scaled_int(_parse_decimal(value, "quantity"), _MICRO_EXP, "quantity")


def format_micro(micro: int) -> str:
    """Integer micro-units -> quantity string (92_500_000 -> '92.5')."""
    sign = "-" if micro < 0 else ""
    whole, frac = divmod(abs(int(micro)), 10 ** _MICRO_EXP)
    body = f"{whole}.{frac:0{_MICRO_EXP}d}".rstrip("0").rstrip(".")
    return f"{sign}{body}"
