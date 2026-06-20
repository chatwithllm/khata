"""Asset details API: PATCH /asset/meta + asset document endpoints + access branches."""
import io

import pytest

from khata import create_app
from khata.config import Config
from khata.db import Base

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f9f0000000049454e44ae426082")


@pytest.fixture
def client():
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    app = create_app(cfg)
    app.config["TESTING"] = True
    Base.metadata.create_all(app.config["ENGINE"])
    with app.test_client() as c:
        c.post("/api/auth/register", json={
            "email": "owner@example.com", "display_name": "Owner", "password": "pw12345"})
        yield c


def _make_asset(client):
    r = client.post("/api/plans", json={
        "type": "asset", "name": "Land", "currency": "INR", "total_price": "10,00,000"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["plan"]["id"]


def _login_as_other_user(client):
    """Register and authenticate a different user (replaces current session)."""
    client.post("/api/auth/logout")
    r = client.post("/api/auth/register", json={
        "email": "other@example.com", "display_name": "Other", "password": "pw12345"})
    assert r.status_code in (201, 409), r.get_json()
    if r.status_code == 409:
        assert client.post("/api/auth/login", json={
            "email": "other@example.com", "password": "pw12345"}).status_code == 200


def test_patch_meta_owner_only(client):
    pid = _make_asset(client)
    r = client.patch(f"/api/plans/{pid}/asset/meta", json={"seller_name": "Ramesh", "buyer_name": "Me",
        "extra_fields": [{"label": "Survey No", "value": "123"}],
        "links": [{"label": "Map", "url": "https://maps.example/x"}]})
    assert r.status_code == 200
    st = r.get_json()["state"]
    assert st["seller"]["name"] == "Ramesh" and st["extra_fields"][0]["label"] == "Survey No"
    # non-owner
    _login_as_other_user(client)
    assert client.patch(f"/api/plans/{pid}/asset/meta", json={"seller_name": "hack"}).status_code == 403


def test_patch_meta_bad_url_400(client):
    pid = _make_asset(client)
    assert client.patch(f"/api/plans/{pid}/asset/meta",
        json={"links": [{"label": "x", "url": "javascript:alert(1)"}]}).status_code == 400


def test_asset_doc_upload_list_download(client):
    pid = _make_asset(client)
    r = client.post(f"/api/plans/{pid}/asset/attachments",
                    data={"file": (io.BytesIO(PNG), "deed.png")}, content_type="multipart/form-data")
    assert r.status_code == 201
    aid = r.get_json()["attachment"]["id"]
    assert len(client.get(f"/api/plans/{pid}/asset/attachments").get_json()["attachments"]) == 1
    assert client.get(f"/api/attachments/{aid}").status_code == 200   # owner can download


def test_asset_doc_download_stranger_403(client):
    pid = _make_asset(client)
    r = client.post(f"/api/plans/{pid}/asset/attachments",
                    data={"file": (io.BytesIO(PNG), "deed.png")}, content_type="multipart/form-data")
    assert r.status_code == 201
    aid = r.get_json()["attachment"]["id"]
    # a second user who is NOT a plan member cannot download the asset document
    _login_as_other_user(client)
    assert client.get(f"/api/attachments/{aid}").status_code == 403


def test_asset_doc_delete_owner(client):
    pid = _make_asset(client)
    r = client.post(f"/api/plans/{pid}/asset/attachments",
                    data={"file": (io.BytesIO(PNG), "deed.png")}, content_type="multipart/form-data")
    assert r.status_code == 201
    aid = r.get_json()["attachment"]["id"]
    assert client.delete(f"/api/attachments/{aid}").status_code == 200
    assert len(client.get(f"/api/plans/{pid}/asset/attachments").get_json()["attachments"]) == 0


def test_asset_doc_delete_stranger_403(client):
    pid = _make_asset(client)
    r = client.post(f"/api/plans/{pid}/asset/attachments",
                    data={"file": (io.BytesIO(PNG), "deed.png")}, content_type="multipart/form-data")
    assert r.status_code == 201
    aid = r.get_json()["attachment"]["id"]
    # a non-member stranger cannot delete the asset document
    _login_as_other_user(client)
    assert client.delete(f"/api/attachments/{aid}").status_code == 403
    # the doc still exists — owner re-login lists 1
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "pw12345"}).status_code == 200
    assert len(client.get(f"/api/plans/{pid}/asset/attachments").get_json()["attachments"]) == 1


def test_asset_doc_upload_stranger_403(client):
    pid = _make_asset(client)
    # a non-member stranger cannot upload an asset document
    _login_as_other_user(client)
    r = client.post(f"/api/plans/{pid}/asset/attachments",
                    data={"file": (io.BytesIO(PNG), "deed.png")}, content_type="multipart/form-data")
    assert r.status_code in (403, 404)
