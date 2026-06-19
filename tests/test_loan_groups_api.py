"""API tests for GET /api/plans/loans/grouped."""
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
    with app.test_client() as c:
        yield c


def _register(client, email="owner@example.com"):
    r = client.post("/api/auth/register", json={
        "email": email, "display_name": "Owner", "password": "pw12345"})
    assert r.status_code in (201, 409), r.get_json()


def _make_loan(client, name, counterparty, direction="given"):
    r = client.post("/api/plans", json={
        "type": "loan", "name": name, "currency": "INR",
        "direction": direction, "interest_type": "monthly", "rate": "3",
        "start_date": "2023-12-12", "counterparty": counterparty})
    assert r.status_code == 201, r.get_json()
    plan_id = r.get_json()["plan"]["id"]
    # add a disbursement so the loan has activity; grouping needs amount data
    dr = client.post(f"/api/plans/{plan_id}/loan/disbursements",
                     json={"amount": "1000", "occurred_at": "2023-12-12T12:00:00"})
    assert dr.status_code == 201, dr.get_json()
    return plan_id


def _login_as_other_user(client):
    """Register and authenticate a different user (replaces current session)."""
    client.post("/api/auth/logout")
    r = client.post("/api/auth/register", json={
        "email": "other@example.com", "display_name": "Other", "password": "pw12345"})
    assert r.status_code in (201, 409), r.get_json()
    if r.status_code == 409:
        client.post("/api/auth/login", json={
            "email": "other@example.com", "password": "pw12345"})


def test_grouped_endpoint_shape(client):
    _register(client)
    _make_loan(client, name="L1", counterparty="Sunil")
    _make_loan(client, name="L2", counterparty="Sunil")
    _make_loan(client, name="L3", counterparty="Bank", direction="taken")
    r = client.get("/api/plans/loans/grouped")
    assert r.status_code == 200
    body = r.get_json()
    assert "groups" in body and "base_total" in body and "sankey" in body
    names = {g["name"] for g in body["groups"]}
    assert "Sunil" in names and "Bank" in names
    sunil = [g for g in body["groups"] if g["name"] == "Sunil"][0]
    assert sunil["given"]["count"] == 2


def test_grouped_owner_only(client):
    _register(client)
    _make_loan(client, name="L", counterparty="K")
    _login_as_other_user(client)
    body = client.get("/api/plans/loans/grouped").get_json()
    assert body["groups"] == []


def test_grouped_unauth_401(client):
    client.delete_cookie("session")
    assert client.get("/api/plans/loans/grouped").status_code == 401


def test_grouped_empty(client):
    _register(client)
    body = client.get("/api/plans/loans/grouped").get_json()
    assert body["groups"] == [] and body["sankey"]["nodes"] == []
