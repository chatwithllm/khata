import io
import json
import urllib.error
from datetime import date

from khata.services import fx_live


class _FakeResp(io.BytesIO):
    """Minimal urlopen context-manager response."""
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode() if not isinstance(payload, bytes) else payload)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, payload=None, status=200, exc=None, capture=None):
    def fake_urlopen(url, timeout=None):
        if capture is not None:
            capture.append((url, timeout))
        if exc is not None:
            raise exc
        return _FakeResp(payload, status=status)
    monkeypatch.setattr(fx_live.urllib.request, "urlopen", fake_urlopen)


def test_fetch_rate_success(monkeypatch):
    calls = []
    _patch(monkeypatch, {"base": "INR", "rates": {"USD": 0.011364}}, capture=calls)
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") == 11_364
    url, timeout = calls[0]
    assert url == "https://api.frankfurter.dev/v1/2026-06-10?base=INR&symbols=USD"
    assert timeout == 4


def test_fetch_latest_success(monkeypatch):
    calls = []
    _patch(monkeypatch, {"base": "USD", "rates": {"INR": 88.0}}, capture=calls)
    assert fx_live.fetch_latest("USD", "INR") == 88_000_000
    assert calls[0][0] == "https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR"


def test_fetch_rate_timeout_returns_none(monkeypatch):
    _patch(monkeypatch, exc=TimeoutError("timed out"))
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") is None


def test_fetch_rate_http_error_returns_none(monkeypatch):
    _patch(monkeypatch, exc=urllib.error.HTTPError("u", 500, "boom", {}, None))
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") is None


def test_fetch_rate_non_200_returns_none(monkeypatch):
    _patch(monkeypatch, {"rates": {"USD": 0.011}}, status=404)
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") is None


def test_fetch_rate_malformed_json_returns_none(monkeypatch):
    _patch(monkeypatch, b"not json {{")
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") is None


def test_fetch_rate_missing_symbol_returns_none(monkeypatch):
    _patch(monkeypatch, {"rates": {}})
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") is None


def test_fetch_range_with_weekend_gaps(monkeypatch):
    # Fri 2026-06-05 and Mon 2026-06-08 present; weekend absent (frankfurter omits it)
    _patch(monkeypatch, {"rates": {"2026-06-05": {"INR": 88.0},
                                   "2026-06-08": {"INR": 88.5}}})
    rates = fx_live.fetch_range(date(2026, 6, 5), date(2026, 6, 8), "USD", "INR")
    assert rates == {date(2026, 6, 5): 88_000_000, date(2026, 6, 8): 88_500_000}


def test_fetch_range_failure_returns_empty(monkeypatch):
    _patch(monkeypatch, exc=OSError("no network"))
    assert fx_live.fetch_range(date(2026, 6, 5), date(2026, 6, 8), "USD", "INR") == {}


def test_rate_for_date_prior_business_day():
    rates = {date(2026, 6, 5): 88_000_000}  # Friday only
    assert fx_live.rate_for_date(rates, date(2026, 6, 7)) == 88_000_000  # Sunday → Friday
    assert fx_live.rate_for_date(rates, date(2026, 6, 5)) == 88_000_000  # exact hit
    assert fx_live.rate_for_date(rates, date(2026, 6, 20)) is None       # beyond max_back
