import json
import os
from datetime import datetime, timedelta

import pytest

from khata import create_app
from khata.config import Config
from khata.db import Base, make_engine, make_session_factory
from khata.models import User, BackupConfig
from khata.services import backup_store


# ---------- pure scheduling logic ----------

def _cfg(**kw):
    c = BackupConfig(id=1, enabled=True, frequency="daily", hour=3, retention=14)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_is_due_respects_enabled_hour_and_last_run():
    now = datetime(2026, 6, 11, 5, 0)        # 5am
    assert backup_store.is_due(_cfg(enabled=False), now) is False        # disabled
    assert backup_store.is_due(_cfg(hour=9), now) is False               # before the hour
    assert backup_store.is_due(_cfg(last_run_at=None), now) is True      # never run
    assert backup_store.is_due(_cfg(last_run_at=datetime(2026, 6, 11, 4)), now) is False  # already today
    assert backup_store.is_due(_cfg(last_run_at=datetime(2026, 6, 10, 4)), now) is True   # yesterday


def test_weekly_threshold():
    now = datetime(2026, 6, 11, 5, 0)
    assert backup_store.is_due(_cfg(frequency="weekly", last_run_at=now - timedelta(days=8)), now) is True
    assert backup_store.is_due(_cfg(frequency="weekly", last_run_at=now - timedelta(days=3)), now) is False


def test_safe_backup_name():
    assert backup_store.safe_backup_name("auto-20260611-030000.json") == "auto-20260611-030000.json"
    assert backup_store.safe_backup_name("../../etc/passwd") is None
    assert backup_store.safe_backup_name("auto-foo.json") is None
    assert backup_store.safe_backup_name("pre-restore-x.json") is None


# ---------- file-backed store ----------

@pytest.fixture
def file_db(tmp_path):
    url = f"sqlite:///{tmp_path}/t.db"
    e = make_engine(url)
    Base.metadata.create_all(e)
    S = make_session_factory(e)
    with S() as s:
        s.add(User(email="o@b.com", display_name="O", password_hash="h"))
        s.commit()
    return url, S, str(tmp_path)


def test_run_backup_writes_and_prunes(file_db):
    url, S, base = file_db
    directory = backup_store.backups_dir(url)
    # 16 backups, retention 14 → 2 pruned, 14 kept, newest survive
    kept = None
    with S() as s:
        for i in range(16):
            stamp = f"202606{10 + i:02d}-030000"
            backup_store.run_backup(s, database_url=url, retention=14, stamp=stamp)
            kept = stamp
    files = backup_store.list_backups(directory)
    assert len(files) == 14
    assert files[0]["filename"] == f"auto-{kept}.json"     # newest first
    # snapshot is valid JSON with the exported tables
    with open(os.path.join(directory, files[0]["filename"])) as fh:
        data = json.load(fh)
    assert "users" in data["tables"] and len(data["tables"]["users"]) == 1


def test_claim_due_is_atomic(file_db):
    url, S, base = file_db
    now = datetime(2026, 6, 11, 5, 0)
    with S() as s:
        cfg = backup_store.get_config(s)
        cfg.enabled = True; cfg.hour = 0; cfg.frequency = "daily"; cfg.last_run_at = None
        s.commit()
    # two independent sessions race; exactly one wins the slot
    with S() as s1, S() as s2:
        first = backup_store.claim_due(s1, now=now)
        second = backup_store.claim_due(s2, now=now)
    assert (first, second) == (True, False)


# ---------- admin API ----------

@pytest.fixture
def client(tmp_path):
    cfg = Config()
    cfg.database_url = f"sqlite:///{tmp_path}/api.db"
    app = create_app(cfg)
    app.config["TESTING"] = True
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def _admin(client):
    return client.post("/api/auth/register", json={
        "email": "boss@b.com", "display_name": "Boss", "password": "pw12345"})


def test_backup_config_admin_only(client):
    _admin(client); client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "m@b.com", "display_name": "M", "password": "pw12345"})
    assert client.get("/api/admin/backup-config").status_code == 403


def test_update_config_validates(client):
    _admin(client)
    assert client.post("/api/admin/backup-config", json={"frequency": "hourly"}).status_code == 400
    assert client.post("/api/admin/backup-config", json={"hour": 30}).status_code == 400
    assert client.post("/api/admin/backup-config", json={"retention": 0}).status_code == 400
    r = client.post("/api/admin/backup-config", json={"enabled": True, "frequency": "weekly", "hour": 2, "retention": 7})
    c = r.get_json()["config"]
    assert c["enabled"] and c["frequency"] == "weekly" and c["hour"] == 2 and c["retention"] == 7


def test_run_now_list_download_delete(client):
    _admin(client)
    r = client.post("/api/admin/backup-run")
    assert r.status_code == 201
    fn = r.get_json()["filename"]
    # appears in listing
    cfg = client.get("/api/admin/backup-config").get_json()
    assert fn in [b["filename"] for b in cfg["backups"]]
    assert cfg["config"]["last_status"].startswith("ok")
    # download returns valid JSON snapshot
    d = client.get(f"/api/admin/backups/{fn}")
    assert d.status_code == 200 and d.mimetype == "application/json"
    assert "tables" in json.loads(d.data)
    # path-traversal rejected
    assert client.get("/api/admin/backups/..%2f..%2fapi.db").status_code in (400, 404)
    # delete
    assert client.delete(f"/api/admin/backups/{fn}").status_code == 200
    assert fn not in [b["filename"] for b in client.get("/api/admin/backup-config").get_json()["backups"]]
