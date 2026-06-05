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


def _register(client, email="a@b.com"):
    return client.post("/api/auth/register", json={
        "email": email, "display_name": "Arjun", "password": "pw12345"})


def test_create_set_pay_and_state(client):
    _register(client)
    r = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "10,00,000",
        "installments": [{"amount": "2,50,000"}, {"amount": "2,50,000"},
                         {"amount": "2,50,000"}, {"amount": "2,50,000"}]})
    assert r.status_code == 201
    pid = r.get_json()["plan"]["id"]

    r = client.post(f"/api/plans/{pid}/payments", json={
        "amount": "3,00,000", "method": "transfer", "funding_source": "savings"})
    assert r.status_code == 201
    st = r.get_json()["state"]
    assert st["paid_to_date_minor"] == 30000000
    assert st["remaining_minor"] == 70000000
    assert st["installments"][0]["status"] == "paid"
    assert st["installments"][1]["status"] == "partial"

    r = client.get(f"/api/plans/{pid}")
    assert r.status_code == 200
    assert r.get_json()["state"]["funding_breakdown"][0]["source"] == "savings"

    r = client.get("/api/plans")
    assert len(r.get_json()["plans"]) == 1


def test_auth_required(client):
    # every endpoint rejects an unauthenticated caller
    assert client.get("/api/plans").status_code == 401
    assert client.post("/api/plans", json={}).status_code == 401
    assert client.get("/api/plans/1").status_code == 401
    assert client.post("/api/plans/1/installments", json={}).status_code == 401
    assert client.post("/api/plans/1/payments", json={}).status_code == 401
    assert client.post("/api/plans/1/loan/disbursements", json={}).status_code == 401
    assert client.post("/api/plans/1/loan/entries", json={}).status_code == 401


def test_ownership_enforced(client):
    _register(client, "a@b.com")
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1000"}).get_json()["plan"]["id"]
    client.post("/api/auth/logout")
    _register(client, "b@b.com")
    # user B cannot read or mutate user A's plan
    assert client.get(f"/api/plans/{pid}").status_code == 403
    assert client.post(f"/api/plans/{pid}/installments",
                       json={"installments": []}).status_code == 403
    assert client.post(f"/api/plans/{pid}/payments",
                       json={"amount": "100", "method": "cash",
                             "funding_source": "savings"}).status_code == 403


def test_validation_error_returns_400(client):
    _register(client)
    r = client.post("/api/plans", json={"name": "P", "currency": "INR", "total_price": "0"})
    assert r.status_code == 400


def test_float_amount_returns_400_not_500(client):
    _register(client)
    r = client.post("/api/plans", json={"name": "P", "currency": "INR", "total_price": 1000.50})
    assert r.status_code == 400


def test_malformed_amount_is_400_not_500(client):
    _register(client, "a@b.com")
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1000"}).get_json()["plan"]["id"]
    r = client.post(f"/api/plans/{pid}/payments",
                    json={"amount": "abc", "method": "upi", "funding_source": "savings"})
    assert r.status_code == 400


def test_create_loan_disbursement_payment_and_state(client):
    _register(client)
    r = client.post("/api/plans", json={
        "type": "loan", "name": "Gold loan", "currency": "INR", "direction": "taken",
        "interest_type": "yearly", "rate": "8.5", "start_date": "2026-01-14"})
    assert r.status_code == 201
    body = r.get_json()
    pid = body["plan"]["id"]
    assert body["plan"]["direction"] == "taken" and body["plan"]["rate_bps"] == 850

    r = client.post(f"/api/plans/{pid}/loan/disbursements",
                    json={"amount": "6,00,000", "occurred_at": "2026-01-14T11:40:00"})
    assert r.status_code == 201
    assert r.get_json()["entry"]["kind"] == "disbursement"
    assert r.get_json()["entry"]["direction"] == "in"
    assert r.get_json()["state"]["principal_outstanding_minor"] == 60000000

    r = client.post(f"/api/plans/{pid}/loan/entries",
                    json={"kind": "interest_payment", "amount": "2,805"})
    assert r.status_code == 201

    r = client.get(f"/api/plans/{pid}")
    assert r.status_code == 200 and r.get_json()["state"]["direction"] == "taken"


def test_asset_create_still_works(client):
    _register(client)
    r = client.post("/api/plans", json={"name": "Plot", "currency": "INR",
                                        "total_price": "10,00,000"})
    assert r.status_code == 201
    assert r.get_json()["plan"]["total_price_minor"] == 100000000
    assert r.get_json()["state"]["remaining_minor"] == 100000000


def test_loan_endpoints_auth_and_ownership(client):
    _register(client, "a@b.com")
    pid = client.post("/api/plans", json={
        "type": "loan", "name": "L", "currency": "INR", "direction": "given",
        "interest_type": "none", "start_date": "2026-01-01"}).get_json()["plan"]["id"]
    client.post("/api/auth/logout")
    assert client.post(f"/api/plans/{pid}/loan/disbursements",
                       json={"amount": "100"}).status_code == 401
    _register(client, "b@b.com")
    assert client.post(f"/api/plans/{pid}/loan/disbursements",
                       json={"amount": "100"}).status_code == 403
    assert client.post(f"/api/plans/{pid}/loan/entries",
                       json={"kind": "interest_payment", "amount": "100"}).status_code == 403


