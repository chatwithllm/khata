# Plan Share Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Public, read-only, tokenized share links for all 5 plan types — with expiry (7/30/90d) + revoke, a `summary`|`full` (PII-redacted) scope, token-less print, and `navigator.share` send.

**Architecture:** New `plan_shares` table + `sharing_links` service. A public blueprint serves `GET /api/public/<token>` (scoped/redacted JSON, no auth) and `GET /s/<token>` (standalone print-friendly page). Owner-only `POST/GET/DELETE /plans/<id>/shares`. Detail pages get a Share menu. Live data — the public view re-renders current `*_state` on each open.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy, Alembic, pytest; vanilla-JS static pages.

---

## File Structure

- **Create** `src/khata/models/share.py` — `PlanShare` model (Task 1).
- **Modify** `src/khata/models/__init__.py` — export `PlanShare` (Task 1).
- **Create** `alembic/versions/sh1share01_plan_shares.py` — migration (Task 1).
- **Create** `src/khata/services/sharing_links.py` — token service + redaction (Task 2).
- **Modify** `src/khata/api/plans.py` — owner `POST/GET/DELETE /<id>/shares` (Task 3).
- **Create** `src/khata/api/public.py` — public blueprint `GET /api/public/<token>` (Task 4).
- **Modify** `src/khata/__init__.py` — register public blueprint (Task 4).
- **Modify** `src/khata/web.py` — `GET /s/<token>` route (Task 5).
- **Create** `src/khata/static/public-plan.html` — standalone read-only/print page (Task 5).
- **Modify** the 5 `*-detail.html` — Share menu + manage/revoke (Task 6).
- **Modify** `docs/specs/khata-AS-BUILT.md` (Task 7).
- **Tests:** `tests/test_sharing_links.py` (Task 2), `tests/test_share_owner_api.py` (Task 3), `tests/test_public_share_api.py` (Task 4).

