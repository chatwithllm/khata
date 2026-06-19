"""Owner-only create / list / revoke share-link endpoints."""
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


def _register(client, email="owner@example.com"):
    return client.post("/api/auth/register", json={
        "email": email, "display_name": "Owner", "password": "pw12345"})


def _make_plan(client):
    """Create a simple asset plan and return its id."""
    r = client.post("/api/plans", json={
        "type": "asset", "name": "Test Plan", "currency": "INR", "total_price": "10000"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["plan"]["id"]


def _login_as_other_user(client):
    """Register and authenticate a different user (replaces current session)."""
    client.post("/api/auth/logout")
    r = client.post("/api/auth/register", json={
        "email": "other@example.com", "display_name": "Other", "password": "pw12345"})
    assert r.status_code in (201, 409), r.get_json()
    if r.status_code == 409:
        # already exists from a previous test run in this fixture scope — just login
        client.post("/api/auth/login", json={
            "email": "other@example.com", "password": "pw12345"})


def test_create_list_revoke_share(client):
    _register(client)
    pid = _make_plan(client)

    # create
    r = client.post(f"/api/plans/{pid}/shares", json={"scope": "summary", "ttl_days": 30})
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    assert "url" in body
    assert "share" in body
    assert body["url"].endswith("/s/" + body["share"]["token"])
    sid = body["share"]["id"]

    # list — should see 1 active share
    r = client.get(f"/api/plans/{pid}/shares")
    assert r.status_code == 200
    shares = r.get_json()["shares"]
    assert len(shares) == 1

    # revoke
    r = client.delete(f"/api/plans/{pid}/shares/{sid}")
    assert r.status_code == 204

    # list again — share should be revoked
    r = client.get(f"/api/plans/{pid}/shares")
    assert r.status_code == 200
    shares = r.get_json()["shares"]
    assert shares[0]["status"] == "revoked"


def test_create_share_bad_input_400(client):
    _register(client)
    pid = _make_plan(client)

    # invalid scope
    assert client.post(
        f"/api/plans/{pid}/shares",
        json={"scope": "x", "ttl_days": 30},
    ).status_code == 400

    # invalid ttl_days (5 is not in {7, 30, 90})
    assert client.post(
        f"/api/plans/{pid}/shares",
        json={"scope": "full", "ttl_days": 5},
    ).status_code == 400


def test_share_owner_only_403(client):
    _register(client)
    pid = _make_plan(client)
    _login_as_other_user(client)
    assert client.post(
        f"/api/plans/{pid}/shares",
        json={"scope": "summary", "ttl_days": 7},
    ).status_code == 403
