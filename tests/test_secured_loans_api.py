import pytest

from khata import create_app
from khata.config import Config
from khata.db import Base


@pytest.fixture
def client():
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    app = create_app(cfg)
    app.config["TESTING"] = True
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def _register(client, email="a@b.com"):
    return client.post("/api/auth/register", json={
        "email": email, "display_name": "A", "password": "pw12345"})


def _make_gold(client):
    return client.post("/api/plans", json={
        "type": "holding", "name": "Gold 22K", "currency": "INR",
        "asset_class": "gold", "unit": "gram", "purity": "22K"})


def _make_loan(client, direction="taken"):
    return client.post("/api/plans", json={
        "type": "loan", "name": "Gold loan", "currency": "INR",
        "direction": direction, "interest_type": "none", "start_date": "2026-01-01"})


def _quoted_holding_worth_1cr(client):
    """Holding worth ₹1,00,00,000: buy 10 units for ₹10,00,000, quote ₹1,00,000/unit."""
    hid = _make_gold(client).get_json()["plan"]["id"]
    client.post(f"/api/plans/{hid}/holding/buys", json={"quantity": "10", "amount": "10,00,000"})
    client.post(f"/api/plans/{hid}/holding/quote", json={"price": "1,00,000"})
    return hid


def _disbursed_loan_6l(client):
    """Taken loan disbursed ₹6,00,000. Explicit past occurred_at so the disbursement is
    never seen as 'future' — default now()=UTC can land a day ahead of local date.today()
    on machines whose TZ is behind UTC, which would zero out principal_outstanding."""
    lid = _make_loan(client).get_json()["plan"]["id"]
    client.post(f"/api/plans/{lid}/loan/disbursements",
                json={"amount": "6,00,000", "occurred_at": "2026-01-01T00:00:00"})
    return lid


def test_link_collateral_sets_secured_and_ltv(client):
    _register(client)
    hid = _quoted_holding_worth_1cr(client)
    lid = _disbursed_loan_6l(client)
    r = client.post(f"/api/plans/{lid}/loan/collateral",
                    json={"collateral_plan_id": hid})
    assert r.status_code == 200
    st = r.get_json()["state"]
    assert st["secured"] is True
    assert st["collateral"]["plan_id"] == hid
    assert st["collateral"]["value_minor"] == 100000000
    assert st["collateral"]["ltv_pct"] == 60       # 6,00,000 / 1,00,00,000 = 60%


def test_unlink_collateral(client):
    _register(client)
    hid = _quoted_holding_worth_1cr(client)
    lid = _disbursed_loan_6l(client)
    client.post(f"/api/plans/{lid}/loan/collateral", json={"collateral_plan_id": hid})
    r = client.post(f"/api/plans/{lid}/loan/collateral", json={"collateral_plan_id": None})
    assert r.status_code == 200
    st = r.get_json()["state"]
    assert st["secured"] is False
    assert st["collateral"] is None


def test_non_holding_collateral_rejected(client):
    _register(client)
    lid = _disbursed_loan_6l(client)
    # pledge the loan's own (non-holding) id as collateral → 400
    r = client.post(f"/api/plans/{lid}/loan/collateral", json={"collateral_plan_id": lid})
    assert r.status_code == 400


def test_collateral_unauthenticated(client):
    assert client.post("/api/plans/1/loan/collateral",
                       json={"collateral_plan_id": 2}).status_code == 401


def test_collateral_non_owner_forbidden(client):
    _register(client, "a@b.com")
    hid = _quoted_holding_worth_1cr(client)
    lid = _disbursed_loan_6l(client)
    client.post("/api/auth/logout")
    _register(client, "b@b.com")
    r = client.post(f"/api/plans/{lid}/loan/collateral", json={"collateral_plan_id": hid})
    assert r.status_code == 403


def test_create_loan_with_inline_collateral(client):
    _register(client)
    hid = _quoted_holding_worth_1cr(client)
    r = client.post("/api/plans", json={
        "type": "loan", "name": "GL", "currency": "INR", "direction": "taken",
        "interest_type": "none", "start_date": "2026-01-01",
        "collateral_plan_id": hid})
    assert r.status_code == 201
    body = r.get_json()
    assert body["plan"]["secured"] is True
    assert body["state"]["secured"] is True
    assert body["state"]["collateral"]["plan_id"] == hid