Verified facts the plan relies on:
- Models use `from ..db import Base`, `Mapped`/`mapped_column`, `ForeignKey("plans.id", ondelete="CASCADE")`, a module-local `_utcnow`. Models are registered by importing in `models/__init__.py`.
- Current alembic head is `fxsnapshot01` (new migration's `down_revision = "fxsnapshot01"`).
- State serializers: `assets.asset_state(session, plan, viewer_id=None)`, `loans.loan_state(session, loan, as_of)`, `holdings.holding_state(session, holding)`, `chits.chit_state(session, chit, as_of=None)`, `retirement.retirement_state(session, retirement)`. Accessed via `plan.asset/loan/holding/chit/retirement`. These emit contributor **names**, `has_proof` (bool) — **not** emails or raw proof refs. The members list is a separate endpoint, never in `*_state`.
- `api/plans.py` has `_owned_plan(user, plan_id) -> (plan, err)`; routes return `jsonify(...), <code>`; `current_user()` from `.auth`. `Plan, User` imported from `..models`.
- `web.py` is `Blueprint("web", ...)` serving `send_from_directory(_static_dir(), "<file>.html")`; detail routes like `@bp.get("/asset/<int:plan_id>")`.
- Blueprints registered in `__init__.py` via `app.register_blueprint(<bp>)`.
- pytest: `tests/test_loan_service.py` uses an in-memory `ctx` fixture `(session, user)` + `_dt`; `tests/conftest.py` provides `app`/`client` and disables live FX; `tests/test_secured_loans_api.py` shows the client auth/seed idiom (register → session cookie; create plan via API).

Test command (venv is in the primary checkout, not this worktree):
`cd /tmp/khata-share && PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest <args>`

---

### Task 1: `PlanShare` model + migration

**Files:**
- Create `src/khata/models/share.py`
- Modify `src/khata/models/__init__.py`
- Create `alembic/versions/sh1share01_plan_shares.py`

- [ ] **Step 1: Write the model**

`src/khata/models/share.py`:
```python
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PlanShare(Base):
    __tablename__ = "plan_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(8), nullable=False, default="summary")  # summary|full
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    plan: Mapped["Plan"] = relationship()
```

- [ ] **Step 2: Export it**

In `src/khata/models/__init__.py` add after the membership import:
```python
from .share import PlanShare  # noqa: F401
```

- [ ] **Step 3: Write the migration**

`alembic/versions/sh1share01_plan_shares.py`:
```python
"""plan_shares — public read-only share links

Revision ID: sh1share01
Revises: fxsnapshot01
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "sh1share01"
down_revision: Union[str, None] = "fxsnapshot01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_shares",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(8), nullable=False, server_default="summary"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_plan_shares_plan_id", "plan_shares", ["plan_id"])
    op.create_index("ix_plan_shares_token", "plan_shares", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_plan_shares_token", table_name="plan_shares")
    op.drop_index("ix_plan_shares_plan_id", table_name="plan_shares")
    op.drop_table("plan_shares")
```

- [ ] **Step 4: Verify migration applies + single head**

Run:
```
cd /tmp/khata-share
KHATA_DATABASE_URL="sqlite:////tmp/sh-mig-test.db" PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/alembic upgrade head
PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/alembic heads
rm -f /tmp/sh-mig-test.db
```
Expected: upgrade runs clean; `heads` shows a single head `sh1share01`.

- [ ] **Step 5: Commit**
```bash
git add src/khata/models/share.py src/khata/models/__init__.py alembic/versions/sh1share01_plan_shares.py
git commit -m "feat(share): PlanShare model + plan_shares migration"
```

---

### Task 2: `sharing_links` service (create/list/revoke/resolve/redact)

**Files:**
- Create `src/khata/services/sharing_links.py`
- Test: `tests/test_sharing_links.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_sharing_links.py`:
```python
from datetime import date, datetime, timezone, timedelta

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.loans import create_loan_plan, add_disbursement
from khata.services import sharing_links as sl


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="a@b.com", display_name="Arjun", password_hash="x")
        s.add(u); s.flush()
        plan = create_loan_plan(s, owner_id=u.id, name="Lent", currency="INR",
                                direction="given", interest_type="monthly", rate_bps=300,
                                start_date=date(2023, 12, 12))
        add_disbursement(s, plan=plan, user_id=u.id, amount_minor=220000000,
                         occurred_at=datetime(2023, 12, 12, tzinfo=timezone.utc))
        s.flush()
        yield s, u, plan


def test_create_share_defaults_and_token(ctx):
    s, u, plan = ctx
    sh = sl.create_share(s, plan=plan, user_id=u.id, scope="summary", ttl_days=30)
    s.flush()
    assert sh.scope == "summary"
    assert len(sh.token) >= 32 and sh.revoked_at is None
    assert sh.expires_at > datetime.now(timezone.utc) + timedelta(days=29)


def test_create_share_validates(ctx):
    s, u, plan = ctx
    with pytest.raises(sl.ShareError):
        sl.create_share(s, plan=plan, user_id=u.id, scope="bogus", ttl_days=30)
    with pytest.raises(sl.ShareError):
        sl.create_share(s, plan=plan, user_id=u.id, scope="full", ttl_days=5)


def test_resolve_public_valid_expired_revoked_unknown(ctx):
    s, u, plan = ctx
    sh = sl.create_share(s, plan=plan, user_id=u.id, scope="full", ttl_days=7)
    s.flush()
    p, scope = sl.resolve_public(s, sh.token)
    assert p.id == plan.id and scope == "full"
    # unknown
    with pytest.raises(sl.ShareNotFound):
        sl.resolve_public(s, "nope-not-a-token")
    # revoked
    sl.revoke_share(s, plan=plan, share_id=sh.id); s.flush()
    with pytest.raises(sl.ShareGone):
        sl.resolve_public(s, sh.token)
    # expired
    sh2 = sl.create_share(s, plan=plan, user_id=u.id, scope="full", ttl_days=7)
    sh2.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); s.flush()
    with pytest.raises(sl.ShareGone):
        sl.resolve_public(s, sh2.token)


def test_public_state_redacts_and_scopes(ctx):
    s, u, plan = ctx
    full = sl.public_state(s, plan, "full")
    summ = sl.public_state(s, plan, "summary")
    import json
    # envelope basics
    for env in (full, summ):
        assert env["plan_type"] == "loan" and env["name"] == "Lent"
        assert env["scope"] in ("full", "summary")
    # no email / proof leakage anywhere
    blob = json.dumps(full)
    assert "@b.com" not in blob and "proof_ref" not in blob
    assert "members" not in full and "members" not in full.get("state", {})
    # full keeps the ledger/schedule; summary drops them
    assert "schedule" in full["state"]
    assert "schedule" not in summ["state"] and "ledger" not in summ["state"]


def test_list_and_revoke(ctx):
    s, u, plan = ctx
    a = sl.create_share(s, plan=plan, user_id=u.id, scope="summary", ttl_days=7)
    b = sl.create_share(s, plan=plan, user_id=u.id, scope="full", ttl_days=30)
    s.flush()
    rows = sl.list_shares(s, plan)
    assert len(rows) == 2 and {r["scope"] for r in rows} == {"summary", "full"}
    sl.revoke_share(s, plan=plan, share_id=a.id); s.flush()
    rows2 = {r["id"]: r for r in sl.list_shares(s, plan)}
    assert rows2[a.id]["status"] == "revoked" and rows2[b.id]["status"] == "active"
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest tests/test_sharing_links.py -v`
Expected: FAIL — `ModuleNotFoundError: khata.services.sharing_links`.

- [ ] **Step 3: Implement the service**

`src/khata/services/sharing_links.py`:
```python
import secrets
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, PlanShare, User
from ..services import assets, loans, holdings, chits, retirement


class ShareError(Exception):
    """Bad input creating a share."""


class ShareNotFound(Exception):
    """Token does not exist."""


class ShareGone(Exception):
    """Token exists but is expired or revoked."""


VALID_SCOPES = {"summary", "full"}
VALID_TTL_DAYS = {7, 30, 90}
# top-level line-item arrays dropped in 'summary' scope
_SUMMARY_DROP = {"ledger", "schedule", "deployed", "installments", "members"}
# keys scrubbed everywhere (defence-in-depth; state serializers shouldn't emit these)
_SCRUB_KEYS = {"email", "proof_ref", "attachments", "attachment_id", "members"}


def create_share(session: Session, *, plan: Plan, user_id, scope: str, ttl_days: int) -> PlanShare:
    if scope not in VALID_SCOPES:
        raise ShareError(f"unknown scope: {scope}")
    if ttl_days not in VALID_TTL_DAYS:
        raise ShareError(f"ttl_days must be one of {sorted(VALID_TTL_DAYS)}")
    sh = PlanShare(
        plan_id=plan.id, token=secrets.token_urlsafe(32), scope=scope,
        expires_at=datetime.now(timezone.utc) + timedelta(days=ttl_days),
        created_by_user_id=user_id)
    session.add(sh)
    session.flush()
    return sh


def _status(sh: PlanShare) -> str:
    if sh.revoked_at is not None:
        return "revoked"
    exp = sh.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return "expired" if exp <= datetime.now(timezone.utc) else "active"


def list_shares(session: Session, plan: Plan) -> list[dict]:
    rows = session.scalars(
        select(PlanShare).where(PlanShare.plan_id == plan.id)
        .order_by(PlanShare.created_at.desc())).all()
    out = []
    for sh in rows:
        st = _status(sh)
        out.append({
            "id": sh.id, "scope": sh.scope, "status": st,
            "expires_at": sh.expires_at.isoformat(),
            "created_at": sh.created_at.isoformat() if sh.created_at else None,
            # only hand back the token for usable links
            "token": sh.token if st == "active" else None,
        })
    return out


def revoke_share(session: Session, *, plan: Plan, share_id: int) -> None:
    sh = session.get(PlanShare, share_id)
    if sh is None or sh.plan_id != plan.id:
        raise ShareNotFound("no such share on this plan")
    if sh.revoked_at is None:
        sh.revoked_at = datetime.now(timezone.utc)
    session.flush()


def resolve_public(session: Session, token: str):
    sh = session.scalar(select(PlanShare).where(PlanShare.token == token))
    if sh is None:
        raise ShareNotFound("unknown token")
    if _status(sh) != "active":
        raise ShareGone("link expired or revoked")
    plan = session.get(Plan, sh.plan_id)
    if plan is None:
        raise ShareNotFound("plan gone")
    return plan, sh.scope


def _scrub(obj):
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in _SCRUB_KEYS}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def _raw_state(session: Session, plan: Plan) -> dict:
    t = plan.type
    if t == "asset":
        return assets.asset_state(session, plan, viewer_id=None)
    if t == "loan":
        return loans.loan_state(session, plan.loan, as_of=datetime.now(timezone.utc).date())
    if t == "holding":
        return holdings.holding_state(session, plan.holding)
    if t == "chit":
        return chits.chit_state(session, plan.chit)
    if t == "retirement":
        return retirement.retirement_state(session, plan.retirement)
    raise ShareError(f"unshareable plan type: {t}")


def public_state(session: Session, plan: Plan, scope: str) -> dict:
    state = _scrub(_raw_state(session, plan))
    if scope == "summary":
        state = {k: v for k, v in state.items() if k not in _SUMMARY_DROP}
    owner = session.get(User, plan.owner_user_id)
    return {
        "plan_type": plan.type,
        "name": plan.name,
        "currency": plan.currency,
        "status": plan.status,
        "scope": scope,
        "owner_name": owner.display_name if owner else None,
        "as_of": datetime.now(timezone.utc).date().isoformat(),
        "state": state,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest tests/test_sharing_links.py -v`
Expected: PASS (5 tests). If `summary`'s drop assertion fails because a type uses a different array key, add that key to `_SUMMARY_DROP` (keep it to genuine line-item arrays).

- [ ] **Step 5: Commit**
```bash
git add src/khata/services/sharing_links.py tests/test_sharing_links.py
git commit -m "feat(share): sharing_links service — tokens, scope, redaction"
```

---

### Task 3: Owner API — create/list/revoke shares

**Files:**
- Modify `src/khata/api/plans.py` (append 3 routes after the loan routes; add import).
- Test: `tests/test_share_owner_api.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_share_owner_api.py`. FIRST read `tests/conftest.py` + `tests/test_secured_loans_api.py` and copy their exact `client` fixture + auth/seed idiom (register → session cookie; create a plan via the API). Then assert this contract:

```python
# (fixture/auth copied from test_secured_loans_api.py)
def test_create_list_revoke_share(client):
    pid = _make_asset_or_loan(client)          # create any plan via API, return its id
    # create
    r = client.post(f"/api/plans/{pid}/shares", json={"scope": "summary", "ttl_days": 30})
    assert r.status_code == 201
    body = r.get_json()
    assert body["url"].endswith("/s/" + body["share"]["token"])
    sid = body["share"]["id"]
    # list
    r = client.get(f"/api/plans/{pid}/shares")
    assert r.status_code == 200 and len(r.get_json()["shares"]) == 1
    # revoke
    r = client.delete(f"/api/plans/{pid}/shares/{sid}")
    assert r.status_code == 204
    r = client.get(f"/api/plans/{pid}/shares")
    assert r.get_json()["shares"][0]["status"] == "revoked"


def test_create_share_bad_input_400(client):
    pid = _make_asset_or_loan(client)
    assert client.post(f"/api/plans/{pid}/shares",
                       json={"scope": "x", "ttl_days": 30}).status_code == 400
    assert client.post(f"/api/plans/{pid}/shares",
                       json={"scope": "full", "ttl_days": 5}).status_code == 400


def test_share_owner_only_403(client):
    pid = _make_asset_or_loan(client)
    _login_as_other_user(client)               # register + auth a different user (see secured_loans test)
    assert client.post(f"/api/plans/{pid}/shares",
                       json={"scope": "summary", "ttl_days": 7}).status_code == 403
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest tests/test_share_owner_api.py -v`
Expected: FAIL (404/405 — routes not defined).

- [ ] **Step 3: Implement the routes**

In `src/khata/api/plans.py`, add to the services import line: `from ..services import sharing_links` (or extend the existing `from ..services import ...`). Append after the loan routes:

```python
@bp.post("/<int:plan_id>/shares")
def create_share(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        sh = sharing_links.create_share(
            g.db, plan=plan, user_id=user.id,
            scope=data.get("scope", "summary"), ttl_days=int(data.get("ttl_days", 30)))
        g.db.commit()
    except (sharing_links.ShareError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    url = request.host_url.rstrip("/") + "/s/" + sh.token
    return jsonify(share={"id": sh.id, "scope": sh.scope, "token": sh.token,
                          "expires_at": sh.expires_at.isoformat()}, url=url), 201


@bp.get("/<int:plan_id>/shares")
def list_shares(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    return jsonify(shares=sharing_links.list_shares(g.db, plan)), 200


@bp.delete("/<int:plan_id>/shares/<int:share_id>")
def revoke_share(plan_id, share_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    try:
        sharing_links.revoke_share(g.db, plan=plan, share_id=share_id)
        g.db.commit()
    except sharing_links.ShareNotFound:
        g.db.rollback()
        return jsonify(error="not_found"), 404
    return "", 204
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest tests/test_share_owner_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**
```bash
git add src/khata/api/plans.py tests/test_share_owner_api.py
git commit -m "feat(share): owner-only create/list/revoke share endpoints"
```

---

### Task 4: Public blueprint — `GET /api/public/<token>`

**Files:**
- Create `src/khata/api/public.py`
- Modify `src/khata/__init__.py` (register blueprint)
- Test: `tests/test_public_share_api.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_public_share_api.py` (copy the `client` fixture/auth/seed idiom from `test_secured_loans_api.py`). The contract:

```python
def test_public_view_valid_scoped(client):
    pid = _make_loan_with_dues(client)         # a loan so state has a 'schedule'
    tok = _create_share(client, pid, scope="full", ttl_days=30)   # POST /shares, return token
    r = client.get(f"/api/public/{tok}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["plan_type"] == "loan" and body["scope"] == "full"
    assert "schedule" in body["state"]
    # no PII leak
    import json
    assert "@" not in json.dumps(body) and "proof_ref" not in json.dumps(body)


def test_public_summary_drops_lines(client):
    pid = _make_loan_with_dues(client)
    tok = _create_share(client, pid, scope="summary", ttl_days=7)
    body = client.get(f"/api/public/{tok}").get_json()
    assert "schedule" not in body["state"] and "ledger" not in body["state"]


def test_public_unknown_404(client):
    assert client.get("/api/public/not-a-real-token").status_code == 404


def test_public_revoked_410(client):
    pid = _make_loan_with_dues(client)
    tok = _create_share(client, pid, scope="full", ttl_days=7)
    sid = _share_id_for(client, pid, tok)
    client.delete(f"/api/plans/{pid}/shares/{sid}")
    assert client.get(f"/api/public/{tok}").status_code == 410


def test_public_no_auth_needed(client):
    pid = _make_loan_with_dues(client)
    tok = _create_share(client, pid, scope="summary", ttl_days=7)
    client.delete_cookie("session")            # drop auth — public must still work
    assert client.get(f"/api/public/{tok}").status_code == 200
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest tests/test_public_share_api.py -v`
Expected: FAIL (404 — blueprint not registered).

- [ ] **Step 3: Implement the blueprint**

`src/khata/api/public.py`:
```python
from flask import Blueprint, g, jsonify

from ..services import sharing_links

bp = Blueprint("public", __name__, url_prefix="/api/public")


@bp.get("/<token>")
def public_view(token):
    try:
        plan, scope = sharing_links.resolve_public(g.db, token)
    except sharing_links.ShareNotFound:
        return jsonify(error="not_found"), 404
    except sharing_links.ShareGone:
        return jsonify(error="gone"), 410
    return jsonify(sharing_links.public_state(g.db, plan, scope)), 200
```

- [ ] **Step 4: Register it**

In `src/khata/__init__.py`, near the other `app.register_blueprint(...)` calls, add:
```python
    from .api.public import bp as public_bp
    app.register_blueprint(public_bp)
```
(Match the existing import style in that file — some blueprints import at top, some inline. Mirror whichever the neighbours use.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest tests/test_public_share_api.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Full suite + commit**
```bash
PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest -q   # all green
git add src/khata/api/public.py src/khata/__init__.py tests/test_public_share_api.py
git commit -m "feat(share): public read-only blueprint GET /api/public/<token>"
```

---

### Task 5: Public page `/s/<token>` + print-friendly render

**Files:**
- Modify `src/khata/web.py` (route)
- Create `src/khata/static/public-plan.html`

- [ ] **Step 1: Add the route**

In `src/khata/web.py`, after the existing detail routes, add:
```python
@bp.get("/s/<token>")
def public_plan(token):
    return send_from_directory(_static_dir(), "public-plan.html")
```
(The token is read client-side from `location.pathname`; the page calls `/api/public/<token>`.)

- [ ] **Step 2: Create the standalone page**

`src/khata/static/public-plan.html` — a self-contained page (no app shell/nav/auth). It must:
- Parse the token: `const token = location.pathname.split('/').pop();`
- `fetch('/api/public/' + token)`; on 404 → show "Link not found", on 410 → "This link has expired or was revoked", else render.
- Render an envelope header: plan name, type, owner_name, currency, status, `as_of`.
- Render headline figures from `state` (type-aware: e.g. loan → principal_outstanding/interest_due/months_behind; asset → totals; holding → current_value/gain; chit/retirement → their headline keys). For `full` scope, also render the `schedule`/`ledger` arrays as a simple read-only table when present. For `summary`, those arrays are absent — render figures only.
- A **Print** button: `<button onclick="window.print()">Print</button>`.
- A small footer: "Read-only shared view · Khata".
- `@media print { /* hide the Print button + any chrome; show the statement full-width */ }`.

Keep styling minimal and self-contained (inline `<style>`), matching the app's ink/ivory palette tokens if convenient, but it must not depend on `app.css`/`ledger.css` loading. Use the money formatting convention `amount_minor / 100` with the envelope `currency` symbol (₹ for INR, $ for USD).

- [ ] **Step 3: Headless verify (controller runs this — see note)**

This step is verified by the controller against a live server (jsdom harness): start the app from this worktree on a free port with a temp DB, seed one plan of each type via the API, create a `full` and a `summary` share for each, then load `/s/<token>` in jsdom with a fetch shim to the live server and assert: 0 page-origin JS throws; header + headline figures present; `full` shows the line table, `summary` does not; expired/revoked token shows the "expired" message; the Print button exists. Also confirm `@media print` hides the button (check the stylesheet text).

- [ ] **Step 4: Commit**
```bash
git add src/khata/web.py src/khata/static/public-plan.html
git commit -m "feat(share): public /s/<token> read-only + print page"
```

---

### Task 6: Share menu on the 5 detail pages

**Files:**
- Modify `src/khata/static/asset-detail.html`, `loan-detail.html`, `holding-detail.html`, `chit-detail.html`, `retirement-detail.html`.

Each page already fetches `/api/plans/<id>` and has a `pid` global, an `el()` helper, and a header area with action buttons (e.g. loan-detail's Edit/Delete). Add a **Share** button next to those.

- [ ] **Step 1: Shared Share-menu JS (paste into each page; adapt helper names per file)**

```js
async function openShareMenu(){
  const scope = confirm('OK = full detail, Cancel = summary only') ? 'full' : 'summary';
  const ttlAns = prompt('Link valid for how many days? (7, 30, or 90)', '30');
  const ttl = parseInt(ttlAns, 10);
  if (![7,30,90].includes(ttl)) { alert('Pick 7, 30, or 90.'); return; }
  let r;
  try {
    r = await fetch('/api/plans/'+pid+'/shares', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ scope, ttl_days: ttl }) });
    if (!r.ok) throw new Error();
  } catch(e){ alert('Could not create link.'); return; }
  const { url } = await r.json();
  if (navigator.share) { try { await navigator.share({ title: document.title, url }); }
                         catch(e){ /* user cancelled */ } }
  else { try { await navigator.clipboard.writeText(url); alert('Link copied:\n'+url); }
         catch(e){ prompt('Copy this link:', url); } }
  if (typeof loadShareList === 'function') loadShareList();
}

