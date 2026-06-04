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
    # create schema on the app's engine
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def test_register_login_me_logout_flow(client):
    r = client.post("/api/auth/register", json={
        "email": "a@b.com", "display_name": "Arjun", "password": "pw12345"})
    assert r.status_code == 201
    assert r.get_json()["user"]["email"] == "a@b.com"

    # session established by register → /me works
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.get_json()["user"]["display_name"] == "Arjun"

    client.post("/api/auth/logout")
    r = client.get("/api/auth/me")
    assert r.status_code == 401

    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "pw12345"})
    assert r.status_code == 200

    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "bad"})
    assert r.status_code == 401


def test_duplicate_register_conflicts(client):
    payload = {"email": "a@b.com", "display_name": "A", "password": "pw12345"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    assert client.post("/api/auth/register", json=payload).status_code == 409
