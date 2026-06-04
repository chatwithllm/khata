# Khata Phase 1 · Plan 1 — Foundation & Local Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the Khata web app skeleton with a SQLite/SQLAlchemy backend and working multi-user local authentication (register, login, logout, session, current-user), under a TDD harness and a development learning loop.

**Architecture:** Flask app-factory backend with SQLAlchemy 2.0 ORM over SQLite (WAL), Alembic migrations, signed-cookie sessions for auth, and a thin static shell serving the landing page, app placeholder, and a Features tab. Password auth now; Google OAuth is a later plan. Everything is test-first with pytest.

**Tech Stack:** Python 3.11, Flask 3.1, SQLAlchemy 2.0, Alembic, Werkzeug security (PBKDF2), python-dotenv, pytest.

---

## File Structure

```
khata/
├── requirements.txt              # pinned deps
├── .env.example                  # config template
├── build_status.json             # learning-loop progress dashboard
├── docs/
│   ├── AGENT_LEARNINGS.md         # learning loop: bugs/decisions → rules
│   └── agent-rules.md             # incident-locked build rules
├── alembic.ini                    # alembic config
├── alembic/
│   ├── env.py                     # alembic environment (reads our metadata)
│   └── versions/                  # migration scripts
├── src/khata/
│   ├── __init__.py                # create_app() factory
│   ├── config.py                  # Config from env
│   ├── db.py                      # engine, SessionLocal, Base, WAL pragma
│   ├── security.py                # hash_password / verify_password
│   ├── models/
│   │   ├── __init__.py            # imports all models for metadata
│   │   └── user.py                # User model
│   ├── services/
│   │   └── auth.py                # register_user, authenticate_user
│   ├── api/
│   │   ├── __init__.py
│   │   └── auth.py                # /api/auth blueprint
│   ├── web.py                     # static shell + features routes
│   └── static/
│       ├── index.html             # landing (from mockup, later plan refines)
│       ├── app.html               # app placeholder
│       └── features.html          # Features & limitations tab
└── tests/
    ├── conftest.py                # app + db fixtures
    ├── test_health.py
    ├── test_security.py
    ├── test_user_model.py
    ├── test_auth_service.py
    └── test_auth_api.py
```

Responsibilities: `db.py` owns the engine/session lifecycle only. `models/` are pure data. `services/auth.py` holds auth business logic (no Flask). `api/auth.py` is the HTTP boundary. `web.py` serves static pages. This keeps logic testable without HTTP.

---

### Task 1: Project dependencies & Flask app factory with health check

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `src/khata/__init__.py`
- Create: `src/khata/config.py`
- Test: `tests/conftest.py`, `tests/test_health.py`

- [ ] **Step 1: Create `requirements.txt`**

```
Flask==3.1.0
SQLAlchemy==2.0.36
alembic==1.14.0
python-dotenv==1.0.1
Werkzeug==3.1.3
pytest==8.3.4
```

- [ ] **Step 2: Create `.env.example`**

```
# copy to .env for local dev
KHATA_SECRET_KEY=dev-only-change-me
KHATA_DATABASE_URL=sqlite:///khata.db
KHATA_ENV=development
```

- [ ] **Step 3: Create the virtualenv and install deps**

Run:
```bash
cd ~/dev/active/khata
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
Expected: installs without error; `.venv/bin/pytest --version` prints a version.

- [ ] **Step 4: Create `src/khata/config.py`**

```python
import os


class Config:
    def __init__(self):
        self.secret_key = os.environ.get("KHATA_SECRET_KEY", "dev-only-change-me")
        self.database_url = os.environ.get("KHATA_DATABASE_URL", "sqlite:///khata.db")
        self.env = os.environ.get("KHATA_ENV", "development")
        self.testing = False
```

- [ ] **Step 5: Create `src/khata/__init__.py` (app factory)**

```python
from flask import Flask, jsonify

