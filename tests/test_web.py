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


def test_dashboard_fidelity_markers(client):
    body = client.get("/app").data.decode()
    for needle in ["/api/auth/me", "/api/dashboard", "/api/networth", "/api/plans",
                   "curtog", "Log payment", "Liabilities", "Net worth"]:
        assert needle in body


def test_app_css_served_with_shell_markers(client):
    r = client.get("/static/assets/app.css")
    assert r.status_code == 200
    body = r.data.decode()
    # shared app-shell markers must live in the extracted stylesheet
    for needle in [".nav-i", ".curtog", ".curtog .slide", "body::before"]:
        assert needle in body


def test_app_shell_links_app_css(client):
    r = client.get("/app")
    assert r.status_code == 200
    assert "/static/assets/app.css" in r.data.decode()


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


def test_loan_detail_has_collateral(client):
    body = client.get("/loan/1").data.decode()
    assert "/loan/collateral" in body
    assert "Collateral" in body or "collateral" in body


def test_retirement_detail_served(client):
    r = client.get("/retirement/1")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/plans", "/retirement/update", "sharing.js", "ledger.css"]:
        assert needle in body


def test_settings_page_served(client):
    r = client.get("/settings")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/auth/password", "/api/auth/profile", "/api/base-currency", "ledger.css"]:
        assert needle in body


def test_analysis_page_served(client):
    r = client.get("/analysis")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["/api/analysis/hold-vs-sell", "ledger.css"]:
        assert needle in body


def test_holding_detail_has_feed_refresh(client):
    body = client.get("/holding/1").data.decode()
    assert "/holding/refresh-quote" in body
    assert "/api/feed/config" in body
