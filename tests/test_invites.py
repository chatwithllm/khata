import pytest

from khata import create_app
from khata.config import Config
from khata.db import Base
from khata.tokens import issue_invite, read_invite


@pytest.fixture
def app():
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    a = create_app(cfg)
    a.config["TESTING"] = True
    Base.metadata.create_all(a.config["ENGINE"])
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def _admin(client):
    return client.post("/api/auth/register", json={
        "email": "boss@b.com", "display_name": "Boss", "password": "pw12345"})


# ---------- token ----------

def test_invite_token_roundtrip_and_tamper():
    secret = "s3cret"
    tok = issue_invite(secret, "New@Person.com")
    assert read_invite(secret, tok) == "new@person.com"      # normalized
    assert read_invite("other-secret", tok) is None          # wrong key
    assert read_invite(secret, "garbage") is None


# ---------- admin mints invite ----------

def test_admin_creates_invite_link(client):
    _admin(client)
    r = client.post("/api/admin/invites", json={"email": "mate@b.com"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["email"] == "mate@b.com"
    assert "/join?token=" in j["join_url"]
    assert j["already_member"] is False


def test_invite_rejects_bad_email_and_non_admin(client):
    _admin(client)
    assert client.post("/api/admin/invites", json={"email": "nope"}).status_code == 400
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "m@b.com", "display_name": "M", "password": "pw12345"})
    assert client.post("/api/admin/invites", json={"email": "x@y.com"}).status_code == 403


# ---------- peek + accept ----------

def test_invite_peek_and_accept_flow(client, app):
    _admin(client)
    token = client.post("/api/admin/invites", json={"email": "mate@b.com"}).get_json()["token"]
    client.post("/api/auth/logout")

    # peek (public)
    info = client.get(f"/api/auth/invite?token={token}").get_json()
    assert info["valid"] is True and info["email"] == "mate@b.com" and info["already_member"] is False

    # accept → creates the account (email bound by token), signs in, NOT admin
    r = client.post("/api/auth/accept-invite", json={"token": token, "display_name": "Mate", "password": "pw12345"})
    assert r.status_code == 201
    u = r.get_json()["user"]
    assert u["email"] == "mate@b.com" and u["is_admin"] is False
    assert client.get("/api/auth/me").status_code == 200          # logged in

    # the new account can log in with the chosen password
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "mate@b.com", "password": "pw12345"}).status_code == 200


def test_accept_invite_rejects_bad_token_and_short_password(client):
    _admin(client)
    token = client.post("/api/admin/invites", json={"email": "mate@b.com"}).get_json()["token"]
    assert client.post("/api/auth/accept-invite", json={"token": "bad", "display_name": "X", "password": "pw12345"}).status_code == 400
    assert client.post("/api/auth/accept-invite", json={"token": token, "display_name": "X", "password": "123"}).status_code == 400


def test_accept_invite_for_existing_email_is_conflict(client):
    _admin(client)                                  # boss@b.com exists
    token = client.post("/api/admin/invites", json={"email": "boss@b.com"}).get_json()["token"]
    assert client.get(f"/api/auth/invite?token={token}").get_json()["already_member"] is True
    r = client.post("/api/auth/accept-invite", json={"token": token, "display_name": "X", "password": "pw12345"})
    assert r.status_code == 409 and r.get_json()["error"] == "already_member"


def test_expired_or_invalid_token_peek(client):
    assert client.get("/api/auth/invite?token=nonsense").get_json()["valid"] is False


# ---------- join page served ----------

def test_join_page_served(client):
    r = client.get("/join")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/auth/invite", "/api/auth/accept-invite", "accept-invite", "token"]:
        assert needle in body