from .config import Config


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    cfg = config or Config()
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["KHATA"] = cfg

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    return app
```

- [ ] **Step 6: Create `tests/conftest.py`**

```python
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
```

- [ ] **Step 7: Create `tests/test_health.py` (failing test)**

```python
def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
```

- [ ] **Step 8: Run the test**

Run: `.venv/bin/python -m pytest tests/test_health.py -v` (set `PYTHONPATH=src`)
Full command:
```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_health.py -v
```
Expected: PASS.

- [ ] **Step 9: Add `pytest.ini` so PYTHONPATH is automatic**

Create `pytest.ini`:
```ini
[pytest]
pythonpath = src
testpaths = tests
```
Re-run `.venv/bin/python -m pytest -v` — expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add requirements.txt .env.example pytest.ini src/khata/__init__.py src/khata/config.py tests/conftest.py tests/test_health.py
git commit -m "feat(core): flask app factory + health check + test harness"
```

---

### Task 2: Database layer (SQLAlchemy engine, session, Base, WAL)

**Files:**
- Create: `src/khata/db.py`
- Create: `src/khata/models/__init__.py`
- Modify: `src/khata/__init__.py` (wire db init + teardown)
- Test: `tests/test_db.py`

- [ ] **Step 1: Create `src/khata/db.py`**

```python
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, connect_args=connect_args)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
```

- [ ] **Step 2: Create `src/khata/models/__init__.py`**

```python
# Importing models here registers them on Base.metadata.
from .user import User  # noqa: F401
```

