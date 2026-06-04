import pytest

from khata import create_app
from khata.config import Config


@pytest.fixture
def app():
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    cfg.testing = True
    application = create_app(cfg)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()
