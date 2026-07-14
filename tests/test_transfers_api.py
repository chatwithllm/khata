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


def _register(client, email="a@b.com", name="Arjun"):
    return client.post("/api/auth/register", json={
        "email": email, "display_name": name, "password": "pw12345"})


def _login(client, email):
    client.post("/api/auth/logout")
    return client.post("/api/auth/login", json={"email": email, "password": "pw12345"})


def _mk_plan_with_member(client):
    """u1 owns plan; u2 registered + accepted as contributor. Returns pid."""
    _register(client, "u1@x.com", "U1")
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "10,00,000"}).get_json()["plan"]["id"]
    _register(client, "u2@x.com", "U2")
    _login(client, "u1@x.com")
    assert client.post(f"/api/plans/{pid}/members",
                       json={"email": "u2@x.com"}).status_code == 201
    _login(client, "u2@x.com")
    assert client.post(f"/api/invitations/{pid}/accept").status_code == 200
    return pid


def test_hop_lifecycle(client):
    pid = _mk_plan_with_member(client)

    # u2 sends 10,000 to u1 — in transit
    _login(client, "u2@x.com")
    me_u1 = None
    members = client.get(f"/api/plans/{pid}/members").get_json()["members"]
    u1_id = next(m["user_id"] for m in members if m["email"] == "u1@x.com")
    r = client.post(f"/api/plans/{pid}/hops", json={
        "amount": "10,000", "method": "transfer", "to_user_id": u1_id})
    assert r.status_code == 201
    hop_id = r.get_json()["hop"]["id"]
    assert r.get_json()["hop"]["receipt_status"] == "pending"

    # u1 sees in-transit and confirms receipt
    _login(client, "u1@x.com")
    r = client.get(f"/api/plans/{pid}/hops")
    assert r.status_code == 200
    assert r.get_json()["in_transit_minor"] == 1000000
    r = client.post(f"/api/plans/{pid}/hops/{hop_id}/receipt", json={"action": "confirm"})
    assert r.status_code == 200

    # receipt shows in confirmations feed before confirm — check the key exists
    r = client.get("/api/confirmations")
    assert "receipts" in r.get_json()

    # u1 pays seller 9,000 drawing from the transit hop — terminal
    r = client.post(f"/api/plans/{pid}/hops", json={
        "amount": "9,000", "method": "transfer", "to_name": "Seller",
        "is_terminal": True,
        "sources": [{"source_hop_id": hop_id, "amount": "9,000"}]})
    assert r.status_code == 201
    assert r.get_json()["transfers"]["in_transit_minor"] == 100000

    # paid total reflects delivered money only, attributed to u2
    st = client.get(f"/api/plans/{pid}").get_json()["state"]
    assert st["paid_to_date_minor"] == 900000

    # resolve the 1,000 remainder back to u2
    r = client.post(f"/api/plans/{pid}/hops/{hop_id}/resolve",
                    json={"action": "return"})
    assert r.status_code == 200
    assert r.get_json()["in_transit_minor"] == 0


def test_seller_role_read_only(client):
    _register(client, "own@x.com", "Owner")
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "5,00,000"}).get_json()["plan"]["id"]
    _register(client, "sell@x.com", "Sella")
    _login(client, "own@x.com")
    r = client.post(f"/api/plans/{pid}/members",
                    json={"email": "sell@x.com", "role": "seller"})
    assert r.status_code == 201
    assert r.get_json()["member"]["role"] == "seller"
    _login(client, "sell@x.com")
    assert client.post(f"/api/invitations/{pid}/accept").status_code == 200

    # seller reads fine
    assert client.get(f"/api/plans/{pid}").status_code == 200
    assert client.get(f"/api/plans/{pid}/hops").status_code == 200
    # seller cannot mutate
    assert client.post(f"/api/plans/{pid}/hops", json={
        "amount": "100", "method": "cash", "to_name": "X"}).status_code == 403
    assert client.post(f"/api/plans/{pid}/payments", json={
        "amount": "100", "method": "cash",
        "funding_source": "savings"}).status_code == 403


def test_hop_to_seller_member_is_auto_terminal(client):
    _register(client, "own2@x.com", "Owner")
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "5,00,000"}).get_json()["plan"]["id"]
    _register(client, "sell2@x.com", "Sella")
    _login(client, "own2@x.com")
    client.post(f"/api/plans/{pid}/members", json={"email": "sell2@x.com", "role": "seller"})
    _login(client, "sell2@x.com")
    client.post(f"/api/invitations/{pid}/accept")
    members = client.get(f"/api/plans/{pid}/members").get_json()["members"]
    seller_id = next(m["user_id"] for m in members if m["email"] == "sell2@x.com")

    _login(client, "own2@x.com")
    r = client.post(f"/api/plans/{pid}/hops", json={
        "amount": "1,000", "method": "transfer", "to_user_id": seller_id})
    assert r.status_code == 201
    assert r.get_json()["hop"]["is_terminal"] is True
    st = client.get(f"/api/plans/{pid}").get_json()["state"]
    assert st["paid_to_date_minor"] == 100000


def test_hops_auth_required(client):
    assert client.get("/api/plans/1/hops").status_code == 401
    assert client.post("/api/plans/1/hops", json={}).status_code == 401


def test_hop_funding_persists_via_api(client):
    _register(client, "u1@x.com", "U1")
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "10,00,000"}).get_json()["plan"]["id"]
    # create a transit hop tagged loan-funded (no linked loan)
    r = client.post(f"/api/plans/{pid}/hops", json={
        "amount": "2000", "method": "transfer", "to_name": "Middleman",
        "funding_source": "loan"})
    assert r.status_code == 201
    hop_id = r.get_json()["hop"]["id"]
    hop = client.get(f"/api/plans/{pid}/hops").get_json()["chains"][0]["hops"][0]
    assert hop["funding_source"] == "loan"
    # patch to savings
    assert client.patch(f"/api/plans/{pid}/hops/{hop_id}",
                        json={"funding_source": "savings"}).status_code == 200
    hop = client.get(f"/api/plans/{pid}/hops").get_json()["chains"][0]["hops"][0]
    assert hop["funding_source"] == "savings"
    # omitting the key on a later patch leaves it untouched
    assert client.patch(f"/api/plans/{pid}/hops/{hop_id}",
                        json={"method": "upi"}).status_code == 200
    hop = client.get(f"/api/plans/{pid}/hops").get_json()["chains"][0]["hops"][0]
    assert hop["funding_source"] == "savings"
    assert hop["method"] == "upi"
