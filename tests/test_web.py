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
