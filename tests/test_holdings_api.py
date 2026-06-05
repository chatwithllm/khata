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


def test_create_holding_and_state(client):
    _register(client)
    r = _make_gold(client)
    assert r.status_code == 201
    body = r.get_json()
    assert body["plan"]["type"] == "holding"
    assert body["plan"]["asset_class"] == "gold"
    assert body["state"]["qty_held_micro"] == 0
    assert body["state"]["current_value_minor"] is None


def test_buy_then_quote_state(client):
    _register(client)
    pid = _make_gold(client).get_json()["plan"]["id"]
    # buy 10 g for ₹5,00,000 (avg ₹50,000/g)
    r = client.post(f"/api/plans/{pid}/holding/buys", json={
        "quantity": "10", "amount": "5,00,000"})
    assert r.status_code == 201
    assert r.get_json()["state"]["qty_held_micro"] == 10_000_000
    # spot now ₹60,000/g
    r = client.post(f"/api/plans/{pid}/holding/quote", json={"price": "60,000"})
    assert r.status_code == 200
    st = r.get_json()["state"]
    assert st["current_value_minor"] == 60000000        # ₹6,00,000 = 60,000/g × 10 g
    assert st["unrealized_gain_minor"] == 10000000       # +₹1,00,000 over cost of held


def test_sell_endpoint(client):
    _register(client)
    pid = _make_gold(client).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/holding/buys", json={"quantity": "10", "amount": "5,00,000"})
    r = client.post(f"/api/plans/{pid}/holding/sells", json={"quantity": "4", "amount": "2,40,000"})
    assert r.status_code == 201
    assert r.get_json()["state"]["qty_held_micro"] == 6_000_000


def test_oversell_400(client):
    _register(client)
    pid = _make_gold(client).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/holding/buys", json={"quantity": "2", "amount": "1,00,000"})
    r = client.post(f"/api/plans/{pid}/holding/sells", json={"quantity": "3", "amount": "1,80,000"})
    assert r.status_code == 400


def test_float_quantity_400(client):
    _register(client)
    pid = _make_gold(client).get_json()["plan"]["id"]
    r = client.post(f"/api/plans/{pid}/holding/buys", json={"quantity": 10.5, "amount": "5,00,000"})
    assert r.status_code == 400


def test_holding_auth_and_ownership(client):
    # 401 unauth
    assert client.post("/api/plans/1/holding/buys", json={}).status_code == 401
    # 403 non-owner
    _register(client, "a@b.com")
    pid = _make_gold(client).get_json()["plan"]["id"]
    client.post("/api/auth/logout")
    _register(client, "b@b.com")
    assert client.post(f"/api/plans/{pid}/holding/buys",
                       json={"quantity": "1", "amount": "50000"}).status_code == 403
