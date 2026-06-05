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


def test_networth_requires_auth(client):
    assert client.get("/api/networth").status_code == 401


def test_networth_empty_shape(client):
    _register(client)
    r = client.get("/api/networth")
    assert r.status_code == 200
    d = r.get_json()
    assert d["base_currency"] == "INR"
    assert d["assets_minor"] == 0 and d["liabilities_minor"] == 0
    assert d["net_worth_minor"] == 0
    assert d["holdings"] == [] and d["unpriced"] == [] and d["unconverted"] == {}


def test_set_base_currency(client):
    _register(client)
    assert client.post("/api/base-currency", json={"currency": "USD"}).status_code == 200
    assert client.get("/api/networth").get_json()["base_currency"] == "USD"
    assert client.post("/api/base-currency", json={"currency": "EUR"}).status_code == 400


def test_set_fx_rate_and_convert(client):
    _register(client)
    # base INR (default); set USD rate
    r = client.post("/api/fx-rates", json={"quote": "USD", "rate": "83.42"})
    assert r.status_code == 201
    assert r.get_json()["rate_micro"] == 83_420_000
    # bad rate (float) → 400
    assert client.post("/api/fx-rates", json={"quote": "USD", "rate": 83.42}).status_code == 400
    # create a USD holding worth $1.00 and confirm it converts into assets
    pid = client.post("/api/plans", json={
        "type": "holding", "name": "USX", "currency": "USD",
        "asset_class": "equity", "unit": "share"}).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/holding/buys", json={"quantity": "10", "amount": "8"})
    client.post(f"/api/plans/{pid}/holding/quote", json={"price": "0.10"})  # $0.10/share ×10 = $1.00
    d = client.get("/api/networth").get_json()
    assert d["assets_minor"] == 8342    # $1.00 → 100 USD-minor → ×83.42 = 8342 INR-minor
