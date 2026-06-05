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


def test_backup_download_and_restore_roundtrip(client):
    _setup(client)
    r = client.get("/api/backup")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    data = json.loads(r.data)
    assert data["version"] == 1
    assert len(data["tables"]["plans"]) == 1
    assert len(data["tables"]["users"]) == 1

    # restore the same backup (raw JSON body) -> matches the user by email, adds the plan
    resp = client.post("/api/restore", json=data)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["stats"]["users_matched"] == 1 and body["stats"]["users_created"] == 0
    assert body["stats"]["plans"] == 1
    # now two plots exist for the user
    plans = client.get("/api/plans").get_json()["plans"]
    assert sum(1 for p in plans if p["name"] == "Plot") == 2


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
