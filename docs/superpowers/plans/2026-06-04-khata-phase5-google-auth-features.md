# Khata Phase 1 · Plan 5 — Google Sign-In + Features Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add identity-only Google sign-in (GIS ID-token, verified server-side, auto-linked by verified email) beside the existing email/password auth, and build the polished editorial-ledger Features & Limitations page.

**Architecture:** A nullable `users.google_sub` column stores the stable Google identity. A pure, session-injected `login_with_google(claims)` does find-by-sub / link-by-verified-email / create. An **injectable** verifier (app config `GOOGLE_VERIFIER`, default `verify_google_credential` using `google-auth`) keeps all auth logic testable without network. Two new auth endpoints (`GET /api/auth/config`, `POST /api/auth/google`) extend the existing `auth` blueprint. The frontend gets a shared `ledger.css` (extracted from the locked mockup kit), a real login section with a Google button shown only when configured, and a full static Features page.

**Tech Stack:** Python 3.12, Flask 3.1, SQLAlchemy 2.0, Alembic, pytest, `google-auth`, Google Identity Services (frontend).

---

## File Structure

```
src/khata/
├── models/user.py          # MODIFY: add google_sub column
├── config.py               # MODIFY: google_client_id
├── __init__.py             # MODIFY: register default GOOGLE_VERIFIER
├── services/auth.py        # MODIFY: GoogleAuthError, EmailUnverifiedError,
│                           #         verify_google_credential, login_with_google
├── api/auth.py             # MODIFY: GET /config, POST /google, current_app import
└── static/
    ├── assets/ledger.css   # NEW: shared editorial-ledger stylesheet
    ├── index.html          # REPLACE placeholder: editorial landing + login section
    └── features.html       # REPLACE placeholder: editorial Features & Limitations page
alembic/versions/<rev>_user_google_sub.py   # NEW
requirements.txt            # MODIFY: google-auth, requests
tests/
├── test_user_model.py      # MODIFY: google_sub persists + unique
├── test_auth_service.py    # MODIFY: login_with_google scenarios
├── test_auth_api.py        # MODIFY: /config + /google endpoints (stubbed verifier)
└── test_web.py             # MODIFY: features sections + login form assertions
build_status.json           # MODIFY
docs/AGENT_LEARNINGS.md     # MODIFY
```

---

### Task 1: `User.google_sub` model field

**Files:** Modify `src/khata/models/user.py`; Test `tests/test_user_model.py`

- [ ] **Step 1: Append failing test to `tests/test_user_model.py`**

