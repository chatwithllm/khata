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


def test_chit_duplicate(client):
    _reg(client); src = _mk(client).get_json()["plan"]
    pid = src["id"]
    client.post(f"/api/plans/{pid}/chit/entries", json={"kind": "chit_contribution", "amount": "50,000"})
    r = client.post(f"/api/plans/{pid}/chit/duplicate", json={"name": "C -2"})
    assert r.status_code == 201
    b = r.get_json()
    new_id = b["plan"]["id"]
    assert new_id != pid
    assert b["plan"]["name"] == "C -2"
    assert b["state"]["chit_value_minor"] == 100000000
    assert b["state"]["n_members"] == 20
    assert b["state"]["months_recorded"] == 0
    assert b["state"]["total_contributed_minor"] == 0


def test_chit_duplicate_blank_name_falls_back(client):
    _reg(client); pid = _mk(client).get_json()["plan"]["id"]
    b = client.post(f"/api/plans/{pid}/chit/duplicate", json={"name": "  "}).get_json()
    assert b["plan"]["name"] == "C -copy"


def test_chit_duplicate_rejects_non_chit(client):
    _reg(client)
    aid = client.post("/api/plans", json={"type": "asset", "name": "A", "currency": "INR",
                                          "total_price": "1,000"}).get_json()["plan"]["id"]
    assert client.post(f"/api/plans/{aid}/chit/duplicate", json={"name": "x"}).status_code == 400


def test_chit_duplicate_auth(client):
    assert client.post("/api/plans/1/chit/duplicate", json={"name": "x"}).status_code == 401


def test_chit_auth(client):
    assert client.post("/api/plans/1/chit/entries", json={}).status_code == 401
