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


@pytest.fixture(autouse=True)
def _no_live_fx(monkeypatch):
    """Tests never hit frankfurter. Patch the fx module's reference (not fx_live
    itself) so the snapshot hot path gets None while test_fx_live.py still
    exercises the real client. Tests that want live behavior monkeypatch
    khata.services.fx.fx_live themselves (test-body patches win)."""
    import khata.services.fx as _fx

    class _Stub:
        @staticmethod
        def fetch_rate(*a, **k):
            return None

        @staticmethod
        def fetch_latest(*a, **k):
            return None

        @staticmethod
        def fetch_range(*a, **k):
            return {}

    monkeypatch.setattr(_fx, "fx_live", _Stub())
