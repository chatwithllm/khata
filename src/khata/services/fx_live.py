"""Live FX rates from frankfurter.app (free, no key, ECB daily fixes).

Stdlib-only (`urllib.request`) — no new dependency. Every function swallows
EVERY failure (network, non-200, parse, missing key) and returns None / {} so
nothing here can ever raise into a request flow. Rates return as int micro
(×1e6) in frankfurter's own direction: quote-per-base (?base=USD&symbols=INR
→ INR per USD). NOTE: that is the OPPOSITE of fx.get_rate's base-per-quote.
"""
import json
import urllib.request
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

BASE_URL = "https://api.frankfurter.dev/v1"
TIMEOUT_S = 4
MICRO = 1_000_000
# frankfurter sits behind Cloudflare, which 403s the default Python-urllib
# User-Agent — identify ourselves or every fetch silently fails.
USER_AGENT = "khata-fx/1.0"


def _get_json(url: str):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _to_micro(val) -> int | None:
    """JSON number → int ×1e6 (Decimal, ROUND_HALF_UP — rates never float onward)."""
    if val is None:
        return None
    try:
        micro = int((Decimal(str(val)) * MICRO).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except Exception:
        return None
    return micro if micro > 0 else None


def fetch_rate(d: date, base: str, quote: str) -> int | None:
    """quote-per-base ×1e6 as of `d`. frankfurter auto-returns the last business
    day's fix for weekends/holidays on single-date lookups."""
    data = _get_json(f"{BASE_URL}/{d.isoformat()}?base={base}&symbols={quote}")
    if not isinstance(data, dict):
        return None
    return _to_micro((data.get("rates") or {}).get(quote))


def fetch_latest(base: str, quote: str) -> int | None:
    """Today's quote-per-base ×1e6."""
    data = _get_json(f"{BASE_URL}/latest?base={base}&symbols={quote}")
    if not isinstance(data, dict):
        return None
    return _to_micro((data.get("rates") or {}).get(quote))


def fetch_range(start: date, end: date, base: str, quote: str) -> dict[date, int]:
    """All business-day rates in [start, end] in one call (for backfill).
    Weekends/holidays are simply absent — use rate_for_date to bridge them."""
    data = _get_json(f"{BASE_URL}/{start.isoformat()}..{end.isoformat()}?base={base}&symbols={quote}")
    if not isinstance(data, dict):
        return {}
    out: dict[date, int] = {}
    for day_str, day_rates in (data.get("rates") or {}).items():
        micro = _to_micro((day_rates or {}).get(quote))
        if micro is None:
            continue
        try:
            out[date.fromisoformat(day_str)] = micro
        except ValueError:
            continue
    return out


def rate_for_date(rates: dict[date, int], d: date, *, max_back: int = 7) -> int | None:
    """Rate for `d`, walking back to the nearest prior business day (≤ max_back days)."""
    for i in range(max_back + 1):
        r = rates.get(d - timedelta(days=i))
        if r:
            return r
    return None