async function loadShareList(){
  const box = document.getElementById('share-list'); if (!box) return;
  const { shares } = await fetch('/api/plans/'+pid+'/shares').then(r=>r.json());
  box.textContent = '';
  for (const sh of shares){
    const row = el('div','share-row',
      sh.scope+' · '+sh.status+' · expires '+(sh.expires_at||'').slice(0,10)+' ');
    if (sh.status === 'active'){
      const rev = el('button','share-revoke','Revoke');
      rev.type='button';
      rev.addEventListener('click', async ()=>{
        if(!confirm('Revoke this link?')) return;
        await fetch('/api/plans/'+pid+'/shares/'+sh.id, { method:'DELETE' });
        loadShareList();
      });
      row.append(rev);
    }
    box.append(row);
  }
}
function printPlan(){ window.print(); }
```

- [ ] **Step 2: Wire the buttons + manage panel into each page**

For each `*-detail.html`:
- Add a **Share** button in the header action row: `<button type="button" onclick="openShareMenu()">Share</button>` and a **Print** button `<button type="button" onclick="printPlan()">Print</button>`.
- Add a manage container near the bottom: `<div id="share-list"></div>` under a small "Shared links" heading.
- Call `loadShareList()` inside the page's existing `boot()`/load function (after data loads).
- Add minimal `@media print` CSS to each page's `<style>` to hide nav/sidebar/buttons/share-list and print the detail cleanly (token-less owner print). Scope under the page's existing top-level class; do NOT edit `ledger.css`/`app.css`.

- [ ] **Step 3: Headless verify (controller runs)**

Controller verifies against the live server: each detail page loads with 0 JS throws, the Share + Print buttons exist, creating a link returns a `/s/<token>` URL, the manage list shows it, Revoke removes it (status → revoked). Per `/build-screen` Phase-4 headless step for each of the 5 routes.

- [ ] **Step 4: Commit**
```bash
git add src/khata/static/asset-detail.html src/khata/static/loan-detail.html src/khata/static/holding-detail.html src/khata/static/chit-detail.html src/khata/static/retirement-detail.html
git commit -m "feat(share): Share/Print menu + manage-links panel on all 5 detail pages"
```

---

### Task 7: AS-BUILT doc

**Files:**
- Modify `docs/specs/khata-AS-BUILT.md`

- [ ] **Step 1: Update the data-model + §9 + change log**

- In the data-model section, add a `plan_shares` table line (id, plan_id [cascade], token [unique], scope summary|full, expires_at, revoked_at?, created_by, created_at; migration `sh1share01`).
- Add a §9 enhancement paragraph (mirror that section's style).
- Add to the top of `## Change log`:
```
- 2026-06-19 — Public read-only share links. Any plan (all 5 types) can be shared via a
  tokenized public URL (`/s/<token>`, no login) with expiry (7/30/90d) + revoke and a
  per-share summary|full (PII-redacted) scope; plus token-less Print and navigator.share
  "send". New `plan_shares` table (migration `sh1share01`), `sharing_links` service,
  public blueprint `GET /api/public/<token>`, owner-only `POST/GET/DELETE /plans/<id>/shares`.
```

