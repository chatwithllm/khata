# Google Sign-In (enable + harden behind reverse proxy) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn on Khata's already-built Google Sign-In and make the app correct + secure when served over HTTPS through the operator's existing reverse proxy.

**Architecture:** No auth-logic changes. Add one opt-in config flag (`KHATA_SECURE_COOKIES`). When set, wrap the WSGI app in Werkzeug's `ProxyFix` (so `request.scheme` reflects the proxy's `X-Forwarded-Proto`) and mark the Flask session cookie `Secure; HttpOnly; SameSite=Lax`. Add an operator runbook. Setting `KHATA_GOOGLE_CLIENT_ID` (already read by `Config`) flips the feature on.

**Tech Stack:** Python 3.12, Flask 3.1, Werkzeug `ProxyFix` (ships with Flask — no new dependency), pytest, `google-auth` (already installed).

**Reference spec:** `docs/superpowers/specs/2026-06-07-google-signin-design.md`

---

## File Structure

- `src/khata/config.py` — add `secure_cookies` boolean parsed from `KHATA_SECURE_COOKIES`. (Already reads `KHATA_GOOGLE_CLIENT_ID`.)
- `src/khata/__init__.py` (`create_app`) — when `cfg.secure_cookies` is true: apply `ProxyFix` + set secure session-cookie config.
- `tests/test_app_config.py` — **new** focused test file for the flag, the cookie/ProxyFix wiring, and the forwarded-scheme behaviour.
- `docs/google-signin-setup.md` — **new** operator runbook.
- `docs/specs/khata-AS-BUILT.md` — record the new env vars + change-log entry.

No other files change. `services/auth.py`, `api/auth.py`, `models/user.py`, `static/index.html` are already complete and must NOT be modified.

---

### Task 1: Config flag `secure_cookies`

**Files:**
- Modify: `src/khata/config.py`
- Test: `tests/test_app_config.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_config.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app_config.py -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'secure_cookies'`

- [ ] **Step 3: Write minimal implementation**

In `src/khata/config.py`, inside `Config.__init__`, add the attribute after the existing
`self.google_client_id = ...` line:

```python
        self.secure_cookies = os.environ.get("KHATA_SECURE_COOKIES", "").strip().lower() in {"1", "true", "yes"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_app_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/khata/config.py tests/test_app_config.py
git commit -m "feat(config): KHATA_SECURE_COOKIES flag (behind-TLS-proxy opt-in)"
```

---

### Task 2: ProxyFix + secure cookie wiring in `create_app`

**Files:**
- Modify: `src/khata/__init__.py`
- Test: `tests/test_app_config.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_app_config.py -v`
Expected: the three new tests FAIL — `test_flag_on_...` fails (`app.wsgi_app` is not `ProxyFix`); `test_proxyfix_honors_x_forwarded_proto` returns `b"http"`.

- [ ] **Step 3: Write minimal implementation**

In `src/khata/__init__.py`, inside `create_app`, immediately after these existing lines:

```python
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["KHATA"] = cfg
```

insert:

```python
    # When served behind a trusted HTTPS reverse proxy, trust its forwarded headers so
    # request.scheme is "https", and mark the session cookie Secure. Opt-in via
    # KHATA_SECURE_COOKIES so direct-http testing on :5057 keeps working (a Secure
    # cookie is never sent over http → would silently break login).
    if cfg.secure_cookies:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config.update(
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_app_config.py -v`
Expected: PASS (6 passed total in the file)

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (previous total + 6 new).

- [ ] **Step 6: Commit**

```bash
git add src/khata/__init__.py tests/test_app_config.py
git commit -m "feat(app): ProxyFix + secure session cookie behind TLS proxy (flag-gated)"
```

---

### Task 3: Operator runbook + AS-BUILT update

**Files:**
- Create: `docs/google-signin-setup.md`
- Modify: `docs/specs/khata-AS-BUILT.md`

- [ ] **Step 1: Write the runbook**

Create `docs/google-signin-setup.md`:

```markdown
# Enabling Google Sign-In

Google Sign-In is already built into Khata. It stays hidden until you configure an
OAuth client id, and it only works when the app is served over **HTTPS on a real
hostname** (Google rejects `http://` and raw IP origins; only `localhost` is exempt).
You already run a reverse proxy on your own domain, so this is just configuration.

## 1. OAuth client (reuse or create)

Google OAuth clients serve multiple origins, so you can reuse an existing one.

