"""Tests for POST /api/plans/<pid>/loan/backfill endpoint.

Auth / seed pattern copied from tests/test_secured_loans_api.py:
- Each test gets a fresh in-memory SQLite DB via a local `client` fixture.
- _register() does POST /api/auth/register — the session cookie is set
  automatically and subsequent requests are authenticated.
- Loan plan created via POST /api/plans, disbursement via
  POST /api/plans/<id>/loan/disbursements.
- Non-owner isolation: logout then register second user.
"""
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


def _register(client, email="owner@test.com"):
    r = client.post("/api/auth/register", json={
        "email": email, "display_name": "Owner", "password": "pw12345"})
    assert r.status_code == 201, r.get_json()
    return r


def _make_given_loan(client):
    """Create a 'given' (lent-out) monthly-3% loan, start 2023-12-12.

    The API accepts 'rate' as a percentage string (e.g. "3" = 3%/month),
    not 'rate_bps' directly — see plans.py's pct_to_bps(data.get("rate")).
    """
    r = client.post("/api/plans", json={
        "type": "loan",
        "name": "Test Lent Loan",
        "currency": "INR",
        "direction": "given",
        "interest_type": "monthly",
        "rate": "3",
        "start_date": "2023-12-12",
    })
    assert r.status_code == 201, r.get_json()
    return r.get_json()["plan"]["id"]


def _disburse(client, pid):
    """Disburse ₹22,00,000 on 2023-12-12."""
    r = client.post(f"/api/plans/{pid}/loan/disbursements", json={
        "amount": "22,00,000",
        "occurred_at": "2023-12-12T00:00:00",
    })
    assert r.status_code in (200, 201), r.get_json()
    return r


def _setup_loan(client):
    """Register owner, create + disburse loan. Returns plan id."""
    _register(client, "owner@test.com")
    pid = _make_given_loan(client)
    _disburse(client, pid)
    return pid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_backfill_owner_clears_dues(client):
    """Owner POSTs with a cutoff large enough to cover all completed months →
    status 201; result.count >= 1; state.months_behind == 0.

    The loan started 2023-12-12 (far in the past), so many months have completed
    by any run date. We pass through_month=999 to guarantee all completed months
    are cleared, which drives months_behind to 0.
    """
    pid = _setup_loan(client)
    r = client.post(f"/api/plans/{pid}/loan/backfill", json={"through_month": 999})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert body["result"]["count"] >= 1
    assert body["state"]["months_behind"] == 0


def test_backfill_requires_a_cutoff(client):
    """POST {} (no cutoff) → 400."""
    pid = _setup_loan(client)
    r = client.post(f"/api/plans/{pid}/loan/backfill", json={})
    assert r.status_code == 400


def test_backfill_rejects_both_cutoffs(client):
    """POST with both through_month and through_date → 400."""
    pid = _setup_loan(client)
    r = client.post(f"/api/plans/{pid}/loan/backfill",
                    json={"through_month": 1, "through_date": "2024-01-01"})
    assert r.status_code == 400


def test_backfill_forbidden_for_non_owner(client):
    """A different authenticated user POSTs → 403."""
    pid = _setup_loan(client)
    # logout owner
    client.post("/api/auth/logout")
    # register a second user
    _register(client, "other@test.com")
    r = client.post(f"/api/plans/{pid}/loan/backfill", json={"through_month": 1})
    assert r.status_code == 403


def test_backfill_malformed_through_date_is_400(client):
    pid = _setup_loan(client)
    r = client.post(f"/api/plans/{pid}/loan/backfill", json={"through_date": "not-a-date"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid"
