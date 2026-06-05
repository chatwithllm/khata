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


def _mk(c):
    return c.post("/api/plans", json={"type": "chit", "name": "C", "currency": "INR",
                  "chit_value": "10,00,000", "n_members": 20, "commission": "5", "start_date": "2026-01-01"})


def test_create_chit_and_state(client):
    _reg(client); r = _mk(client)
    assert r.status_code == 201
    b = r.get_json(); assert b["plan"]["type"] == "chit"; assert b["state"]["subscription_minor"] == 5000000


def test_chit_entry_and_dividend(client):
    _reg(client); pid = _mk(client).get_json()["plan"]["id"]
    assert client.post(f"/api/plans/{pid}/chit/entries", json={"kind": "chit_contribution", "amount": "50,000"}).status_code == 201
    d = client.get(f"/api/plans/{pid}/chit/dividend?bid=1,00,000").get_json()
    assert d["dividend_per_member_minor"] == 250000 and d["prize_minor"] == 90000000
    st = client.get(f"/api/plans/{pid}").get_json()["state"]
    assert st["total_contributed_minor"] == 5000000


def test_chit_auth(client):
    assert client.post("/api/plans/1/chit/entries", json={}).status_code == 401
