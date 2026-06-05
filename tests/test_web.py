import pytest

from khata import create_app
from khata.config import Config
from khata.db import Base


@pytest.fixture
def client():
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    app = create_app(cfg)
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def test_landing_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Khata" in r.data


def test_features_page_lists_limitations(client):
    r = client.get("/features")
    assert r.status_code == 200
    assert b"Limitations" in r.data


def test_features_page_has_editorial_sections(client):
    r = client.get("/features")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["Single source of truth", "Sign in with Google",
                   "Limitations", "ledger.css"]:
        assert needle in body


def test_landing_has_login_and_google_hook(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.decode()
    assert "/api/auth/login" in body
    assert "/api/auth/config" in body      # decides whether to show Google button
    assert "/api/auth/google" in body
    assert "ledger.css" in body


def test_holdings_page_served(client):
    r = client.get("/holdings")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["Net worth", "/api/networth", "/api/fx-rates", "ledger.css"]:
        assert needle in body


def test_app_shell_served(client):
    r = client.get("/app")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/auth/me", "/api/networth", "/api/dashboard", "/api/plans",
                   "Net worth", "ledger.css", "/holdings", "/features"]:
        assert needle in body


def test_create_page_served(client):
    r = client.get("/create")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/plans", "Asset", "Loan", "Holding", "ledger.css", "/api/auth/me"]:
        assert needle in body


def test_asset_detail_served(client):
    r = client.get("/asset/1")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/plans", "/payments", "Log payment", "ledger.css"]:
        assert needle in body


def test_loan_detail_served(client):
    r = client.get("/loan/1")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/plans", "/loan/disbursements", "/loan/entries", "ledger.css"]:
        assert needle in body


def test_holding_detail_served(client):
    r = client.get("/holding/1")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/plans", "/holding/buys", "/holding/quote", "sharing.js", "ledger.css"]:
        assert needle in body


def test_sharing_js_served_and_mounted(client):
    assert client.get("/static/assets/sharing.js").status_code == 200
    for path in ["/asset/1", "/loan/1", "/holding/1"]:
        assert "sharing.js" in client.get(path).data.decode()


def test_chit_detail_served(client):
    r = client.get("/chit/1")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/plans", "/chit/entries", "/chit/dividend", "sharing.js", "ledger.css"]:
        assert needle in body