First READ `tests/test_user_model.py` to reuse its existing session fixture/helper. If it has a `_session()` helper or `session` fixture, mirror it. Append this test (adapt the session-construction line to match the file's existing pattern):

```python
def test_google_sub_persists_and_is_unique():
    from sqlalchemy.exc import IntegrityError
    from khata.db import Base, make_engine, make_session_factory
    from khata.models import User

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = make_session_factory(engine)()

    u = User(email="g@b.com", display_name="G", password_hash=None, google_sub="sub-123")
    s.add(u)
    s.commit()
    assert s.get(User, u.id).google_sub == "sub-123"

    s.add(User(email="h@b.com", display_name="H", password_hash=None, google_sub="sub-123"))
    with pytest.raises(IntegrityError):
        s.commit()
```

Ensure `import pytest` is present at the top of the file (it usually is; add it if missing).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_user_model.py::test_google_sub_persists_and_is_unique -q`
Expected: FAIL (`TypeError: 'google_sub' is an invalid keyword argument for User`).

- [ ] **Step 3: Add the column to `src/khata/models/user.py`**

In the `User` class, immediately after the `password_hash` line, add:
```python
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
```
(`String` and `Mapped`/`mapped_column` are already imported in this file.)

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_user_model.py -q` (expect all pass), then `.venv/bin/python -m pytest -q` (expect 65 passed — was 64, +1).

- [ ] **Step 5: Commit**

```bash
git add src/khata/models/user.py tests/test_user_model.py
git commit -m "feat(models): User.google_sub (stable Google identity), unique+nullable

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Alembic migration for `users.google_sub`

**Files:** Create `alembic/versions/<rev>_user_google_sub.py`

- [ ] **Step 1: Reset scratch DB to the Plan-4 head**

```bash
cd /Users/assistant/dev/active/khata
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
(DB now at `fcb8126c1b40`.)

- [ ] **Step 2: Autogenerate**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic revision --autogenerate -m "user google_sub"
```
Expect output mentioning `add_column` of `google_sub` on `users` (and its unique index).

- [ ] **Step 3: Sanity-check the file**

Open `alembic/versions/*_user_google_sub.py`: confirm `down_revision = 'fcb8126c1b40'`; `upgrade()` adds the `google_sub` column to `users` and creates a unique index (e.g. `op.create_index(..., unique=True)`); `downgrade()` drops the index + column. Because `env.py` uses `render_as_batch=True`, the ops may be wrapped in `with op.batch_alter_table('users') as batch_op:` — that is fine. If ANY table other than `users` appears, STOP and report BLOCKED (trim to only the `users.google_sub` add/drop and note it).

- [ ] **Step 4: Apply + verify + round-trip**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
.venv/bin/python -c "import sqlite3;cols=[r[1] for r in sqlite3.connect('khata.db').execute('PRAGMA table_info(users)')];print('google_sub' in cols)"
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic downgrade -1 && KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
Expected: `True`; downgrade + re-upgrade both succeed.

- [ ] **Step 5: Full suite + commit**

```bash
.venv/bin/python -m pytest -q   # 65 passed
rm -f khata.db khata.db-wal khata.db-shm
git add alembic/versions/
git commit -m "feat(db): migration for users.google_sub

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
(Do NOT commit the scratch `khata.db`.)

---

### Task 3: Config + dependency wiring (`google_client_id`, `GOOGLE_VERIFIER`, deps)

**Files:** Modify `src/khata/config.py`, `src/khata/__init__.py`, `requirements.txt`

This task wires config and installs the dependency. The default `GOOGLE_VERIFIER` references `verify_google_credential`, which is created in Task 4; to keep this task self-contained and green, we add a **lazy import** so the factory does not import `google-auth` at module load. The verifier function itself lands in Task 4 — but it imports `google-auth` lazily inside its body, so importing `services.auth` here is safe even before that. Implement Tasks 3 and 4 in order.

- [ ] **Step 1: Add the dependency**

Append to `requirements.txt`:
```
google-auth==2.38.0
requests==2.32.3
```
Then install:
```bash
.venv/bin/python -m pip install google-auth==2.38.0 requests==2.32.3
```
Expected: installs clean (pulls `cachetools`, `pyasn1-modules`, `rsa`, `urllib3`, `certifi`, etc.).

- [ ] **Step 2: Add `google_client_id` to `src/khata/config.py`**

In `Config.__init__`, after the `self.env = ...` line, add:
```python
        self.google_client_id = os.environ.get("KHATA_GOOGLE_CLIENT_ID")
```

- [ ] **Step 3: Register the default verifier in `src/khata/__init__.py`**

In `create_app`, after `app.config["KHATA"] = cfg`, add:
```python
    from .services.auth import verify_google_credential
    app.config["GOOGLE_VERIFIER"] = verify_google_credential
```
(This import is safe even before Task 4 adds the function only if Task 4 is done first. Implement Task 4 immediately after this task; do not run the app between Task 3 and Task 4. The full suite is run at the end of Task 4.)

- [ ] **Step 4: Verify config attribute (no app import yet)**

Run:
```bash
.venv/bin/python -c "from khata.config import Config; print(Config().google_client_id)"
```
Expected: prints `None` (no `KHATA_GOOGLE_CLIENT_ID` set). This does not import the factory, so it passes before Task 4.

- [ ] **Step 5: Commit (with Task 4)**

Do not commit yet — Task 3 and Task 4 ship together (the factory import in Step 3 needs Task 4's function). Proceed directly to Task 4; its final step commits both.

---

### Task 4: Auth service — verifier + `login_with_google`

**Files:** Modify `src/khata/services/auth.py`; Test `tests/test_auth_service.py`

- [ ] **Step 1: Append failing tests to `tests/test_auth_service.py`**

Append (the file already has a `session` fixture and imports `register_user`):
```python
def test_google_create_new_user(session):
    from khata.services.auth import login_with_google
    claims = {"sub": "g-1", "email": "New@B.com", "email_verified": True, "name": "Neha"}
    user, created = login_with_google(session, claims=claims)
    session.commit()
    assert created is True
    assert user.email == "new@b.com"
    assert user.display_name == "Neha"
    assert user.password_hash is None
    assert user.google_sub == "g-1"


def test_google_links_existing_verified_email(session):
    from khata.services.auth import login_with_google
    existing = register_user(session, email="a@b.com", display_name="Arjun", password="pw12345")
    session.commit()
    claims = {"sub": "g-2", "email": "a@b.com", "email_verified": True, "name": "Arjun G"}
    user, created = login_with_google(session, claims=claims)
    session.commit()
    assert created is False
    assert user.id == existing.id
    assert user.google_sub == "g-2"
    assert user.display_name == "Arjun"  # not overwritten on link


def test_google_matches_by_sub_on_repeat(session):
    from khata.services.auth import login_with_google
    claims = {"sub": "g-3", "email": "c@b.com", "email_verified": True, "name": "Cee"}
    first, c1 = login_with_google(session, claims=claims)
    session.commit()
    # second login: same sub, even if email/name differ — same user, no new row
    again = {"sub": "g-3", "email": "changed@b.com", "email_verified": True, "name": "Cee2"}
    second, c2 = login_with_google(session, claims=again)
    session.commit()
    assert c1 is True and c2 is False
    assert second.id == first.id
    assert second.email == "c@b.com"  # original email unchanged


def test_google_unverified_email_refused(session):
    from khata.services.auth import login_with_google, EmailUnverifiedError
    claims = {"sub": "g-4", "email": "d@b.com", "email_verified": False, "name": "Dee"}
    with pytest.raises(EmailUnverifiedError):
        login_with_google(session, claims=claims)


def test_google_name_fallback_to_email(session):
    from khata.services.auth import login_with_google
    claims = {"sub": "g-5", "email": "e@b.com", "email_verified": True, "name": ""}
    user, created = login_with_google(session, claims=claims)
    session.commit()
    assert created is True
    assert user.display_name == "e@b.com"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_auth_service.py -q`
Expected: FAIL (`ImportError: cannot import name 'login_with_google'`).

- [ ] **Step 3: Add errors + functions to `src/khata/services/auth.py`**

After the existing error classes (`InvalidCredentialsError`), add:
```python
class GoogleAuthError(AuthError):
    pass


class EmailUnverifiedError(GoogleAuthError):
    pass
```
At the end of the file, add the verifier (lazy `google-auth` import) and the login function:
```python
def verify_google_credential(credential: str, client_id: str) -> dict:
    """Verify a Google Identity Services ID token; return the relevant claims.

    Raises GoogleAuthError on any verification failure. google-auth is imported
    lazily so the rest of the auth module (and tests that stub the verifier) do
    not require the package.
    """
    from google.oauth2 import id_token
    from google.auth.transport import requests as ga_requests

    try:
        info = id_token.verify_oauth2_token(credential, ga_requests.Request(), client_id)
    except ValueError as e:
        raise GoogleAuthError(str(e)) from e
    return {
        "sub": info["sub"],
        "email": info.get("email"),
        "email_verified": bool(info.get("email_verified", False)),
        "name": info.get("name"),
    }


def login_with_google(session: Session, *, claims: dict) -> tuple[User, bool]:
    """Find-by-sub / link-by-verified-email / create. Returns (user, created)."""
    sub = claims["sub"]
    user = session.scalar(select(User).where(User.google_sub == sub))
    if user is not None:
        return user, False

    if not claims.get("email_verified"):
        raise EmailUnverifiedError("email_unverified")
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise EmailUnverifiedError("email_unverified")

    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        existing.google_sub = sub
        session.flush()
        return existing, False

    name = (claims.get("name") or "").strip() or email
    user = User(email=email, display_name=name, password_hash=None, google_sub=sub)
    session.add(user)
    session.flush()
    return user, True
```
(`select`, `Session`, `User` are already imported at the top of this file.)

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_auth_service.py -q` (expect all pass), then verify the factory import from Task 3 now resolves:
```bash
.venv/bin/python -c "from khata import create_app; from khata.config import Config; create_app(Config()); print('factory ok')"
```
Expected: `factory ok`. Then `.venv/bin/python -m pytest -q` (expect 70 passed — 65 + 5 new service tests).

- [ ] **Step 5: Commit (Tasks 3 + 4 together)**

```bash
git add requirements.txt src/khata/config.py src/khata/__init__.py src/khata/services/auth.py tests/test_auth_service.py
git commit -m "feat(auth): Google ID-token verifier + login_with_google (link/create); config + deps

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: API — `GET /api/auth/config` + `POST /api/auth/google`

**Files:** Modify `src/khata/api/auth.py`; Test `tests/test_auth_api.py`

- [ ] **Step 1: Append failing tests to `tests/test_auth_api.py`**

Append (the file imports `create_app`, `Config`, `Base`):
```python
def _google_client(verifier, client_id="test-cid"):
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    cfg.google_client_id = client_id
    app = create_app(cfg)
    app.config["TESTING"] = True
    app.config["GOOGLE_VERIFIER"] = verifier
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def test_auth_config_reports_client_id():
    c = _google_client(lambda cred, cid: {}, client_id="abc.apps.googleusercontent.com")
    r = c.get("/api/auth/config")
    assert r.status_code == 200
    assert r.get_json()["google_client_id"] == "abc.apps.googleusercontent.com"


def test_auth_config_null_when_unset(client):
    r = client.get("/api/auth/config")
    assert r.status_code == 200
    assert r.get_json()["google_client_id"] is None


def test_google_login_creates_and_sets_session():
    claims = {"sub": "z-1", "email": "z@b.com", "email_verified": True, "name": "Zoya"}
    c = _google_client(lambda cred, cid: claims)
    r = c.post("/api/auth/google", json={"credential": "fake"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["created"] is True
    assert body["user"]["email"] == "z@b.com"
    # session established → /me works
    assert c.get("/api/auth/me").status_code == 200


def test_google_login_not_configured_503(client):
    # default Config() has no google_client_id
    r = client.post("/api/auth/google", json={"credential": "fake"})
    assert r.status_code == 503
    assert r.get_json()["error"] == "google_not_configured"


def test_google_login_invalid_token_401():
    from khata.services.auth import GoogleAuthError

    def bad(cred, cid):
        raise GoogleAuthError("bad signature")

    c = _google_client(bad)
    r = c.post("/api/auth/google", json={"credential": "fake"})
    assert r.status_code == 401
    assert r.get_json()["error"] == "invalid_token"


def test_google_login_unverified_email_403():
    claims = {"sub": "z-2", "email": "z2@b.com", "email_verified": False, "name": "Z2"}
    c = _google_client(lambda cred, cid: claims)
    r = c.post("/api/auth/google", json={"credential": "fake"})
    assert r.status_code == 403
    assert r.get_json()["error"] == "email_unverified"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_auth_api.py -q`
Expected: the 6 new tests FAIL (404 on `/config` and `/google`).

- [ ] **Step 3: Update imports + add endpoints in `src/khata/api/auth.py`**

Change the Flask import line to add `current_app`:
```python
from flask import Blueprint, current_app, g, jsonify, request, session
```
Extend the service import to include the new symbols:
```python
from ..services.auth import (
    register_user,
    authenticate_user,
    login_with_google,
    EmailTakenError,
    InvalidCredentialsError,
    GoogleAuthError,
    EmailUnverifiedError,
    AuthError,
)
```
At the end of the file, add the two endpoints:
```python
@bp.get("/config")
def auth_config():
    cfg = current_app.config["KHATA"]
    return jsonify(google_client_id=cfg.google_client_id), 200


@bp.post("/google")
def google_login():
    cfg = current_app.config["KHATA"]
    if not cfg.google_client_id:
        return jsonify(error="google_not_configured"), 503
    data = request.get_json(silent=True) or {}
    verifier = current_app.config["GOOGLE_VERIFIER"]
    try:
        claims = verifier(data.get("credential", ""), cfg.google_client_id)
        user, created = login_with_google(g.db, claims=claims)
        g.db.commit()
    except EmailUnverifiedError:
        g.db.rollback()
        return jsonify(error="email_unverified"), 403
    except (GoogleAuthError, ValueError):
        g.db.rollback()
        return jsonify(error="invalid_token"), 401
    session["user_id"] = user.id
    return jsonify(user=_user_json(user), created=created), 200
```
(The `auth` blueprint's `url_prefix="/api/auth"` makes these `/api/auth/config` and `/api/auth/google`.)

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_auth_api.py -q` (expect all pass), then `.venv/bin/python -m pytest -q` (expect 76 passed — 70 + 6 new).

- [ ] **Step 5: Commit**

```bash
git add src/khata/api/auth.py tests/test_auth_api.py
git commit -m "feat(api): GET /api/auth/config + POST /api/auth/google (verify, link/create, session)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Shared `ledger.css` + editorial Features page

**Files:** Create `src/khata/static/assets/ledger.css`; Replace `src/khata/static/features.html`; Test `tests/test_web.py`

**Reference:** the locked design kit is `docs/mockups/_SHARED_KIT.md` (§1 fonts, §2 tokens + base + grain) and the built reference landing `docs/mockups/index.html`. Reuse token names and the grain overlay VERBATIM — do not invent new tokens.

- [ ] **Step 1: Append failing test to `tests/test_web.py`**

Append:
```python
def test_features_page_has_editorial_sections(client):
    r = client.get("/features")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["Single source of truth", "Sign in with Google",
                   "Limitations", "ledger.css"]:
        assert needle in body
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_web.py::test_features_page_has_editorial_sections -q`
Expected: FAIL (current placeholder lacks these strings).

- [ ] **Step 3: Create `src/khata/static/assets/ledger.css`**

Assemble the shared stylesheet from `docs/mockups/_SHARED_KIT.md`. It MUST contain, in order:
1. The `:root{...}` INR token block and the `html[data-cur="usd"]{...}` token block **verbatim** from §2 of the kit.
2. The base reset, `body` (with `background`/`color`/`font-family`/transition), the `body::before` film-grain overlay, `.mono`, and `a` rules **verbatim** from §2.
3. Marketing/page chrome used by both static pages (these are new, lightweight, token-based — add them):
```css
.wrap{max-width:1080px;margin:0 auto;padding:0 24px;position:relative;z-index:1}
.nav{display:flex;align-items:center;justify-content:space-between;padding:22px 0}
.nav .brand{display:flex;align-items:center;gap:10px;font-family:"Fraunces",serif;font-weight:600;font-size:21px}
.nav .glyph{width:28px;height:28px;border-radius:8px;background:linear-gradient(145deg,var(--primary),var(--primary-deep));box-shadow:0 6px 14px -6px var(--primary)}
.nav a.link{color:var(--ink-soft);font-weight:500;margin-left:22px}
.nav a.link:hover{color:var(--ink)}
.hero{padding:64px 0 40px}
.hero h1{font-family:"Fraunces",serif;font-weight:600;font-size:clamp(34px,6vw,60px);letter-spacing:-.02em;line-height:1.04}
.hero p{color:var(--ink-soft);font-size:18px;margin-top:16px;max-width:60ch}
.feat{border-top:1px solid var(--line);padding:34px 0;display:grid;grid-template-columns:200px 1fr;gap:28px}
@media(max-width:760px){.feat{grid-template-columns:1fr;gap:10px}}
.feat h2{font-family:"Fraunces",serif;font-weight:600;font-size:23px;letter-spacing:-.01em}
.feat p{color:var(--ink-soft);max-width:64ch;margin-bottom:10px}
.lim{display:inline-block;font-size:12px;font-family:"JetBrains Mono";text-transform:uppercase;letter-spacing:.1em;color:var(--accent);font-weight:700;margin-right:8px}
.btn{display:inline-block;background:linear-gradient(145deg,var(--primary),var(--primary-deep));color:#fff;font-weight:600;padding:11px 20px;border-radius:100px;box-shadow:0 10px 24px -12px var(--primary);cursor:pointer;border:none;font-size:15px}
.foot{border-top:1px solid var(--line);padding:30px 0;color:var(--ink-faint);font-size:13px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px}
.reveal{opacity:0;transform:translateY(14px);transition:opacity .7s var(--ease),transform .7s var(--ease)}
.reveal.in{opacity:1;transform:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:24px;box-shadow:var(--shadow)}
.authrow{display:flex;flex-direction:column;gap:12px;max-width:360px}
.authrow input{font-family:inherit;font-size:15px;padding:11px 13px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink)}
.authrow .err{color:var(--neg);font-size:13px;min-height:18px}
.gbtn{margin-top:6px}
.muted{color:var(--ink-faint);font-size:13px}
.tlink{color:var(--primary);font-weight:600;cursor:pointer}
```

- [ ] **Step 4: Replace `src/khata/static/features.html`**

Write the full page. Fonts come from the kit's §1 `<link>`; styles from `/static/assets/ledger.css`. The reveal JS at the bottom is the kit's IntersectionObserver pattern.
```html
<!DOCTYPE html>
<html lang="en" data-cur="inr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Khata — Features &amp; Limitations</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/assets/ledger.css">
</head>
<body>
<div class="wrap">
  <nav class="nav">
    <a class="brand" href="/"><span class="glyph"></span> Khata</a>
    <div><a class="link" href="/features">Features</a><a class="link" href="/app">Open app</a></div>
  </nav>

  <header class="hero reveal">
    <h1>Honest features.<br>Honest limits.</h1>
    <p>Khata is a privacy-first, self-hosted money-plans and net-worth ledger. Here is exactly what it does — and, just as important, what it does not.</p>
  </header>

  <section class="feat reveal">
    <h2>Shared plans &amp; attribution</h2>
    <div><p>Invite family members to a plan; every payment is attributed to whoever logged it, and each contributor's ownership share is derived from what they actually paid in.</p>
    <p><span class="lim">Limitations</span> Ownership share reflects recorded contributions, not legal title. Adding a member needs their existing account email.</p></div>
  </section>

  <section class="feat reveal">
    <h2>Single source of truth</h2>
    <div><p>Every balance — paid-to-date, remaining, interest due, net position — is computed from recorded ledger rows each time you read it. Nothing is stored that could drift out of sync.</p>
    <p><span class="lim">Limitations</span> Accuracy depends on what you log. Khata reads no bank feeds in this phase; nothing is inferred automatically.</p></div>
  </section>

  <section class="feat reveal">
    <h2>Money as exact integers</h2>
    <div><p>Amounts are stored as integer minor units (paise, cents) and computed with exact decimal arithmetic. Rates are integer basis points. No floating-point money, ever.</p>
    <p><span class="lim">Limitations</span> Each plan has one fixed original currency; cross-currency net worth is not yet consolidated.</p></div>
  </section>

  <section class="feat reveal">
    <h2>Asset purchase roll-forward</h2>
    <div><p>Set an installment schedule, log payments as they happen, and Khata rolls your total paid forward across the schedule — showing what's covered, what's next, and where you're ahead or behind.</p>
    <p><span class="lim">Limitations</span> Payments apply greedily in schedule order; there is no per-payment-to-installment tagging.</p></div>
  </section>

  <section class="feat reveal">
    <h2>Loans with derived interest</h2>
    <div><p>Track money lent or borrowed with reducing-balance simple interest, accrued whole-month from the start date. Principal, interest accrued, interest due, and a monthly schedule are all derived.</p>
    <p><span class="lim">Limitations</span> Simple interest only (no compounding/EMI amortization yet); unsecured loans only (no collateral in this phase).</p></div>
  </section>

  <section class="feat reveal">
    <h2>Net-position dashboard</h2>
    <div><p>One rollup of what you owe, what you're owed, and what you've paid into your asset plans — net position at a glance, with the plans behind it.</p>
    <p><span class="lim">Limitations</span> Totals are per-currency sums; mixed-currency portfolios are not yet consolidated into a single figure.</p></div>
  </section>

  <section class="feat reveal">
    <h2>Self-hosted &amp; private</h2>
    <div><p>Run Khata on your own machine or server. Your ledger lives in your SQLite database; no third party sees your finances.</p>
    <p><span class="lim">Limitations</span> Backups, TLS, and host security are your responsibility — Khata ships sensible defaults, not a managed service.</p></div>
  </section>

  <section class="feat reveal">
    <h2>Sign in with Google</h2>
    <div><p>Optionally enable Google sign-in: a one-tap identity check, verified server-side, that links to your account by verified email. Email/password still works without it.</p>
    <p><span class="lim">Limitations</span> Identity only — Khata requests no access to your Google data. Self-hosters must configure their own Google client ID; otherwise the button simply does not appear.</p></div>
  </section>

  <footer class="foot">
    <span>Khata — your money, your ledger, your machine.</span>
    <span><a class="link" href="/">Home</a> · <a class="link" href="/app">Open app</a></span>
  </footer>
</div>
<script>
  const io = new IntersectionObserver((es) => {
    es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
  }, { threshold: .12 });
  document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
</script>
</body>
</html>
```

- [ ] **Step 5: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_web.py -q` (expect all pass — the existing `test_features_page_lists_limitations` still passes because "Limitations" appears), then `.venv/bin/python -m pytest -q` (expect 77 passed — 76 + 1 new).

- [ ] **Step 6: Commit**

```bash
git add src/khata/static/assets/ledger.css src/khata/static/features.html tests/test_web.py
git commit -m "feat(web): shared ledger.css + editorial Features & Limitations page

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Editorial landing + login section with Google button

**Files:** Replace `src/khata/static/index.html`; Test `tests/test_web.py`

- [ ] **Step 1: Append failing test to `tests/test_web.py`**

Append:
```python
def test_landing_has_login_and_google_hook(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.data.decode()
    assert "/api/auth/login" in body
    assert "/api/auth/config" in body      # decides whether to show Google button
    assert "/api/auth/google" in body
    assert "ledger.css" in body
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_web.py::test_landing_has_login_and_google_hook -q`
Expected: FAIL (placeholder lacks these strings).

- [ ] **Step 3: Replace `src/khata/static/index.html`**

The page reuses `ledger.css`, shows a hero + a login card. The login card supports a sign-in/register toggle (POSTing to the existing `/api/auth/login` and `/api/auth/register`) and renders the Google button only when `/api/auth/config` returns a `google_client_id`.
```html
<!DOCTYPE html>
<html lang="en" data-cur="inr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Khata — your money, your ledger</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/assets/ledger.css">
</head>
<body>
<div class="wrap">
  <nav class="nav">
    <a class="brand" href="/"><span class="glyph"></span> Khata</a>
    <div><a class="link" href="/features">Features</a><a class="link" href="/app">Open app</a></div>
  </nav>

  <section class="hero" style="display:grid;grid-template-columns:1.2fr .8fr;gap:48px;align-items:center">
    <div class="reveal">
      <h1>Your money,<br>your ledger,<br>your machine.</h1>
      <p>A privacy-first, self-hosted ledger for money plans and net worth — INR-native, multi-currency, exact to the paise. <a class="tlink" href="/features">See features &amp; limits →</a></p>
    </div>

    <div class="card reveal" id="auth">
      <div class="authrow">
        <strong id="auth-title" style="font-family:'Fraunces',serif;font-size:20px">Sign in</strong>
        <input id="email" type="email" placeholder="you@example.com" autocomplete="email">
        <input id="name" type="text" placeholder="Display name" autocomplete="name" style="display:none">
        <input id="password" type="password" placeholder="Password" autocomplete="current-password">
        <div class="err" id="err"></div>
        <button class="btn" id="submit">Sign in</button>
        <div class="muted">
          <span id="toggle-text">New here?</span>
          <span class="tlink" id="toggle">Create an account</span>
        </div>
        <div id="google-area" style="display:none">
          <div class="muted" style="margin:8px 0">— or —</div>
          <div id="g_id_onload"></div>
          <div class="gbtn" id="g_btn"></div>
        </div>
      </div>
    </div>
  </section>

  <footer class="foot">
    <span>Khata — your money, your ledger, your machine.</span>
    <span><a class="link" href="/features">Features</a></span>
  </footer>
</div>

<script>
  const $ = (id) => document.getElementById(id);
  let mode = "login";  // or "register"

  $("toggle").addEventListener("click", () => {
    mode = mode === "login" ? "register" : "login";
    const reg = mode === "register";
    $("auth-title").textContent = reg ? "Create account" : "Sign in";
    $("submit").textContent = reg ? "Create account" : "Sign in";
    $("name").style.display = reg ? "block" : "none";
    $("toggle-text").textContent = reg ? "Have an account?" : "New here?";
    $("toggle").textContent = reg ? "Sign in" : "Create an account";
    $("err").textContent = "";
  });

  $("submit").addEventListener("click", async () => {
    $("err").textContent = "";
    const path = mode === "register" ? "/api/auth/register" : "/api/auth/login";
    const payload = { email: $("email").value, password: $("password").value };
    if (mode === "register") payload.display_name = $("name").value;
    const r = await fetch(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (r.ok) { window.location.href = "/app"; return; }
    const e = await r.json().catch(() => ({}));
    $("err").textContent = ({
      invalid_credentials: "Wrong email or password.",
      email_taken: "That email already has an account.",
      invalid: "Check your details and try again.",
    })[e.error] || "Something went wrong.";
  });

  // Google button — only if the server has a client id configured.
  (async () => {
    let cid = null;
    try { cid = (await (await fetch("/api/auth/config")).json()).google_client_id; } catch (_) {}
    if (!cid) return;
    $("google-area").style.display = "block";
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => {
      google.accounts.id.initialize({ client_id: cid, callback: onGoogle });
      google.accounts.id.renderButton($("g_btn"), { theme: "outline", size: "large", width: 320 });
    };
    document.head.appendChild(s);
  })();

  async function onGoogle(resp) {
    const r = await fetch("/api/auth/google", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential: resp.credential }),
    });
    if (r.ok) { window.location.href = "/app"; return; }
    const e = await r.json().catch(() => ({}));
    $("err").textContent = ({
      email_unverified: "Your Google email isn't verified.",
      google_not_configured: "Google sign-in isn't enabled here.",
    })[e.error] || "Google sign-in failed.";
  }

  const io = new IntersectionObserver((es) => {
    es.forEach((x) => { if (x.isIntersecting) { x.target.classList.add("in"); io.unobserve(x.target); } });
  }, { threshold: .12 });
  document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
</script>
</body>
</html>
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_web.py -q` (expect all pass — `test_landing_served` still passes, "Khata" is present), then `.venv/bin/python -m pytest -q` (expect 78 passed — 77 + 1 new).

- [ ] **Step 5: Commit**

```bash
git add src/khata/static/index.html tests/test_web.py
git commit -m "feat(web): editorial landing with login section + conditional Google button

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Smoke test + process docs

**Files:** Modify `build_status.json`, `docs/AGENT_LEARNINGS.md`

- [ ] **Step 1: Smoke-test the auth endpoints (stubbed Google) + pages**

```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db PYTHONPATH=src .venv/bin/python wsgi.py > /tmp/khata_p5.log 2>&1 &
sleep 2.5
echo "== config (unconfigured) =="; curl -s localhost:5050/api/auth/config
echo; echo "== google when unconfigured =="; curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:5050/api/auth/google -H 'Content-Type: application/json' -d '{"credential":"x"}'
echo "== features page has sections =="; curl -s localhost:5050/features | grep -c "Single source of truth"
echo "== landing has google hook =="; curl -s localhost:5050/ | grep -c "/api/auth/config"
echo "== ledger.css served =="; curl -s -o /dev/null -w "%{http_code}\n" localhost:5050/static/assets/ledger.css
kill %1 2>/dev/null
```
Expected: `config` → `{"google_client_id":null}`; google-when-unconfigured → `503`; features grep → `1`; landing grep → `1`; ledger.css → `200`. (The full Google sign-in round-trip needs a real client ID + browser; the stubbed-verifier path is already proven by the Task-5 API tests.)

- [ ] **Step 2: Replace `build_status.json`**

```json
{
  "project": "khata",
  "phase": 1,
  "plan": "5-google-auth-features",
  "tasks_total": 8,
  "tasks_done": 8,
  "last_updated": "2026-06-04",
  "tests": "78 passed",
  "python": "3.12",
  "notes": "Plan 5 complete: Google sign-in (GIS ID-token, server-verified via google-auth, injected verifier; auto-link by verified email, find-by-sub/link/create), GET /api/auth/config + POST /api/auth/google, users.google_sub. Frontend: shared ledger.css, editorial Features & Limitations page, landing login section with conditional Google button. Next: Phase 2 candidates — secured loans/collateral, holdings/net-worth, chit funds, or letting Google users set a password."
}
```

- [ ] **Step 3: Append to `docs/AGENT_LEARNINGS.md`**

```markdown

## 2026-06-04 — Plan 5 (Google sign-in + Features page)
- Google sign-in is identity-only via GIS ID tokens. The verifier (`verify_google_credential`,
  google-auth) is **injected** through `app.config["GOOGLE_VERIFIER"]` and imports google-auth
  lazily, so all auth logic is unit-tested with plain claims dicts — no network, no real client ID.
- `login_with_google` is find-by-`google_sub` → link-by-verified-email → create. Linking/creation is
  gated on `email_verified` (raises `EmailUnverifiedError` → 403). `google_sub` is unique; matching by
  sub first means a changed Google email never forks the account.
- API split: `GET /api/auth/config` exposes the (public) client id so a fully static frontend can
  decide whether to render the Google button; `POST /api/auth/google` 503s when unconfigured — so
  self-hosters who skip OAuth still get working email/password.
- Frontend now has a real shared stylesheet `static/assets/ledger.css` (extracted from the mockup
  kit) used by both static pages — the first step toward building the real app UI off the mockups.

### Deferred follow-ups
- Let Google-created users (password_hash=NULL) set a password later (account settings).
- Import Google profile picture (we already support manual upload; left out per YAGNI).
- The landing/login page is hand-rolled HTML+JS; when the real app shell is built, consolidate the
  auth JS into a shared module.
```

- [ ] **Step 4: Commit**

```bash
rm -f /tmp/khata_p5.log khata.db khata.db-wal khata.db-shm
git add build_status.json docs/AGENT_LEARNINGS.md
git commit -m "chore(process): Plan 5 complete — build status + learnings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- `users.google_sub` + migration → Tasks 1, 2. ✓
- Injectable verifier (`verify_google_credential`, lazy google-auth, app config) → Tasks 3, 4. ✓
- `login_with_google` find-by-sub / link-by-verified-email / create; `GoogleAuthError` + `EmailUnverifiedError` → Task 4. ✓
- `GET /api/auth/config`, `POST /api/auth/google` (503/401/403 dispatch, session, `created`) → Task 5. ✓
- `KHATA_GOOGLE_CLIENT_ID` config + `google-auth`/`requests` deps → Task 3. ✓
- Shared `ledger.css` + full editorial Features page → Task 6. ✓
- Landing login section + conditional Google button (config-gated) → Task 7. ✓
- Smoke + docs → Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code/HTML/CSS step is complete and copy-pasteable. Frontend chrome reuses the locked kit tokens verbatim (cited to `_SHARED_KIT.md` §1/§2), not invented. ✓

**Type consistency:** `login_with_google(session, *, claims) -> (User, bool)`, verifier signature `(credential, client_id) -> dict`, error types `GoogleAuthError`/`EmailUnverifiedError`, config key `GOOGLE_VERIFIER`, config attr `google_client_id`, endpoint error strings (`google_not_configured`/`invalid_token`/`email_unverified`) are consistent across service, API, tests, and frontend. Test counts chain: 64 → 65 (T1) → 65 (T2) → 70 (T4) → 76 (T5) → 77 (T6) → 78 (T7). ✓

**Note on Task 3/4 coupling:** Task 3's factory imports `verify_google_credential`, which Task 4 defines. They are committed together (Task 4 Step 5) and the plan flags running the full suite only after Task 4. A subagent executing Task 3 alone must proceed straight into Task 4 before running the app/full suite. ✓

---

## Next (Phase 2 candidates)
- Secured loans / collateral; holdings & net-worth consolidation (incl. cross-currency); chit funds.
- Let Google-created users set a password; consolidate frontend auth JS when the app shell is built.
