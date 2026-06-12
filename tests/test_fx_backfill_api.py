from datetime import date

import pytest

from khata import create_app
from khata.config import Config
from khata.db import Base


@pytest.fixture
def client():
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    cfg.testing = True
    app = create_app(cfg)
    app.config["TESTING"] = True
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def _make_admin(client):
    """Register first user — the codebase auto-promotes the first registered
    user to admin (see test_admin_api.py: test_first_user_is_admin_others_are_not).
    The session cookie is kept by the test client, so subsequent requests run
    as that admin."""
    r = client.post("/api/auth/register", json={
        "email": "a@b.com", "password": "pw12345678", "display_name": "A"})
    assert r.status_code in (200, 201)
    assert r.get_json()["user"]["is_admin"] is True
    return r


def test_backfill_requires_admin(client):
    client.post("/api/auth/register", json={
        "email": "x@b.com", "password": "pw12345678", "display_name": "X"})
    # log out so the request is unauthenticated / no-admin
    client.post("/api/auth/logout")
    # register a second (non-admin) user and use that session
    client.post("/api/auth/register", json={
        "email": "y@b.com", "password": "pw12345678", "display_name": "Y"})
    assert client.post("/api/admin/fx-backfill").status_code == 403


def test_backfill_fills_nulls_idempotently(client, monkeypatch):
    _make_admin(client)
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1,00,000"}).get_json()["plan"]["id"]
    # Saturday-dated entry → must take Friday's rate
    client.post(f"/api/plans/{pid}/payments", json={
        "amount": "1,000", "method": "upi", "funding_source": "savings",
        "occurred_at": "2026-06-06T12:00:00+00:00"})
    # entry that already has a rate → must be skipped
    client.post(f"/api/plans/{pid}/payments", json={
        "amount": "2,000", "method": "upi", "funding_source": "savings",
        "occurred_at": "2026-06-05T12:00:00+00:00", "fx_rate_micro": 99_999})

    import khata.api.admin as admin_api
    monkeypatch.setattr(admin_api.fx_live, "fetch_range",
                        lambda start, end, base, quote: {date(2026, 6, 5): 88_000_000})

    r = client.post("/api/admin/fx-backfill")
    assert r.status_code == 200
    body = r.get_json()
    assert body == {"filled": 1, "skipped": 1, "no_rate": 0}

    ledger = client.get(f"/api/plans/{pid}").get_json()["state"]["ledger"]
    by_amt = {row["amount_minor"]: row for row in ledger}
    # INR entry: counter USD → USD-per-INR = inverse of ₹88/$ = 11_364 micro
    assert by_amt[100_000]["fx_rate_micro"] == 11_364
    assert by_amt[100_000]["fx_counter_currency"] == "USD"
    assert by_amt[200_000]["fx_rate_micro"] == 99_999      # untouched

    # idempotent re-run: nothing left to fill
    r2 = client.post("/api/admin/fx-backfill")
    assert r2.get_json() == {"filled": 0, "skipped": 2, "no_rate": 0}


def test_backfill_frankfurter_down_counts_no_rate(client, monkeypatch):
    _make_admin(client)
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1,00,000"}).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/payments", json={
        "amount": "1,000", "method": "upi", "funding_source": "savings"})
    import khata.api.admin as admin_api
    monkeypatch.setattr(admin_api.fx_live, "fetch_range", lambda *a, **k: {})
    r = client.post("/api/admin/fx-backfill")
    assert r.get_json() == {"filled": 0, "skipped": 0, "no_rate": 1}
