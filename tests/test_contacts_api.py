"""Contacts API: CRUD + rollup + loan-contact assignment."""
from khata import create_app
from khata.config import Config
from khata.db import Base
import pytest


@pytest.fixture
def client():
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    app = create_app(cfg)
    app.config["TESTING"] = True
    Base.metadata.create_all(app.config["ENGINE"])
    with app.test_client() as c:
        c.post("/api/auth/register", json={
            "email": "owner@example.com", "display_name": "Owner", "password": "pw12345"})
        yield c


def _make_loan(client):
    r = client.post("/api/plans", json={
        "type": "loan", "name": "Test Loan", "currency": "INR",
        "direction": "taken", "interest_type": "none", "start_date": "2026-01-01"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["plan"]["id"]


def _login_as_other_user(client):
    """Register and authenticate a different user (replaces current session)."""
    client.post("/api/auth/logout")
    r = client.post("/api/auth/register", json={
        "email": "other@example.com", "display_name": "Other", "password": "pw12345"})
    assert r.status_code in (201, 409), r.get_json()
    if r.status_code == 409:
        client.post("/api/auth/login", json={
            "email": "other@example.com", "password": "pw12345"})


def test_contact_crud_and_rollup(client):
    r = client.post("/api/contacts", json={"name": "Karunakar", "phone": "+91 99"})
    assert r.status_code == 201
    cid = r.get_json()["contact"]["id"]
    assert client.get("/api/contacts").get_json()["contacts"][0]["name"] == "Karunakar"
    r = client.get(f"/api/contacts/{cid}")
    assert r.status_code == 200 and "rollup" in r.get_json()
    assert client.patch(f"/api/contacts/{cid}", json={"phone": "+91 11"}).status_code == 200
    assert client.delete(f"/api/contacts/{cid}").status_code == 204


def test_contact_owner_only(client):
    cid = client.post("/api/contacts", json={"name": "K"}).get_json()["contact"]["id"]
    _login_as_other_user(client)
    assert client.get(f"/api/contacts/{cid}").status_code in (403, 404)
    assert client.delete(f"/api/contacts/{cid}").status_code in (403, 404)


def test_assign_loan_to_contact(client):
    cid = client.post("/api/contacts", json={"name": "K"}).get_json()["contact"]["id"]
    pid = _make_loan(client)
    r = client.post(f"/api/plans/{pid}/loan/contact", json={"contact_id": cid})
    assert r.status_code == 200
    assert client.get(f"/api/contacts/{cid}").get_json()["rollup"]["loan_count"] == 1
    assert client.post(f"/api/plans/{pid}/loan/contact", json={"contact_id": None}).status_code == 200


def test_create_contact_requires_name_400(client):
    assert client.post("/api/contacts", json={"name": "  "}).status_code == 400
