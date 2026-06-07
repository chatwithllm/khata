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