- [ ] **Step 2: Full suite + commit**
```bash
PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest -q   # all green
git add docs/specs/khata-AS-BUILT.md
git commit -m "docs(share): record public share links in AS-BUILT"
```

---

## Self-Review

**Spec coverage:**
- `plan_shares` table + token/expiry/revoke/scope → Task 1. ✅
- Service create/list/revoke/resolve + redaction (summary drops lines; scrub email/proof/members) → Task 2. ✅
- Owner-only create/list/revoke endpoints → Task 3. ✅
- Public `GET /api/public/<token>` 200/404/410, no-auth → Task 4. ✅
- Public `/s/<token>` print-friendly page → Task 5. ✅
- Share/Print/send + manage-revoke UI on all 5 detail pages, navigator.share, token-less print → Task 6. ✅
- All 5 plan types → `_raw_state` dispatch (Task 2) + public page render (Task 5). ✅
- Security: unguessable `token_urlsafe(32)`, owner-only mutations, read-only public, 410/404 → Tasks 1–4. ✅
- Docs → Task 7. ✅

**Placeholder scan:** Backend tasks (1–4) carry full code. The API test files (Tasks 3–4) intentionally defer the `client` fixture + `_make_*`/`_login_as_other_user` helpers to the project's real pattern in `conftest.py`/`test_secured_loans_api.py` — flagged explicitly because guessing the auth/seed mechanism would be wrong; the behavioral assertions are concrete. Tasks 5–6 are UI (no JS unit harness in the repo) → verified headless by the controller, with explicit pass criteria.

**Type consistency:** `create_share(scope, ttl_days)`, `resolve_public(token) -> (plan, scope)`, `public_state(plan, scope) -> envelope{plan_type,name,currency,status,scope,owner_name,as_of,state}`, `list_shares -> [{id,scope,status,expires_at,created_at,token?}]`, exceptions `ShareError|ShareNotFound|ShareGone` — used identically across service, owner API, and public API. Token routed as `/s/<token>` and `/api/public/<token>` consistently. Envelope `state` keys consumed by the public page match the scrub/summary rules.
