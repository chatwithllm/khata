from khata.config import Config


def test_secure_cookies_defaults_false(monkeypatch):
    monkeypatch.delenv("KHATA_SECURE_COOKIES", raising=False)
    assert Config().secure_cookies is False


def test_secure_cookies_parses_truthy_env(monkeypatch):
    for val in ("1", "true", "TRUE", "yes"):
        monkeypatch.setenv("KHATA_SECURE_COOKIES", val)
        assert Config().secure_cookies is True, val


def test_secure_cookies_parses_falsy_env(monkeypatch):
    for val in ("0", "false", "no", ""):
        monkeypatch.setenv("KHATA_SECURE_COOKIES", val)
        assert Config().secure_cookies is False, val


from werkzeug.middleware.proxy_fix import ProxyFix

from khata import create_app


def _cfg(secure):
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    cfg.secure_cookies = secure
    return cfg


def test_flag_on_applies_proxyfix_and_secure_cookie():
    app = create_app(_cfg(True))
    assert isinstance(app.wsgi_app, ProxyFix)
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_flag_off_leaves_app_plain():
    app = create_app(_cfg(False))
    assert not isinstance(app.wsgi_app, ProxyFix)
    assert not app.config.get("SESSION_COOKIE_SECURE")


def test_proxyfix_honors_x_forwarded_proto():
    app = create_app(_cfg(True))

    @app.route("/_scheme_probe")
    def _scheme_probe():
        from flask import request
        return request.scheme

    client = app.test_client()
    r = client.get("/_scheme_probe", headers={"X-Forwarded-Proto": "https"})
    assert r.data == b"https"
