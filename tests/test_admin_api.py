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


def _register(client, email, name="U"):
    return client.post("/api/auth/register", json={
        "email": email, "display_name": name, "password": "pw12345"})


def _login(client, email, pw="pw12345"):
    return client.post("/api/auth/login", json={"email": email, "password": pw})


def test_first_user_is_admin_others_are_not(client):
    r = _register(client, "boss@b.com")
    assert r.get_json()["user"]["is_admin"] is True
    client.post("/api/auth/logout")
    r = _register(client, "member@b.com")
    assert r.get_json()["user"]["is_admin"] is False


def test_non_admin_cannot_use_admin_api(client):
    _register(client, "boss@b.com")
    client.post("/api/auth/logout")
    _register(client, "member@b.com")            # now logged in as the non-admin
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/users/1/disable", json={"disabled": True}).status_code == 403


def test_admin_lists_users(client):
    _register(client, "boss@b.com")
    client.post("/api/auth/logout"); _register(client, "m@b.com")
    client.post("/api/auth/logout"); _login(client, "boss@b.com")
    r = client.get("/api/admin/users")
    assert r.status_code == 200
    users = r.get_json()["users"]
    assert len(users) == 2
    assert users[0]["is_admin"] is True and users[1]["is_admin"] is False


def test_promote_and_demote(client):
    _register(client, "boss@b.com")
    client.post("/api/auth/logout"); _register(client, "m@b.com")
    client.post("/api/auth/logout"); _login(client, "boss@b.com")
    # promote member (id 2) to admin
    assert client.post("/api/admin/users/2/admin", json={"is_admin": True}).get_json()["is_admin"] is True
    # demote them back
    assert client.post("/api/admin/users/2/admin", json={"is_admin": False}).get_json()["is_admin"] is False


def test_cannot_remove_last_admin(client):
    _register(client, "boss@b.com")             # sole admin, id 1
    client.post("/api/auth/logout"); _register(client, "m@b.com")
    client.post("/api/auth/logout"); _login(client, "boss@b.com")
    r = client.post("/api/admin/users/1/admin", json={"is_admin": False})
    assert r.status_code == 400 and "last remaining admin" in r.get_json()["detail"]
    r = client.post("/api/admin/users/1/disable", json={"disabled": True})
    assert r.status_code == 400


def test_disable_blocks_login_and_session(client):
    _register(client, "boss@b.com")
    client.post("/api/auth/logout"); _register(client, "m@b.com")    # id 2
    client.post("/api/auth/logout"); _login(client, "boss@b.com")
    assert client.post("/api/admin/users/2/disable", json={"disabled": True}).status_code == 200
    client.post("/api/auth/logout")
    # disabled user can no longer log in
    r = _login(client, "m@b.com")
    assert r.status_code == 403 and r.get_json()["error"] == "account_disabled"
    # re-enable restores login
    _login(client, "boss@b.com")
    assert client.post("/api/admin/users/2/disable", json={"disabled": False}).status_code == 200
    client.post("/api/auth/logout")
    assert _login(client, "m@b.com").status_code == 200


def test_disabled_user_live_session_stops_resolving(client):
    _register(client, "boss@b.com")
    client.post("/api/auth/logout")
    _register(client, "m@b.com")                # id 2, currently logged in with a live session
    assert client.get("/api/auth/me").status_code == 200
    # admin disables them in another session
    c2 = client.application.test_client()
    _login(c2, "boss@b.com")
    c2.post("/api/admin/users/2/disable", json={"disabled": True})
    # the member's still-open session now resolves to nobody
    assert client.get("/api/auth/me").status_code == 401


def test_reset_password(client):
    _register(client, "boss@b.com")
    client.post("/api/auth/logout"); _register(client, "m@b.com")    # id 2
    client.post("/api/auth/logout"); _login(client, "boss@b.com")
    assert client.post("/api/admin/users/2/reset-password", json={"password": "newpass1"}).status_code == 200
    client.post("/api/auth/logout")
    assert _login(client, "m@b.com", "pw12345").status_code == 401   # old password dead
    assert _login(client, "m@b.com", "newpass1").status_code == 200  # new one works


def test_delete_user_removes_their_plans(client):
    _register(client, "boss@b.com")
    client.post("/api/auth/logout"); _register(client, "m@b.com")    # id 2
    # member creates a plan
    client.post("/api/plans", json={"name": "P", "currency": "INR", "total_price": "1000"})
    client.post("/api/auth/logout"); _login(client, "boss@b.com")
    r = client.delete("/api/admin/users/2")
    assert r.status_code == 200
    assert r.get_json()["plans_deleted"] == 1
    assert len(client.get("/api/admin/users").get_json()["users"]) == 1


def test_cannot_delete_or_disable_self(client):
    _register(client, "boss@b.com")             # id 1, admin
    assert client.delete("/api/admin/users/1").status_code == 400
    assert client.post("/api/admin/users/1/disable", json={"disabled": True}).status_code == 400


def test_admin_inherits_backup_access(client):
    _register(client, "boss@b.com")             # admin
    assert client.get("/api/auth/me").get_json()["is_operator"] is True
    assert client.get("/api/backup").status_code == 200
    client.post("/api/auth/logout"); _register(client, "m@b.com")     # non-admin
    assert client.get("/api/auth/me").get_json()["is_operator"] is False
    assert client.get("/api/backup").status_code == 403
