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


def _google_client(verifier, client_id="test-cid"):
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    cfg.google_client_id = client_id
    app = create_app(cfg)
    app.config["TESTING"] = True
    app.config["GOOGLE_VERIFIER"] = verifier
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def test_auth_config_reports_client_id():
    c = _google_client(lambda cred, cid: {}, client_id="abc.apps.googleusercontent.com")
    r = c.get("/api/auth/config")
    assert r.status_code == 200
    assert r.get_json()["google_client_id"] == "abc.apps.googleusercontent.com"


def test_auth_config_null_when_unset(client):
    r = client.get("/api/auth/config")
    assert r.status_code == 200
    assert r.get_json()["google_client_id"] is None


def test_google_login_creates_and_sets_session():
    claims = {"sub": "z-1", "email": "z@b.com", "email_verified": True, "name": "Zoya"}
    c = _google_client(lambda cred, cid: claims)
    r = c.post("/api/auth/google", json={"credential": "fake"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["created"] is True
    assert body["user"]["email"] == "z@b.com"
    # session established → /me works
    assert c.get("/api/auth/me").status_code == 200


def test_google_login_not_configured_503(client):
    # default Config() has no google_client_id
    r = client.post("/api/auth/google", json={"credential": "fake"})
    assert r.status_code == 503
    assert r.get_json()["error"] == "google_not_configured"


def test_google_login_invalid_token_401():
    from khata.services.auth import GoogleAuthError

    def bad(cred, cid):
        raise GoogleAuthError("bad signature")

    c = _google_client(bad)
    r = c.post("/api/auth/google", json={"credential": "fake"})
    assert r.status_code == 401
    assert r.get_json()["error"] == "invalid_token"


def test_google_login_unverified_email_403():
    claims = {"sub": "z-2", "email": "z2@b.com", "email_verified": False, "name": "Z2"}
    c = _google_client(lambda cred, cid: claims)
    r = c.post("/api/auth/google", json={"credential": "fake"})
    assert r.status_code == 403
    assert r.get_json()["error"] == "email_unverified"


def test_set_and_change_password(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "display_name": "A", "password": "pw12345"})
    assert client.post("/api/auth/password", json={"password": "x"}).status_code == 400
    assert client.post("/api/auth/password", json={"password": "newpw99"}).status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "a@b.com", "password": "newpw99"}).status_code == 200


def test_password_requires_auth(client):
    assert client.post("/api/auth/password", json={"password": "newpw99"}).status_code == 401


def test_update_profile_api(client):
    client.post("/api/auth/register", json={"email": "a@b.com", "display_name": "Old", "password": "pw12345"})
    r = client.post("/api/auth/profile", json={"display_name": "New Name"})
    assert r.status_code == 200 and r.get_json()["user"]["display_name"] == "New Name"
    assert client.post("/api/auth/profile", json={"display_name": "  "}).status_code == 400
    assert client.get("/api/auth/me").get_json()["user"]["has_password"] is True


_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAA"
        "C0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def test_avatar_set_clear_and_in_me(client):
    client.post("/api/auth/register", json={
        "email": "a@b.com", "display_name": "Arjun", "password": "pw12345"})
    assert client.get("/api/auth/me").get_json()["user"]["avatar"] is None
    # set a (tiny) image data URL
    r = client.post("/api/auth/avatar", json={"avatar": _PNG})
    assert r.status_code == 200 and r.get_json()["user"]["avatar"] == _PNG
    assert client.get("/api/auth/me").get_json()["user"]["avatar"] == _PNG
    # clear it
    assert client.post("/api/auth/avatar", json={"avatar": None}).get_json()["user"]["avatar"] is None


def test_avatar_rejects_non_image_and_oversize(client):
    client.post("/api/auth/register", json={
        "email": "a@b.com", "display_name": "Arjun", "password": "pw12345"})
    assert client.post("/api/auth/avatar", json={"avatar": "not-a-data-url"}).status_code == 400
    big = "data:image/png;base64," + ("A" * 200001)
    assert client.post("/api/auth/avatar", json={"avatar": big}).status_code == 413


def test_avatar_requires_auth(client):
    assert client.post("/api/auth/avatar", json={"avatar": _PNG}).status_code == 401
