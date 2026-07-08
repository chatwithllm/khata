import io

import pytest

from khata import create_app
from khata.config import Config
from khata.db import Base

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


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


def _login(client, email):
    client.post("/api/auth/logout")
    return client.post("/api/auth/login", json={"email": email, "password": "pw12345"})


def _setup(client):
    """owner + member on a plan; member logs an in-transit hop. Returns (pid, hop_id)."""
    _register(client, "own@x.com", "Owner")
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "5,00,000"}).get_json()["plan"]["id"]
    _register(client, "mem@x.com", "Member")
    _login(client, "own@x.com")
    client.post(f"/api/plans/{pid}/members", json={"email": "mem@x.com"})
    _login(client, "mem@x.com")
    client.post(f"/api/invitations/{pid}/accept")
    members = client.get(f"/api/plans/{pid}/members").get_json()["members"]
    own_id = next(m["user_id"] for m in members if m["email"] == "own@x.com")
    hop_id = client.post(f"/api/plans/{pid}/hops", json={
        "amount": "1,000", "method": "transfer",
        "to_user_id": own_id}).get_json()["hop"]["id"]
    return pid, hop_id


def _upload(client, pid, hop_id, name="receipt.png"):
    return client.post(f"/api/plans/{pid}/hops/{hop_id}/attachments",
                       data={"file": (io.BytesIO(PNG), name)},
                       content_type="multipart/form-data")


def test_logger_uploads_member_lists(client):
    pid, hop_id = _setup(client)
    # logger (member) uploads
    r = _upload(client, pid, hop_id)
    assert r.status_code == 201
    att_id = r.get_json()["attachment"]["id"]
    # other member (owner) lists + downloads
    _login(client, "own@x.com")
    r = client.get(f"/api/plans/{pid}/hops/{hop_id}/attachments")
    assert r.status_code == 200
    assert len(r.get_json()["attachments"]) == 1
    assert client.get(f"/api/attachments/{att_id}").status_code == 200
    # hops listing reflects proof
    row = client.get(f"/api/plans/{pid}/hops").get_json()["chains"][0]["hops"][0]
    assert row["has_proof"] is True
    assert row["attachment_count"] == 1


def test_outsider_forbidden(client):
    pid, hop_id = _setup(client)
    _upload(client, pid, hop_id)
    _register(client, "out@x.com", "Out")
    assert client.get(f"/api/plans/{pid}/hops/{hop_id}/attachments").status_code == 403
    assert _upload(client, pid, hop_id).status_code == 403


def test_owner_can_delete(client):
    pid, hop_id = _setup(client)
    att_id = _upload(client, pid, hop_id).get_json()["attachment"]["id"]
    _login(client, "own@x.com")
    assert client.delete(f"/api/attachments/{att_id}").status_code == 200


def test_bad_hop_404(client):
    pid, hop_id = _setup(client)
    assert client.get(f"/api/plans/{pid}/hops/99999/attachments").status_code == 404
