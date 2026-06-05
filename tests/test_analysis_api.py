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


def _reg(c): return c.post("/api/auth/register", json={"email": "a@b.com", "display_name": "A", "password": "pw12345"})


def test_analysis_requires_auth(client):
    assert client.get("/api/analysis/hold-vs-sell").status_code == 401


def test_analysis_hold_vs_sell(client):
    _reg(client)
    r = client.get("/api/analysis/hold-vs-sell",
                   query_string={"asset_value": "10,00,000", "appreciation": "10",
                                 "borrow": "6,00,000", "interest": "9", "horizon": "18"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["net_hold_advantage_minor"] == 8011233 and d["verdict"] == "hold"


def test_analysis_bad_input_400(client):
    _reg(client)
    assert client.get("/api/analysis/hold-vs-sell",
                      query_string={"asset_value": "abc", "appreciation": "10", "borrow": "6,00,000",
                                    "interest": "9", "horizon": "18"}).status_code == 400
