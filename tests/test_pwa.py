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


def test_pwa_manifest_served(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.mimetype == "application/manifest+json"
    data = json.loads(r.data)
    assert data["name"] == "Khata"
    assert data["start_url"] == "/app"
    assert data["display"] == "standalone"


def test_pwa_service_worker_served(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.mimetype
    assert r.headers.get("Cache-Control") == "no-store"


def test_pwa_icons_reachable(client):
    for url in [
        "/static/assets/icons/icon-192.png",
        "/static/assets/icons/icon-512.png",
        "/static/assets/icons/apple-touch-icon.png",
    ]:
        r = client.get(url)
        assert r.status_code == 200, f"icon not found: {url}"
        assert r.mimetype == "image/png"
