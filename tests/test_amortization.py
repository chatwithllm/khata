from datetime import date

from khata.services.loans import amortize


def _base(**kw):
    args = dict(principal_minor=3500000, rate_bps=750, interest_type="yearly",
                tenure_months=24, currency="INR", as_of=date(2026, 1, 1))
    args.update(kw)
    return amortize(**args)


def test_baseline_emi_and_totals():
    r = _base()
    assert r["available"] is True
    assert r["baseline"]["months"] == 24
    # 35,000 @ 7.5%/yr over 24 mo → EMI ≈ ₹1,576/mo (157,660 minor); allow rounding slack
    assert 157000 <= r["emi_minor"] <= 158500
    b = r["baseline"]
    assert b["total_interest_minor"] > 0
    assert b["total_paid_minor"] == 3500000 + b["total_interest_minor"]
    assert b["payoff_date"] == "2028-01-01"          # Jan 2026 + 24 mo
    assert len(r["schedule"]) == 24
    # first month: interest = balance * 0.00625 = 3500000*0.00625 = 21875
    assert r["schedule"][0]["interest_minor"] == 21875


def test_extra_per_month_saves_time_and_interest():
    r = _base(extra_monthly_minor=50000)             # +₹500/mo
    s = r["scenario"]
    assert s["months"] < 24
    assert s["months_saved"] == 24 - s["months"]
    assert s["interest_saved_minor"] > 0
    assert s["total_interest_minor"] < r["baseline"]["total_interest_minor"]


def test_lump_sum_saves():
    r = _base(lump_minor=1000000, lump_month=1)       # ₹10,000 now
    s = r["scenario"]
    assert s["months"] < 24
    assert s["interest_saved_minor"] > 0
    assert s["lump_minor"] == 1000000


def test_target_months_requires_bigger_payment():
    r = _base(target_months=12)
    s = r["scenario"]
    assert s["months"] <= 12
    assert s["required_payment_minor"] > r["emi_minor"]   # must pay more to finish sooner
    assert s["extra_monthly_minor"] == s["required_payment_minor"] - r["emi_minor"]
    assert s["interest_saved_minor"] > 0


def test_interest_free_loan():
    r = _base(rate_bps=0, interest_type="none")
    assert r["baseline"]["total_interest_minor"] == 0
    # EMI = ceil(35,00,000 / 24)
    assert r["emi_minor"] == -(-3500000 // 24)
    assert r["baseline"]["months"] == 24


def test_no_tenure_unavailable():
    r = _base(tenure_months=None)
    assert r["available"] is False
    assert r["reason"] == "needs_tenure"
    r2 = _base(tenure_months=0)
    assert r2["available"] is False and r2["reason"] == "needs_tenure"


def test_no_principal_unavailable():
    r = _base(principal_minor=0)
    assert r["available"] is False and r["reason"] == "no_principal"


# ── API endpoint ──
import pytest
from khata import create_app
from khata.config import Config
from khata.db import Base


@pytest.fixture
def client():
    cfg = Config(); cfg.database_url = "sqlite:///:memory:"
    app = create_app(cfg); app.config["TESTING"] = True
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def _loan_with_principal(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "display_name": "A", "password": "pw12345"})
    pid = client.post("/api/plans", json={
        "type": "loan", "name": "Car loan", "currency": "INR", "direction": "taken",
        "interest_type": "yearly", "rate": "7.5", "start_date": "2026-01-01",
        "tenure_months": 24}).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/loan/disbursements",
                json={"amount": "3,50,000", "occurred_at": "2026-01-01T00:00:00"})
    return pid


def test_amortization_endpoint(client):
    pid = _loan_with_principal(client)
    r = client.get(f"/api/plans/{pid}/loan/amortization")
    assert r.status_code == 200
    j = r.get_json()
    assert j["available"] is True
    assert j["tenure_months"] == 24 and j["emi_minor"] > 0
    assert "scenario" not in j                              # no what-if params → baseline only

    # with extra → scenario with savings
    r2 = client.get(f"/api/plans/{pid}/loan/amortization?extra=50,000").get_json()
    assert r2["scenario"]["months"] < 24
    assert r2["scenario"]["interest_saved_minor"] > 0

    # target months
    r3 = client.get(f"/api/plans/{pid}/loan/amortization?target_months=12").get_json()
    assert r3["scenario"]["months"] <= 12
    assert r3["scenario"]["required_payment_minor"] > j["emi_minor"]


def test_amortization_needs_tenure(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "display_name": "A", "password": "pw12345"})
    pid = client.post("/api/plans", json={
        "type": "loan", "name": "L", "currency": "INR", "direction": "taken",
        "interest_type": "none", "start_date": "2026-01-01"}).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/loan/disbursements", json={"amount": "1,00,000", "occurred_at": "2026-01-01T00:00:00"})
    j = client.get(f"/api/plans/{pid}/loan/amortization").get_json()
    assert j["available"] is False and j["reason"] == "needs_tenure"
