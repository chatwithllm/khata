import io
import json

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


def _setup(client, email="a@b.com"):
    client.post("/api/auth/register", json={
        "email": email, "display_name": "Arjun", "password": "pw12345"})
    client.post("/api/plans", json={"name": "Plot", "currency": "INR", "total_price": "10,00,000"})


def test_backup_requires_auth(client):
    assert client.get("/api/backup").status_code == 401
    assert client.post("/api/restore", json={"tables": {}}).status_code == 401


def test_backup_operator_only(client):
    # first registered user = operator; a second member is forbidden
    client.post("/api/auth/register", json={
        "email": "owner@b.com", "display_name": "Owner", "password": "pw12345"})
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={
        "email": "member@b.com", "display_name": "Member", "password": "pw12345"})
    # logged in as the 2nd user (a non-operator)
    assert client.get("/api/backup").status_code == 403
    assert client.post("/api/restore", json={"version": 1, "tables": {}}).status_code == 403
    # the operator can
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "owner@b.com", "password": "pw12345"})
    assert client.get("/api/backup").status_code == 200


def test_backup_download_and_restore_replaces(client):
    _setup(client)
    r = client.get("/api/backup")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    data = json.loads(r.data)
    assert data["version"] == 1
    assert len(data["tables"]["plans"]) == 1
    assert len(data["tables"]["users"]) == 1

    # restore the same backup (raw JSON body) -> REPLACES: still exactly one plan
    resp = client.post("/api/restore", json=data)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["logged_out"] is False
    assert body["stats"]["users"] == 1
    assert body["stats"]["plans"] == 1
    plans = client.get("/api/plans").get_json()["plans"]
    assert sum(1 for p in plans if p["name"] == "Plot") == 1


def test_restore_removes_data_not_in_backup(client):
    _setup(client)
    data = json.loads(client.get("/api/backup").data)
    # create a second plan AFTER taking the backup
    client.post("/api/plans", json={"name": "Later", "currency": "INR", "total_price": "1,000"})
    assert len(client.get("/api/plans").get_json()["plans"]) == 2
    resp = client.post("/api/restore", json=data)
    assert resp.status_code == 200
    plans = client.get("/api/plans").get_json()["plans"]
    assert [p["name"] for p in plans] == ["Plot"]


def test_restore_session_survives_when_operator_in_backup(client):
    _setup(client)
    data = json.loads(client.get("/api/backup").data)
    assert client.post("/api/restore", json=data).status_code == 200
    # same cookie still authenticates (session re-pointed by email)
    assert client.get("/api/backup").status_code == 200


def test_restore_logs_out_when_operator_absent_from_backup(client):
    _setup(client)
    data = json.loads(client.get("/api/backup").data)
    data["tables"]["users"][0]["email"] = "someone-else@b.com"
    resp = client.post("/api/restore", json=data)
    assert resp.status_code == 200
    assert resp.get_json()["logged_out"] is True
    # session cleared — next request is unauthenticated
    assert client.get("/api/backup").status_code == 401


def test_restore_rejects_backup_with_no_users(client):
    _setup(client)
    r = client.post("/api/restore", json={"version": 1, "tables": {"users": []}})
    assert r.status_code == 400
    # instance untouched
    assert len(client.get("/api/plans").get_json()["plans"]) == 1


def test_restore_via_multipart_file(client):
    _setup(client)
    data = json.loads(client.get("/api/backup").data)
    buf = io.BytesIO(json.dumps(data).encode())
    resp = client.post("/api/restore", data={"file": (buf, "backup.json")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["stats"]["plans"] == 1


def test_restore_rejects_garbage(client):
    _setup(client)
    assert client.post("/api/restore", json={"not": "a backup"}).status_code == 400
    buf = io.BytesIO(b"this is not json")
    r = client.post("/api/restore", data={"file": (buf, "x.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
