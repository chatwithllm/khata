"""Public read-only share endpoint GET /api/public/<token>."""
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


def _register(client, email="owner@example.com"):
    return client.post("/api/auth/register", json={
        "email": email, "display_name": "Owner", "password": "pw12345"})


def _make_loan_with_dues(client):
    """Create a loan plan with a disbursement (has a schedule) and return its id."""
    r = client.post("/api/plans", json={
        "type": "loan", "name": "Test Loan", "currency": "INR",
        "direction": "given", "interest_type": "monthly", "rate": "3",
        "start_date": "2023-12-12"})
    assert r.status_code == 201, r.get_json()
    pid = r.get_json()["plan"]["id"]
    r2 = client.post(f"/api/plans/{pid}/loan/disbursements",
                     json={"amount": "2200000", "occurred_at": "2023-12-12T12:00:00"})
    assert r2.status_code in (200, 201), r2.get_json()
    return pid


def _create_share(client, plan_id, scope="full", ttl_days=30):
    """POST /api/plans/<pid>/shares and return the token."""
    r = client.post(f"/api/plans/{plan_id}/shares",
                    json={"scope": scope, "ttl_days": ttl_days})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["share"]["token"]


def _share_id_for(client, plan_id, token):
    """GET /api/plans/<pid>/shares and find the share whose token == tok; return its id."""
    r = client.get(f"/api/plans/{plan_id}/shares")
    assert r.status_code == 200, r.get_json()
    for share in r.get_json()["shares"]:
        if share["token"] == token:
            return share["id"]
    raise AssertionError(f"Token {token!r} not found in plan {plan_id} shares")


def test_public_view_valid_scoped(client):
    _register(client)
    pid = _make_loan_with_dues(client)
    tok = _create_share(client, pid, scope="full", ttl_days=30)
    r = client.get(f"/api/public/{tok}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["plan_type"] == "loan" and body["scope"] == "full"
    assert "schedule" in body["state"]
    assert "@" not in json.dumps(body) and "proof_ref" not in json.dumps(body)
    blob = json.dumps(body)
    assert "logged_by_user_id" not in blob
    assert "funding_plan_id" not in blob
    assert r.headers.get("Cache-Control") == "no-store"


def test_public_summary_drops_lines(client):
    _register(client)
    pid = _make_loan_with_dues(client)
    tok = _create_share(client, pid, scope="summary", ttl_days=7)
    body = client.get(f"/api/public/{tok}").get_json()
    assert "schedule" not in body["state"] and "ledger" not in body["state"]


def test_public_unknown_404(client):
    assert client.get("/api/public/not-a-real-token").status_code == 404


def test_public_revoked_410(client):
    _register(client)
    pid = _make_loan_with_dues(client)
    tok = _create_share(client, pid, scope="full", ttl_days=7)
    sid = _share_id_for(client, pid, tok)
    client.delete(f"/api/plans/{pid}/shares/{sid}")
    assert client.get(f"/api/public/{tok}").status_code == 410


def test_public_no_auth_needed(client):
    _register(client)
    pid = _make_loan_with_dues(client)
    tok = _create_share(client, pid, scope="summary", ttl_days=7)
    client.delete_cookie("session")            # drop auth — public must still work
    assert client.get(f"/api/public/{tok}").status_code == 200


def test_public_share_no_contact_pii(client):
    _register(client)
    pid = _make_loan_with_dues(client)
    cid = client.post("/api/contacts", json={"name": "PRIVATE_PERSON", "phone": "PRIVATE_PHONE"}).get_json()["contact"]["id"]
    client.post(f"/api/plans/{pid}/loan/contact", json={"contact_id": cid})
    tok = _create_share(client, pid, scope="full", ttl_days=30)
    import json
    blob = json.dumps(client.get(f"/api/public/{tok}").get_json())
    assert "PRIVATE_PERSON" not in blob and "PRIVATE_PHONE" not in blob
    assert "contact_id" not in blob and "\"contact\"" not in blob


def _make_asset(client):
    """Create a minimal asset plan and return its id."""
    r = client.post("/api/plans", json={
        "type": "asset", "name": "Test Asset", "currency": "INR",
        "total_price": "5000000"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["plan"]["id"]


def test_public_share_asset_no_pii(client):
    """seller, buyer, extra_fields, and links must be absent from public asset share."""
    _register(client)
    pid = _make_asset(client)

    # Attach seller name + a link + an extra field via the PATCH API
    r = client.patch(f"/api/plans/{pid}/asset/meta", json={
        "seller_name": "PRIVATE_SELLER",
        "extra_fields": [{"label": "Reg No", "value": "SECRET_REGVAL"}],
        "links": [{"label": "Listing", "url": "https://example.com/SECRET_URL"}],
    })
    assert r.status_code == 200, r.get_json()

    tok = _create_share(client, pid, scope="full", ttl_days=30)
    resp = client.get(f"/api/public/{tok}")
    assert resp.status_code == 200

    body = resp.get_json()
    blob = json.dumps(body)

    # Check that no PII strings appear anywhere in the raw JSON text
    assert "PRIVATE_SELLER" not in blob, "seller name leaked into public share"
    assert "SECRET_REGVAL" not in blob, "extra_field value leaked into public share"
    assert "SECRET_URL" not in blob, "link URL leaked into public share"

    # Check that the sensitive structural keys are absent from the parsed dict
    state = body["state"]
    assert "seller" not in state, "'seller' key present in public state"
    assert "buyer" not in state, "'buyer' key present in public state"
    assert "extra_fields" not in state, "'extra_fields' key present in public state"
    assert "links" not in state, "'links' key present in public state"