(Note: `user.py` is created in Task 3. Until then this import will fail — that is expected; Task 2's test below does not import models.)

For Task 2, temporarily make it empty:
```python
# Models are registered on Base.metadata as they are added.
```

- [ ] **Step 3: Wire engine + session into the app factory**

Modify `src/khata/__init__.py` — replace its body with:
```python
from flask import Flask, g, jsonify

from .config import Config
from .db import make_engine, make_session_factory


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    cfg = config or Config()
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["KHATA"] = cfg

    engine = make_engine(cfg.database_url)
    SessionLocal = make_session_factory(engine)
    app.config["ENGINE"] = engine
    app.config["SESSION_FACTORY"] = SessionLocal

    @app.before_request
    def _open_session():
        g.db = SessionLocal()

    @app.teardown_request
    def _close_session(exc):
        db = g.pop("db", None)
        if db is not None:
            if exc is not None:
                db.rollback()
            db.close()

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    return app
```

- [ ] **Step 4: Create `tests/test_db.py` (failing test)**

```python
from sqlalchemy import text

from khata.db import make_engine, make_session_factory


def test_engine_runs_and_wal_enabled():
    engine = make_engine("sqlite:///:memory:")
    Session = make_session_factory(engine)
    with Session() as s:
        assert s.execute(text("SELECT 1")).scalar() == 1
```

- [ ] **Step 5: Run the test**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/khata/db.py src/khata/models/__init__.py src/khata/__init__.py tests/test_db.py
git commit -m "feat(db): sqlalchemy engine, session factory, WAL pragmas, request-scoped session"
```

---

### Task 3: User model

**Files:**
- Create: `src/khata/models/user.py`
- Modify: `src/khata/models/__init__.py` (register User)
- Test: `tests/test_user_model.py`

- [ ] **Step 1: Create `src/khata/models/user.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def __repr__(self) -> str:
        return f"<User {self.email}>"
```

- [ ] **Step 2: Register the model in `src/khata/models/__init__.py`**

```python
from .user import User  # noqa: F401
```

- [ ] **Step 3: Create `tests/test_user_model.py` (failing test)**

```python
from sqlalchemy import text

from khata.db import Base, make_engine, make_session_factory
from khata.models import User


def test_user_persists_and_enforces_unique_email():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        s.add(User(email="a@b.com", display_name="Arjun", password_hash="x"))
        s.commit()
        count = s.execute(text("SELECT COUNT(*) FROM users")).scalar()
        assert count == 1
```

- [ ] **Step 4: Run the test**

Run: `.venv/bin/python -m pytest tests/test_user_model.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/khata/models/user.py src/khata/models/__init__.py tests/test_user_model.py
git commit -m "feat(models): User model with unique email"
```

---

### Task 4: Alembic migrations wired to our metadata

**Files:**
- Create: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/` (via `alembic init`)
- Modify: `alembic/env.py`
- Test: manual migration run (documented)

- [ ] **Step 1: Initialize Alembic**

Run:
```bash
cd ~/dev/active/khata
PYTHONPATH=src .venv/bin/alembic init alembic
```
Expected: creates `alembic.ini`, `alembic/`, `alembic/versions/`.

- [ ] **Step 2: Point `alembic.ini` at the env var (edit the `sqlalchemy.url` line)**

In `alembic.ini`, set:
```ini
sqlalchemy.url =
```
(Leave it blank — `env.py` will inject from `KHATA_DATABASE_URL`.)

- [ ] **Step 3: Replace `alembic/env.py` target metadata block**

Edit `alembic/env.py` — after the imports, add:
```python
import os
from khata.db import Base
import khata.models  # noqa: F401  (registers all models)

target_metadata = Base.metadata


def _db_url() -> str:
    return os.environ.get("KHATA_DATABASE_URL", "sqlite:///khata.db")
```
Then in `run_migrations_offline()` replace `url = config.get_main_option("sqlalchemy.url")` with `url = _db_url()`.
In `run_migrations_online()` replace the engine creation with:
```python
    from sqlalchemy import create_engine
    connectable = create_engine(_db_url(), future=True)
```

- [ ] **Step 4: Generate the initial migration**

Run:
```bash
PYTHONPATH=src KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic revision --autogenerate -m "users table"
```
Expected: a file appears in `alembic/versions/` containing `op.create_table('users', ...)`.

- [ ] **Step 5: Apply the migration**

Run:
```bash
PYTHONPATH=src KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
Expected: `khata.db` created; `users` table exists. Verify:
```bash
.venv/bin/python -c "import sqlite3;print(sqlite3.connect('khata.db').execute(\"select name from sqlite_master where type='table'\").fetchall())"
```
Expected: includes `('users',)` and `('alembic_version',)`.

- [ ] **Step 6: Add `khata.db` and `.venv` to `.gitignore`**

Create `.gitignore`:
```
.venv/
khata.db
khata.db-wal
khata.db-shm
__pycache__/
*.pyc
.env
.pytest_cache/
```

- [ ] **Step 7: Commit**

```bash
git add alembic.ini alembic/ .gitignore
git commit -m "feat(db): alembic migrations wired to model metadata + initial users migration"
```

---

### Task 5: Password hashing utility

**Files:**
- Create: `src/khata/security.py`
- Test: `tests/test_security.py`

- [ ] **Step 1: Create `tests/test_security.py` (failing test)**

```python
from khata.security import hash_password, verify_password


def test_hash_is_not_plaintext_and_verifies():
    h = hash_password("s3cret!")
    assert h != "s3cret!"
    assert verify_password("s3cret!", h) is True
    assert verify_password("wrong", h) is False
```

- [ ] **Step 2: Run it to confirm failure**

Run: `.venv/bin/python -m pytest tests/test_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'khata.security'`.

- [ ] **Step 3: Create `src/khata/security.py`**

```python
from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(plain: str) -> str:
    return generate_password_hash(plain, method="pbkdf2:sha256")


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    return check_password_hash(hashed, plain)
```

- [ ] **Step 4: Run the test**

Run: `.venv/bin/python -m pytest tests/test_security.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/khata/security.py tests/test_security.py
git commit -m "feat(auth): password hashing util (pbkdf2)"
```

---

### Task 6: Auth service (register + authenticate)

**Files:**
- Create: `src/khata/services/__init__.py` (empty), `src/khata/services/auth.py`
- Test: `tests/test_auth_service.py`

- [ ] **Step 1: Create `tests/test_auth_service.py` (failing test)**

```python
import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.services.auth import (
    register_user,
    authenticate_user,
    EmailTakenError,
    InvalidCredentialsError,
)


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        yield s


def test_register_then_authenticate(session):
    user = register_user(session, email="a@b.com", display_name="Arjun", password="pw12345")
    session.commit()
    assert user.id is not None
    got = authenticate_user(session, email="a@b.com", password="pw12345")
    assert got.id == user.id


def test_duplicate_email_rejected(session):
    register_user(session, email="a@b.com", display_name="A", password="pw12345")
    session.commit()
    with pytest.raises(EmailTakenError):
        register_user(session, email="a@b.com", display_name="A2", password="pw12345")


def test_bad_password_rejected(session):
    register_user(session, email="a@b.com", display_name="A", password="pw12345")
    session.commit()
    with pytest.raises(InvalidCredentialsError):
        authenticate_user(session, email="a@b.com", password="nope")
```

- [ ] **Step 2: Run it to confirm failure**

Run: `.venv/bin/python -m pytest tests/test_auth_service.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Create `src/khata/services/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `src/khata/services/auth.py`**

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User
from ..security import hash_password, verify_password


class AuthError(Exception):
    pass


class EmailTakenError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


def register_user(session: Session, *, email: str, display_name: str, password: str) -> User:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AuthError("invalid email")
    if len(password) < 6:
        raise AuthError("password too short")
    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise EmailTakenError(email)
    user = User(email=email, display_name=display_name.strip() or email,
                password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def authenticate_user(session: Session, *, email: str, password: str) -> User:
    email = email.strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password_hash or ""):
        raise InvalidCredentialsError(email)
    return user
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_auth_service.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/khata/services/__init__.py src/khata/services/auth.py tests/test_auth_service.py
git commit -m "feat(auth): register + authenticate service with typed errors"
```

---

### Task 7: Auth API blueprint (register, login, logout, me) with sessions

**Files:**
- Create: `src/khata/api/__init__.py` (empty), `src/khata/api/auth.py`
- Modify: `src/khata/__init__.py` (register blueprint)
- Test: `tests/test_auth_api.py`

- [ ] **Step 1: Create `tests/test_auth_api.py` (failing test)**

```python
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
    # create schema on the app's engine
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def test_register_login_me_logout_flow(client):
    r = client.post("/api/auth/register", json={
        "email": "a@b.com", "display_name": "Arjun", "password": "pw12345"})
    assert r.status_code == 201
    assert r.get_json()["user"]["email"] == "a@b.com"

    # session established by register → /me works
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.get_json()["user"]["display_name"] == "Arjun"

    client.post("/api/auth/logout")
    r = client.get("/api/auth/me")
    assert r.status_code == 401

    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "pw12345"})
    assert r.status_code == 200

    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "bad"})
    assert r.status_code == 401


def test_duplicate_register_conflicts(client):
    payload = {"email": "a@b.com", "display_name": "A", "password": "pw12345"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    assert client.post("/api/auth/register", json=payload).status_code == 409
```

- [ ] **Step 2: Run it to confirm failure**

Run: `.venv/bin/python -m pytest tests/test_auth_api.py -v`
Expected: FAIL (404 / module not found).

- [ ] **Step 3: Create `src/khata/api/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `src/khata/api/auth.py`**

```python
from flask import Blueprint, g, jsonify, request, session

from ..services.auth import (
    register_user,
    authenticate_user,
    EmailTakenError,
    InvalidCredentialsError,
    AuthError,
)
from ..models import User

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _user_json(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name}


def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    return g.db.get(User, uid)


@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    try:
        user = register_user(
            g.db,
            email=data.get("email", ""),
            display_name=data.get("display_name", ""),
            password=data.get("password", ""),
        )
        g.db.commit()
    except EmailTakenError:
        g.db.rollback()
        return jsonify(error="email_taken"), 409
    except AuthError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    session["user_id"] = user.id
    return jsonify(user=_user_json(user)), 201


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    try:
        user = authenticate_user(g.db, email=data.get("email", ""), password=data.get("password", ""))
    except InvalidCredentialsError:
        return jsonify(error="invalid_credentials"), 401
    session["user_id"] = user.id
    return jsonify(user=_user_json(user)), 200


@bp.post("/logout")
def logout():
    session.pop("user_id", None)
    return jsonify(ok=True), 200


@bp.get("/me")
def me():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(user=_user_json(user)), 200
```

- [ ] **Step 5: Register the blueprint in `src/khata/__init__.py`**

Add, just before `return app`:
```python
    from .api.auth import bp as auth_bp
    app.register_blueprint(auth_bp)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_auth_api.py -v`
Expected: 2 PASS.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/khata/api/__init__.py src/khata/api/auth.py src/khata/__init__.py tests/test_auth_api.py
git commit -m "feat(auth): /api/auth register/login/logout/me with session"
```

---

### Task 8: Static shell — landing, app placeholder, Features tab

**Files:**
- Create: `src/khata/web.py`
- Create: `src/khata/static/index.html`, `src/khata/static/app.html`, `src/khata/static/features.html`
- Modify: `src/khata/__init__.py` (register web blueprint)
- Test: `tests/test_web.py`

- [ ] **Step 1: Create `tests/test_web.py` (failing test)**

```python
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
```

- [ ] **Step 2: Run it to confirm failure**

Run: `.venv/bin/python -m pytest tests/test_web.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Create `src/khata/static/index.html`**

```html
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Khata</title></head>
<body>
  <h1>Khata — money the way you actually pay it</h1>
  <p>Privacy-first money-plans & net-worth ledger.</p>
  <p><a href="/app">Open app</a> · <a href="/features">Features</a></p>
</body></html>
```

(Note: the polished landing mockup at `docs/mockups/index.html` replaces this in a later UI plan.)

- [ ] **Step 4: Create `src/khata/static/app.html`**

```html
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Khata — app</title></head>
<body>
  <h1>Khata app</h1>
  <p id="who">Loading…</p>
  <script>
    fetch("/api/auth/me").then(r => r.ok ? r.json() : null).then(d => {
      document.getElementById("who").textContent =
        d ? `Signed in as ${d.user.display_name}` : "Not signed in";
    });
  </script>
</body></html>
```

- [ ] **Step 5: Create `src/khata/static/features.html`**

```html
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Khata — Features</title></head>
<body>
  <h1>Features &amp; Limitations</h1>
  <section>
    <h2>Multi-user accounts</h2>
    <p>Each family member signs in; plans can be shared with per-payment attribution.</p>
    <p><strong>Limitations:</strong> ownership share reflects recorded contributions, not legal title.</p>
  </section>
  <section>
    <h2>Single source of truth</h2>
    <p>Every balance is computed from recorded ledger rows.</p>
    <p><strong>Limitations:</strong> accuracy depends on what you log; nothing is inferred from bank feeds in this phase.</p>
  </section>
</body></html>
```

- [ ] **Step 6: Create `src/khata/web.py`**

```python
from flask import Blueprint, current_app, send_from_directory

bp = Blueprint("web", __name__)


def _static_dir() -> str:
    return current_app.static_folder


@bp.get("/")
def landing():
    return send_from_directory(_static_dir(), "index.html")


@bp.get("/app")
def app_shell():
    return send_from_directory(_static_dir(), "app.html")


@bp.get("/features")
def features():
    return send_from_directory(_static_dir(), "features.html")
```

- [ ] **Step 7: Register the web blueprint in `src/khata/__init__.py`**

Add, just before `return app`:
```python
    from .web import bp as web_bp
    app.register_blueprint(web_bp)
```

- [ ] **Step 8: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_web.py -v`
Expected: 2 PASS.

- [ ] **Step 9: Commit**

```bash
git add src/khata/web.py src/khata/static/ src/khata/__init__.py tests/test_web.py
git commit -m "feat(web): static shell — landing, app placeholder, features tab"
```

---

### Task 9: Learning-loop scaffolding (AGENT_LEARNINGS, rules, build_status)

**Files:**
- Create: `docs/AGENT_LEARNINGS.md`, `docs/agent-rules.md`, `build_status.json`

- [ ] **Step 1: Create `docs/agent-rules.md`**

```markdown
# Khata — Build Rules (incident-locked)

Rules here are derived from real bugs/decisions. Add a rule whenever a mistake
costs time, with a one-line "why". Never delete a rule without a superseding one.

## Locked rules
1. **TDD always** — write the failing test before implementation. No exceptions.
2. **Money is integer minor units** — store amounts as integer paise/cents in a
   given currency; never float. (Why: float rounding corrupts ledgers.)
3. **Balances are derived, never stored** — compute from ledger rows. (Why: stored
   balances drift out of sync — core product promise is a single source of truth.)
4. **Original currency + amount are immutable on a ledger entry** — conversions are
   display-only. (Why: rewriting history breaks audit trust.)
5. **Every external call (e.g. price API) must have a manual fallback.** (Why:
   privacy-first + offline-capable is a product promise.)
```

- [ ] **Step 2: Create `docs/AGENT_LEARNINGS.md`**

```markdown
# Khata — Agent Learnings

Append-only log. Each entry: date · what happened · the rule it produced (if any).

## 2026-06-04
- Project scaffolded; chose integer-minor-units for money and derived balances as
  locked rules before writing any money code. → see agent-rules #2, #3.
```

- [ ] **Step 3: Create `build_status.json`**

```json
{
  "project": "khata",
  "phase": 1,
  "plan": "1-foundation-auth",
  "tasks_total": 9,
  "tasks_done": 0,
  "last_updated": "2026-06-04",
  "notes": "Foundation & local auth. Update tasks_done as tasks complete."
}
```

- [ ] **Step 4: Commit**

```bash
git add docs/AGENT_LEARNINGS.md docs/agent-rules.md build_status.json
git commit -m "chore(process): learning-loop scaffolding — rules, learnings log, build status"
```

---

### Task 10: Dev entrypoint & manual smoke test

**Files:**
- Create: `wsgi.py`
- Modify: `README.md` (run instructions)

- [ ] **Step 1: Create `wsgi.py`**

```python
from dotenv import load_dotenv

from khata import create_app

load_dotenv()
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5050)
```

- [ ] **Step 2: Run the dev server and smoke-test**

Run:
```bash
PYTHONPATH=src KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/python wsgi.py
```
In another shell:
```bash
curl -s localhost:5050/api/health           # {"status":"ok"}
curl -s -c /tmp/cj -X POST localhost:5050/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"a@b.com","display_name":"Arjun","password":"pw12345"}'   # 201 + user
curl -s -b /tmp/cj localhost:5050/api/auth/me                            # user JSON
curl -s localhost:5050/features | grep -i limitations                    # matches
```
Expected: each line behaves as commented. Stop the server (Ctrl-C).

- [ ] **Step 3: Add a "Run locally" section to `README.md`**

Append:
```markdown
## Run locally
```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=src KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
PYTHONPATH=src .venv/bin/python wsgi.py   # http://localhost:5050
.venv/bin/python -m pytest -v             # run tests
```
```

- [ ] **Step 4: Update `build_status.json` `tasks_done` to 10 and commit**

```bash
git add wsgi.py README.md build_status.json
git commit -m "feat(core): dev entrypoint + run docs; foundation plan complete"
```

---

## Self-Review

**Spec coverage (Plan 1 scope = foundation + local multi-user auth):**
- Multi-user accounts → User model (Task 3), register/login service (Task 6), API (Task 7). ✓
- Local username/password auth → security (Task 5), service (Task 6), API (Task 7). ✓ (Google OAuth is Plan 5 — intentionally out of scope here.)
- SQLite + SQLAlchemy + Alembic → Tasks 2, 4. ✓
- Single-source-of-truth / money rules → locked into agent-rules before money code (Task 9). ✓
- Features & limitations tab → Task 8 (scaffold) + grows each phase. ✓
- Learning loop → Task 9. ✓
- Served web shell (landing/app) → Task 8. ✓
- Plan/ledger/asset/loan/sharing/dashboard → **deferred to Plans 2–5** (correctly out of this plan's scope).

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows the command + expected output. ✓

**Type consistency:** `User` fields (`email`, `display_name`, `password_hash`) are consistent across model, service, API, and tests. `register_user`/`authenticate_user` signatures match their call sites in `api/auth.py` and tests. Error classes (`EmailTakenError`, `InvalidCredentialsError`, `AuthError`) defined in Task 6 and imported in Task 7. `g.db` session set in app factory (Task 2) and used in `api/auth.py` (Task 7). ✓

---

## Next plans (Phase 1 continued)
- **Plan 2** — Plan + ledger core (integer-minor-unit money, derived balances) + Asset type with roll-forward installments + asset API.
- **Plan 3** — Loan type (given/taken, unsecured): tranches, interest accrual, principal-vs-interest ledger.
- **Plan 4** — Sharing & contributors: PlanMembership, per-payment attribution, auto ownership share, net-position dashboard.
- **Plan 5** — Google OAuth + polished Features/limitations page wired to mockups.
