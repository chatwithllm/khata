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


def _make_retirement(client):
    return client.post("/api/plans", json={
        "type": "retirement", "name": "401k", "currency": "INR",
        "current_age": 30, "retirement_age": 60,
        "monthly_contribution": "10,000", "annual_return": "8", "inflation": "6"})


def test_create_retirement_and_state(client):
    _register(client)
    r = _make_retirement(client)
    assert r.status_code == 201
    body = r.get_json()
    assert body["plan"]["type"] == "retirement"
    assert body["plan"]["current_age"] == 30
    assert body["plan"]["retirement_age"] == 60
    assert body["state"]["projected_corpus_minor"] == 1490359449


def test_retirement_update_changes_corpus(client):
    _register(client)
    pid = _make_retirement(client).get_json()["plan"]["id"]
    before = client.get(f"/api/plans/{pid}").get_json()["state"]["projected_corpus_minor"]
    r = client.post(f"/api/plans/{pid}/retirement/update",
                    json={"monthly_contribution": "20,000"})
    assert r.status_code == 200
    after = r.get_json()["state"]["projected_corpus_minor"]
    assert after != before
    # corpus reflects the doubled contribution (~2x, modulo half-up rounding)
    assert after == 2980718897


def test_retirement_update_auth_and_ownership(client):
    # 401 unauth
    assert client.post("/api/plans/1/retirement/update", json={}).status_code == 401
    # 403 non-owner
    _register(client, "a@b.com")
    pid = _make_retirement(client).get_json()["plan"]["id"]
    client.post("/api/auth/logout")
    _register(client, "b@b.com")
    assert client.post(f"/api/plans/{pid}/retirement/update",
                       json={"monthly_contribution": "5,000"}).status_code == 403


def test_asset_create_still_works(client):
    _register(client)
    r = client.post("/api/plans", json={
        "type": "asset", "name": "Car", "currency": "INR", "total_price": "5,00,000"})
    assert r.status_code == 201
    assert r.get_json()["plan"]["type"] == "asset"