**Reuse an existing Web client:**
- Google Cloud Console → APIs & Services → Credentials → your existing OAuth 2.0 **Web**
  client → add `https://<your-khata-domain>` under **Authorized JavaScript origins** → Save.
- Note: the sign-in popup shows that client's consent-screen app name.

**Or create a fresh client (clean "Khata" branding):**
- Credentials → Create credentials → OAuth client ID → Application type **Web application**.
- **Authorized JavaScript origins:** `https://<your-khata-domain>`. (No redirect URI —
  Google Identity Services uses the origin only.)
- Copy the **Client ID**.

## 2. Reverse proxy

Terminate TLS for `https://<your-khata-domain>` and proxy to the app, passing the
forwarded scheme. Example (Caddy):

    <your-khata-domain> {
        reverse_proxy 127.0.0.1:5057 {
            header_up X-Forwarded-Proto https
        }
    }

(Caddy/most proxies pass `Host` and `X-Forwarded-Proto` by default; set it explicitly
if yours does not.)

## 3. App environment

In `.env.app`:

    KHATA_GOOGLE_CLIENT_ID=<your-client-id>
    KHATA_SECURE_COOKIES=1

Then restart: `./run-app.sh`.

- `KHATA_GOOGLE_CLIENT_ID` reveals the "Continue with Google" button and enables
  `POST /api/auth/google`.
- `KHATA_SECURE_COOKIES=1` makes the app trust the proxy's `X-Forwarded-Proto` and marks
  the session cookie `Secure; HttpOnly; SameSite=Lax`. Set it **only** on the
  proxied instance — direct `http://<lan-ip>:5057` access would stop logging in with a
  Secure cookie.

## 4. Verify

- Open `https://<your-khata-domain>` → the "Continue with Google" button appears.
- Sign in with Google → a new account is created, or it links to an existing account
  with the same verified email. The session persists across page loads.
- DevTools → Application → Cookies: the `session` cookie shows `Secure` + `HttpOnly`.
```

Replace `<your-khata-domain>` / `<your-client-id>` with your real values when you follow it.

- [ ] **Step 2: Update AS-BUILT**

In `docs/specs/khata-AS-BUILT.md`:

1. In §3 (config-from-env list), append `KHATA_SECURE_COOKIES` next to the existing
   `KHATA_GOOGLE_CLIENT_ID` entry, e.g. change the line listing env config to also
   mention: `KHATA_SECURE_COOKIES (behind an HTTPS reverse proxy → ProxyFix + Secure cookie)`.
2. Add a change-log entry at the top of the `## Change log` list:

```markdown
- 2026-06-07 — Enabled Google Sign-In (already built). Set KHATA_GOOGLE_CLIENT_ID to
  reveal the button + /api/auth/google. New KHATA_SECURE_COOKIES=1 flag: when behind an
  HTTPS reverse proxy, applies ProxyFix (trust X-Forwarded-Proto/Host) + marks the
  session cookie Secure/HttpOnly/SameSite=Lax. Runbook: docs/google-signin-setup.md.
```

- [ ] **Step 3: Verify docs render (no broken markdown) + suite still green**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (unchanged from Task 2 — docs don't affect tests).

- [ ] **Step 4: Commit**

```bash
git add docs/google-signin-setup.md docs/specs/khata-AS-BUILT.md
git commit -m "docs: Google sign-in operator runbook + AS-BUILT"
```

---

## Self-Review

**1. Spec coverage:**
- Spec §"Configure the client id" → no code change needed (already read); covered by Task 3 runbook step 3. ✓
- Spec §"Proxy-awareness + cookie hardening" → Task 1 (flag) + Task 2 (ProxyFix + cookie). ✓
- Spec §"Operator runbook" → Task 3. ✓
- Spec §"Testing" (config flag, proxy scheme, existing green) → Task 1 + Task 2 tests + full-suite runs. ✓
- Spec §"Out of scope" (no auth-logic/deps/exposure changes) → no tasks touch those files. ✓

**2. Placeholder scan:** `<your-khata-domain>` / `<your-client-id>` are operator fill-ins inside the runbook content (intended), not plan gaps. No TBD/TODO/"handle edge cases". ✓

**3. Type consistency:** `cfg.secure_cookies` (bool) defined in Task 1, consumed in Task 2 and the Task 2 tests' `_cfg()` helper. `KHATA_SECURE_COOKIES` env name consistent across config, runbook, AS-BUILT. `ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)` and the `isinstance(app.wsgi_app, ProxyFix)` assertion match. ✓
