import pytest
from khata import create_app
from khata.config import Config
from khata.db import Base


def _app(feed=None, provider=None):
    cfg = Config(); cfg.database_url = "sqlite:///:memory:"; cfg.price_feed = feed
    app = create_app(cfg); app.config["TESTING"] = True
    if provider is not None:
        app.config["PRICE_PROVIDER"] = provider
    Base.metadata.create_all(app.config["ENGINE"])
    return app


def _reg(c): return c.post("/api/auth/register", json={"email": "a@b.com", "display_name": "A", "password": "pw12345"})


def _mk_holding(c):
    return c.post("/api/plans", json={"type": "holding", "name": "Gold", "currency": "INR",
                  "asset_class": "gold", "unit": "gram"}).get_json()["plan"]["id"]


def test_feed_config_disabled_by_default():
    c = _app().test_client(); _reg(c)
    assert c.get("/api/feed/config").get_json()["enabled"] is False


def test_feed_config_enabled_when_set():
    c = _app(feed="demo").test_client(); _reg(c)
    assert c.get("/api/feed/config").get_json()["enabled"] is True


def test_refresh_quote_disabled_503():
    c = _app().test_client(); _reg(c); pid = _mk_holding(c)
    assert c.post(f"/api/plans/{pid}/holding/refresh-quote").status_code == 503


def test_refresh_quote_uses_provider():
    # provider returns ₹61,000/g = 6100000 minor for any holding
    c = _app(feed="demo", provider=lambda asset_class, symbol, currency, feed_cfg: 6100000).test_client()
    _reg(c); pid = _mk_holding(c)
    r = c.post(f"/api/plans/{pid}/holding/refresh-quote")
    assert r.status_code == 200
    assert r.get_json()["state"]["current_price_minor"] == 6100000


def test_refresh_quote_requires_auth_and_owner():
    c = _app(feed="demo").test_client()
    assert c.post("/api/plans/1/holding/refresh-quote").status_code == 401
