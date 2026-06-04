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
        "email": email, "display_name": "Arjun", "password": "pw12345"})


def test_create_set_pay_and_state(client):
    _register(client)
    r = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "10,00,000",
        "installments": [{"amount": "2,50,000"}, {"amount": "2,50,000"},
                         {"amount": "2,50,000"}, {"amount": "2,50,000"}]})
    assert r.status_code == 201
    pid = r.get_json()["plan"]["id"]

    r = client.post(f"/api/plans/{pid}/payments", json={
        "amount": "3,00,000", "method": "transfer", "funding_source": "savings"})
    assert r.status_code == 201
    st = r.get_json()["state"]
    assert st["paid_to_date_minor"] == 30000000
    assert st["remaining_minor"] == 70000000
    assert st["installments"][0]["status"] == "paid"
    assert st["installments"][1]["status"] == "partial"

    r = client.get(f"/api/plans/{pid}")
    assert r.status_code == 200
    assert r.get_json()["state"]["funding_breakdown"][0]["source"] == "savings"

    r = client.get("/api/plans")
    assert len(r.get_json()["plans"]) == 1


def test_auth_required(client):
    # every endpoint rejects an unauthenticated caller
    assert client.get("/api/plans").status_code == 401
    assert client.post("/api/plans", json={}).status_code == 401
    assert client.get("/api/plans/1").status_code == 401
    assert client.post("/api/plans/1/installments", json={}).status_code == 401
    assert client.post("/api/plans/1/payments", json={}).status_code == 401


def test_ownership_enforced(client):
    _register(client, "a@b.com")
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1000"}).get_json()["plan"]["id"]
    client.post("/api/auth/logout")
    _register(client, "b@b.com")
    # user B cannot read or mutate user A's plan
    assert client.get(f"/api/plans/{pid}").status_code == 403
    assert client.post(f"/api/plans/{pid}/installments",
                       json={"installments": []}).status_code == 403
    assert client.post(f"/api/plans/{pid}/payments",
                       json={"amount": "100", "method": "cash",
                             "funding_source": "savings"}).status_code == 403


def test_validation_error_returns_400(client):
    _register(client)
    r = client.post("/api/plans", json={"name": "P", "currency": "INR", "total_price": "0"})
    assert r.status_code == 400


def test_float_amount_returns_400_not_500(client):
    _register(client)
    r = client.post("/api/plans", json={"name": "P", "currency": "INR", "total_price": 1000.50})
    assert r.status_code == 400