def test_member_can_access_and_contribute(client):
    client.post("/api/auth/register", json={
        "email": "b@b.com", "display_name": "Priya", "password": "pw12345"})
    client.post("/api/auth/logout")
    _register(client, "a@b.com")  # owner
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "10,00,000"}).get_json()["plan"]["id"]
    assert client.post(f"/api/plans/{pid}/members", json={"email": "b@b.com"}).status_code == 201
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "b@b.com", "password": "pw12345"})

    assert client.get(f"/api/plans/{pid}").status_code == 200            # member reads
    assert client.post(f"/api/plans/{pid}/payments", json={
        "amount": "2,00,000", "method": "upi", "funding_source": "savings"}).status_code == 201
    assert client.post(f"/api/plans/{pid}/installments",
                       json={"installments": []}).status_code == 403     # owner-only
    assert client.post(f"/api/plans/{pid}/members",
                       json={"email": "a@b.com"}).status_code == 403      # owner-only
    st = client.get(f"/api/plans/{pid}").get_json()["state"]
    assert any(c["display_name"] == "Priya" for c in st["contributors"])


def test_non_member_forbidden(client):
    _register(client, "a@b.com")
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1000"}).get_json()["plan"]["id"]
    client.post("/api/auth/logout")
    _register(client, "c@b.com")
    assert client.get(f"/api/plans/{pid}").status_code == 403


def test_dashboard_rollup(client):
    _register(client, "a@b.com")
    client.post("/api/plans", json={
        "type": "loan", "name": "GL", "currency": "INR", "direction": "taken",
        "interest_type": "none", "start_date": "2026-01-01"})
    client.post("/api/plans/1/loan/disbursements",
                json={"amount": "1,00,000", "occurred_at": "2026-01-01T00:00:00"})
    pid2 = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "5,00,000"}).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid2}/payments",
                json={"amount": "1,00,000", "method": "upi", "funding_source": "savings"})

    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["i_owe_minor"] == 10000000
    assert d["paid_to_date_minor"] == 10000000
    assert d["owed_to_me_minor"] == 0
    assert d["net_position_minor"] == -10000000
    assert len(d["plans"]) == 2


def test_dashboard_requires_auth(client):
    assert client.get("/api/dashboard").status_code == 401


def test_edit_ledger_entry_and_occurred_at(client):
    _register(client)
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "10,00,000",
        "installments": [{"amount": "5,00,000"}, {"amount": "5,00,000"}]}).get_json()["plan"]["id"]
    # log a payment with an explicit occurred_at date
    r = client.post(f"/api/plans/{pid}/payments", json={
        "amount": "3,00,000", "method": "transfer", "funding_source": "savings",
        "occurred_at": "2025-03-15T12:00:00"})
    assert r.status_code == 201
    e = client.get(f"/api/plans/{pid}").get_json()["state"]["ledger"][0]
    assert e["occurred_at"].startswith("2025-03-15")
    assert "id" in e and "created_at" in e          # exposed for edit + "logged" display
    eid = e["id"]
    # edit it: change amount + note + date → derived state recomputes
    r = client.patch(f"/api/plans/{pid}/entries/{eid}", json={
        "amount": "4,00,000", "note": "corrected", "occurred_at": "2025-04-01T12:00:00"})
    assert r.status_code == 200
    st = r.get_json()["state"]
    assert st["paid_to_date_minor"] == 40000000
    e = [x for x in st["ledger"] if x["id"] == eid][0]
    assert e["note"] == "corrected" and e["occurred_at"].startswith("2025-04-01")
    # bad amount → 400 (no 500); missing entry → 400
    assert client.patch(f"/api/plans/{pid}/entries/{eid}", json={"amount": "abc"}).status_code == 400
    assert client.patch(f"/api/plans/{pid}/entries/999999", json={"note": "x"}).status_code == 400
    # unauthenticated → 401
    client.post("/api/auth/logout")
    assert client.patch(f"/api/plans/{pid}/entries/{eid}", json={"note": "x"}).status_code == 401


def test_delete_ledger_entry(client):
    _register(client)
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "10,00,000"}).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/payments", json={
        "amount": "3,00,000", "method": "cash", "funding_source": "savings"})
    eid = client.get(f"/api/plans/{pid}").get_json()["state"]["ledger"][0]["id"]
    # delete → derived paid recomputes to 0, ledger empty
    r = client.delete(f"/api/plans/{pid}/entries/{eid}")
    assert r.status_code == 200
    st = r.get_json()["state"]
    assert st["paid_to_date_minor"] == 0 and st["ledger"] == []
    # already gone → 400; unauth → 401
    assert client.delete(f"/api/plans/{pid}/entries/{eid}").status_code == 400
    client.post("/api/auth/logout")
    assert client.delete(f"/api/plans/{pid}/entries/1").status_code == 401


def test_edit_loan_terms_and_delete_plan(client):
    _register(client)
    pid = client.post("/api/plans", json={
        "type": "loan", "name": "Old name", "currency": "INR", "direction": "taken",
        "counterparty": "HDFC", "interest_type": "yearly", "rate": "8.5",
        "start_date": "2025-01-15"}).get_json()["plan"]["id"]
    # edit terms
    r = client.patch(f"/api/plans/{pid}", json={"name": "New name", "counterparty": "ICICI", "rate": "10"})
    assert r.status_code == 200
    d = client.get(f"/api/plans/{pid}").get_json()["plan"]
    assert d["name"] == "New name" and d["counterparty"] == "ICICI" and d["rate_bps"] == 1000
    # bad interest_type → 400
    assert client.patch(f"/api/plans/{pid}", json={"interest_type": "weird"}).status_code == 400
    # delete the whole plan
    assert client.delete(f"/api/plans/{pid}").status_code == 200
    assert client.get(f"/api/plans/{pid}").status_code == 404
    # unauth → 401
    client.post("/api/auth/logout")
    assert client.delete(f"/api/plans/{pid}").status_code == 401
