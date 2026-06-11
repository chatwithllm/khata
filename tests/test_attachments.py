import base64
import io
import json

import pytest

from khata import create_app
from khata.config import Config
from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Attachment
from khata.services.assets import create_asset_plan, log_payment
from khata.services.attachments import add_attachment, AttachmentError, _sniff
from khata.services.backup import export_all, import_merge
from datetime import datetime, timezone

# 1x1 PNG (valid magic bytes).
PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def client():
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    app = create_app(cfg)
    app.config["TESTING"] = True
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def _register(client, email="a@b.com"):
    return client.post("/api/auth/register", json={
        "email": email, "display_name": "Arjun", "password": "pw12345"})


def _plan_with_entry(client):
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "10,00,000"}).get_json()["plan"]["id"]
    r = client.post(f"/api/plans/{pid}/payments", json={
        "amount": "1,00,000", "method": "transfer", "funding_source": "savings"})
    eid = r.get_json()["entry"]["id"]
    return pid, eid


def _upload(client, pid, eid, blob=PNG, name="receipt.png"):
    return client.post(f"/api/plans/{pid}/entries/{eid}/attachments",
                       data={"file": (io.BytesIO(blob), name)},
                       content_type="multipart/form-data")


# ---------- magic-byte sniffing ----------

def test_sniff_allows_known_types_rejects_junk():
    assert _sniff(PNG) == "image/png"
    assert _sniff(PDF) == "application/pdf"
    assert _sniff(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01") == "image/jpeg"
    assert _sniff(b"this is just plain text, not proof") is None
    assert _sniff(b"PK\x03\x04" + b"\x00" * 100) is None   # bare zip is not an Office doc


# ---------- upload / list / download / delete ----------

def test_upload_list_download_delete_roundtrip(client):
    _register(client)
    pid, eid = _plan_with_entry(client)

    r = _upload(client, pid, eid)
    assert r.status_code == 201
    att = r.get_json()["attachment"]
    assert att["mime"] == "image/png"
    assert att["filename"] == "receipt.png"
    assert att["is_image"] is True
    aid = att["id"]

    # list reflects it
    r = client.get(f"/api/plans/{pid}/entries/{eid}/attachments")
    assert r.status_code == 200
    assert [a["id"] for a in r.get_json()["attachments"]] == [aid]

    # download returns the exact bytes + correct content-type, served inline
    r = client.get(f"/api/attachments/{aid}")
    assert r.status_code == 200
    assert r.mimetype == "image/png"
    assert r.data == PNG
    assert "inline" in r.headers["Content-Disposition"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"

    # delete removes it
    assert client.delete(f"/api/attachments/{aid}").status_code == 200
    assert client.get(f"/api/attachments/{aid}").status_code == 404
    assert client.get(f"/api/plans/{pid}/entries/{eid}/attachments").get_json()["attachments"] == []


def test_pdf_is_attachment_disposition(client):
    _register(client)
    pid, eid = _plan_with_entry(client)
    aid = _upload(client, pid, eid, PDF, "deed.pdf").get_json()["attachment"]["id"]
    r = client.get(f"/api/attachments/{aid}")
    assert r.mimetype == "application/pdf"
    assert "inline" in r.headers["Content-Disposition"]   # pdf renders inline


def test_unsupported_type_rejected(client):
    _register(client)
    pid, eid = _plan_with_entry(client)
    r = _upload(client, pid, eid, b"definitely not an allowed file type at all", "x.exe")
    assert r.status_code == 400
    assert "unsupported" in r.get_json()["detail"].lower()


def test_proof_tag_lights_up_after_upload(client):
    _register(client)
    pid, eid = _plan_with_entry(client)
    # before: no proof
    st = client.get(f"/api/plans/{pid}").get_json()["state"]
    row = next(e for e in st["ledger"] if e["id"] == eid)
    assert row["has_proof"] is False and row["attachment_count"] == 0
    # after upload: proof tag on, count = 1
    _upload(client, pid, eid)
    st = client.get(f"/api/plans/{pid}").get_json()["state"]
    row = next(e for e in st["ledger"] if e["id"] == eid)
    assert row["has_proof"] is True and row["attachment_count"] == 1


# ---------- access control ----------

def test_non_member_cannot_view_or_upload(client):
    _register(client, "a@b.com")
    pid, eid = _plan_with_entry(client)
    aid = _upload(client, pid, eid).get_json()["attachment"]["id"]
    client.post("/api/auth/logout")
    _register(client, "stranger@b.com")
    assert client.get(f"/api/attachments/{aid}").status_code == 403
    assert client.get(f"/api/plans/{pid}/entries/{eid}/attachments").status_code == 403
    assert _upload(client, pid, eid).status_code in (403, 404)


def test_upload_requires_auth(client):
    assert client.post("/api/plans/1/entries/1/attachments").status_code == 401
    assert client.get("/api/attachments/1").status_code == 401
    assert client.delete("/api/attachments/1").status_code == 401


# ---------- size cap ----------

def test_oversize_rejected_413(monkeypatch):
    # Drive the service directly with a tiny cap so we don't allocate 25 MB.
    import khata.services.attachments as A
    monkeypatch.setattr(A, "MAX_SIZE", 4)
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    S = make_session_factory(e)
    with S() as s:
        u = User(email="o@b.com", display_name="O", password_hash="h"); s.add(u); s.flush()
        plan = create_asset_plan(s, owner_id=u.id, name="P", currency="INR", total_price_minor=1000)
        entry = log_payment(s, plan=plan, user_id=u.id, amount_minor=500,
                            occurred_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                            method="upi", funding_source="savings")
        s.flush()
        with pytest.raises(AttachmentError, match="too large"):
            add_attachment(s, entry=entry, uploaded_by=u.id, filename="big.png", raw=PNG)


# ---------- backup round-trip preserves blob bytes ----------

def test_backup_export_import_preserves_attachment_bytes():
    e1 = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e1)
    S1 = make_session_factory(e1)
    with S1() as s:
        u = User(email="o@b.com", display_name="O", password_hash="h"); s.add(u); s.flush()
        plan = create_asset_plan(s, owner_id=u.id, name="P", currency="INR", total_price_minor=1000)
        entry = log_payment(s, plan=plan, user_id=u.id, amount_minor=500,
                            occurred_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                            method="upi", funding_source="savings")
        s.flush()
        add_attachment(s, entry=entry, uploaded_by=u.id, filename="r.png", raw=PNG)
        s.commit()
        data = export_all(s)

    # survives JSON serialization (blob is base64 text)
    data = json.loads(json.dumps(data))
    assert len(data["tables"]["attachments"]) == 1

    e2 = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e2)
    S2 = make_session_factory(e2)
    with S2() as s:
        stats = import_merge(s, data)
        s.commit()
        assert stats["attachments"] == 1
        att = s.query(Attachment).one()
        assert att.data == PNG          # exact bytes preserved through base64 round-trip
        assert att.sha256 == __import__("hashlib").sha256(PNG).hexdigest()
