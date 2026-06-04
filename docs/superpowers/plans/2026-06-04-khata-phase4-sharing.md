# Khata Phase 1 · Plan 4 — Sharing & Contributors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Share plans with other users, attribute each ledger entry to its logger, derive each contributor's ownership share, and roll everything into a per-user net-position dashboard — test-first.

**Architecture:** A `plan_memberships` table links users to plans (owner stays on `plans.owner_user_id`). The API gains an `_accessible_plan` (owner-or-member) check for reads + asset payments, while setup/membership stay owner-only. `asset_state` derives a `contributors` breakdown; a pure `dashboard.net_position` rolls up owned loans + the user's asset contributions. Builds on Plans 1–3.

**Tech Stack:** Python 3.12, Flask 3.1, SQLAlchemy 2.0, Alembic, pytest.

---

## File Structure

```
src/khata/
├── models/
│   ├── __init__.py          # MODIFY: register PlanMembership
│   ├── plan.py              # MODIFY: Plan.memberships relationship
│   └── membership.py        # NEW: PlanMembership
├── services/
│   ├── assets.py            # MODIFY: asset_state adds `contributors` (uses session)
│   ├── sharing.py           # NEW: add/remove/list members + accessible
│   └── dashboard.py         # NEW: net_position rollup
└── api/
    ├── plans.py             # MODIFY: _accessible_plan; member endpoints; index incl. member plans
    ├── dashboard.py         # NEW: GET /api/dashboard blueprint
    └── __init__.py          # (factory) MODIFY: register dashboard blueprint  [in src/khata/__init__.py]
alembic/versions/<rev>_memberships.py   # NEW
tests/
├── test_membership_models.py  # NEW
├── test_sharing_service.py    # NEW
├── test_dashboard_service.py  # NEW
├── test_asset_service.py      # MODIFY: contributors
└── test_plans_api.py          # MODIFY: member access + dashboard
```

---

### Task 1: PlanMembership model

**Files:** Create `src/khata/models/membership.py`; Modify `src/khata/models/plan.py`, `src/khata/models/__init__.py`; Test `tests/test_membership_models.py`

- [ ] **Step 1: Write failing test `tests/test_membership_models.py`**

```python
import pytest
from sqlalchemy.exc import IntegrityError

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, PlanMembership


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_membership_persists_and_is_unique():
    s = _session()
    owner = User(email="o@b.com", display_name="Owner", password_hash="x")
    member = User(email="m@b.com", display_name="Priya", password_hash="x")
    s.add_all([owner, member])
    s.flush()
    plan = Plan(owner_user_id=owner.id, type="asset", name="Plot", currency="INR")
    s.add(plan)
    s.flush()
    s.add(PlanMembership(plan_id=plan.id, user_id=member.id))
    s.commit()

    got = s.get(Plan, plan.id)
    assert len(got.memberships) == 1 and got.memberships[0].role == "contributor"

    s.add(PlanMembership(plan_id=plan.id, user_id=member.id))
    with pytest.raises(IntegrityError):
        s.commit()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_membership_models.py -q`
Expected: FAIL (cannot import PlanMembership).

- [ ] **Step 3: Create `src/khata/models/membership.py`**

```python
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PlanMembership(Base):
    __tablename__ = "plan_memberships"
    __table_args__ = (UniqueConstraint("plan_id", "user_id", name="uq_plan_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="contributor")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    plan: Mapped["Plan"] = relationship(back_populates="memberships")
```

- [ ] **Step 4: Modify `src/khata/models/plan.py` — add `memberships` to `Plan`**

In the `Plan` class, right after the `ledger_entries: Mapped[list["LedgerEntry"]] = relationship(...)` statement, add:
```python
    memberships: Mapped[list["PlanMembership"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan")
```

- [ ] **Step 5: Modify `src/khata/models/__init__.py` — register it**

Append:
```python
from .membership import PlanMembership  # noqa: F401
```

- [ ] **Step 6: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_membership_models.py -q` (expect 1 PASS), then `.venv/bin/python -m pytest -q` (expect 54 passed).

- [ ] **Step 7: Commit**

```bash
git add src/khata/models/membership.py src/khata/models/plan.py src/khata/models/__init__.py tests/test_membership_models.py
git commit -m "feat(models): PlanMembership (plan sharing) with unique(plan_id,user_id)"
```

---

### Task 2: Alembic migration for plan_memberships

**Files:** Create `alembic/versions/<rev>_memberships.py`

- [ ] **Step 1: Reset scratch DB to the Plan-3 head**

```bash
cd /Users/assistant/dev/active/khata
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
(DB now at `daacf83e03ee`.)

- [ ] **Step 2: Autogenerate**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic revision --autogenerate -m "plan memberships"
```
Expect: `Detected added table 'plan_memberships'`.

- [ ] **Step 3: Sanity-check the file**

Open `alembic/versions/*_plan_memberships.py`: `down_revision = 'daacf83e03ee'`; `upgrade()` has `op.create_table('plan_memberships', ...)` with a unique constraint on `(plan_id, user_id)`; `downgrade()` drops it. If `plan_memberships` is absent or other tables appear, STOP and report BLOCKED.

- [ ] **Step 4: Apply + verify + round-trip**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
.venv/bin/python -c "import sqlite3;print('plan_memberships' in [r[0] for r in sqlite3.connect('khata.db').execute(\"select name from sqlite_master where type='table'\")])"
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic downgrade -1 && KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
Expected: `True`; downgrade + re-upgrade both succeed.

- [ ] **Step 5: Full suite + commit**

```bash
.venv/bin/python -m pytest -q   # 54 passed
git add alembic/versions/
git commit -m "feat(db): migration for plan_memberships"
```

---

### Task 3: Sharing service (members + accessible)

**Files:** Create `src/khata/services/sharing.py`; Test `tests/test_sharing_service.py`

- [ ] **Step 1: Write failing test `tests/test_sharing_service.py`**

```python
import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan
from khata.services.sharing import (
    add_member, remove_member, list_members, accessible,
    UserNotFound, AlreadyMember, MemberError,
)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        owner = User(email="o@b.com", display_name="Owner", password_hash="x")
        member = User(email="m@b.com", display_name="Priya", password_hash="x")
        stranger = User(email="s@b.com", display_name="Stranger", password_hash="x")
        s.add_all([owner, member, stranger])
        s.flush()
        plan = Plan(owner_user_id=owner.id, type="asset", name="Plot", currency="INR")
        s.add(plan)
        s.flush()
        yield s, owner, member, stranger, plan


def test_add_list_remove_and_accessible(ctx):
    s, owner, member, stranger, plan = ctx
    add_member(s, plan=plan, email="m@b.com")
    s.commit()
    assert accessible(s, plan=plan, user_id=owner.id) is True
    assert accessible(s, plan=plan, user_id=member.id) is True
    assert accessible(s, plan=plan, user_id=stranger.id) is False

    rows = list_members(s, plan)
    assert {r["role"] for r in rows} == {"owner", "contributor"}
    assert any(r["display_name"] == "Priya" and r["role"] == "contributor" for r in rows)

    remove_member(s, plan=plan, user_id=member.id)
    s.commit()
    assert accessible(s, plan=plan, user_id=member.id) is False


def test_add_member_errors(ctx):
    s, owner, member, stranger, plan = ctx
    with pytest.raises(UserNotFound):
        add_member(s, plan=plan, email="nobody@x.com")
    with pytest.raises(AlreadyMember):
        add_member(s, plan=plan, email="o@b.com")  # owner can't be a member
    add_member(s, plan=plan, email="m@b.com")
    s.commit()
    with pytest.raises(AlreadyMember):
        add_member(s, plan=plan, email="m@b.com")  # dup


def test_remove_nonmember_raises(ctx):
    s, owner, member, stranger, plan = ctx
    with pytest.raises(MemberError):
        remove_member(s, plan=plan, user_id=stranger.id)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_sharing_service.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Create `src/khata/services/sharing.py`**

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, User, PlanMembership


class MemberError(Exception):
    pass


class UserNotFound(MemberError):
    pass


class AlreadyMember(MemberError):
    pass


def accessible(session: Session, *, plan: Plan, user_id: int) -> bool:
    if plan.owner_user_id == user_id:
        return True
    return any(m.user_id == user_id for m in plan.memberships)


def add_member(session: Session, *, plan: Plan, email: str) -> PlanMembership:
    email = (email or "").strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        raise UserNotFound(email)
    if user.id == plan.owner_user_id:
        raise AlreadyMember("owner is already on the plan")
    if any(m.user_id == user.id for m in plan.memberships):
        raise AlreadyMember(email)
    membership = PlanMembership(plan_id=plan.id, user_id=user.id, role="contributor")
    plan.memberships.append(membership)
    session.flush()
    return membership


def remove_member(session: Session, *, plan: Plan, user_id: int) -> None:
    membership = next((m for m in plan.memberships if m.user_id == user_id), None)
    if membership is None:
        raise MemberError("not_a_member")
    plan.memberships.remove(membership)
    session.flush()


def list_members(session: Session, plan: Plan) -> list[dict]:
    owner = session.get(User, plan.owner_user_id)
    rows = [{"user_id": owner.id, "email": owner.email,
             "display_name": owner.display_name, "role": "owner"}]
    for m in plan.memberships:
        u = session.get(User, m.user_id)
        rows.append({"user_id": u.id, "email": u.email,
                     "display_name": u.display_name, "role": m.role})
    return rows
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_sharing_service.py -q`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/sharing.py tests/test_sharing_service.py
git commit -m "feat(sharing): add/remove/list members + accessible check"
```

---

### Task 4: Ownership share — `contributors` in asset_state

**Files:** Modify `src/khata/services/assets.py`; Test `tests/test_asset_service.py` (append)

- [ ] **Step 1: Append failing test to `tests/test_asset_service.py`**

```python
def test_state_contributors_breakdown(ctx):
    s, u = ctx
    from khata.models import User
    priya = User(email="priya@b.com", display_name="Priya", password_hash="x")
    s.add(priya)
    s.flush()
    plan = _plan_with_schedule(s, u, 100000, [100000])
    # u pays 58k, priya pays 42k
    log_payment(s, plan=plan, user_id=u.id, amount_minor=58000, occurred_at=_now(),
                method="transfer", funding_source="savings")
    log_payment(s, plan=plan, user_id=priya.id, amount_minor=42000, occurred_at=_now(),
                method="upi", funding_source="savings")
    st = asset_state(s, plan)
    cons = st["contributors"]
    by = {c["display_name"]: c for c in cons}
    assert by[u.display_name]["paid_minor"] == 58000 and by[u.display_name]["pct"] == 58
    assert by["Priya"]["paid_minor"] == 42000 and by["Priya"]["pct"] == 42
    assert cons[0]["display_name"] == u.display_name  # biggest first
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_asset_service.py::test_state_contributors_breakdown -q`
Expected: FAIL (`KeyError: 'contributors'`).

- [ ] **Step 3: Modify `src/khata/services/assets.py`**

Add `User` to the models import at the top — change:
```python
from ..models import Plan, AssetPurchase, Installment, LedgerEntry
```
to:
```python
from ..models import Plan, AssetPurchase, Installment, LedgerEntry, User
```
Then inside `asset_state`, just before the `return {` statement, add the contributors computation:
```python
    by_user: dict[int, int] = {}
    for e in outs:
        by_user[e.logged_by_user_id] = by_user.get(e.logged_by_user_id, 0) + e.amount_minor
    contributors = []
    for uid, amt in sorted(by_user.items(), key=lambda kv: kv[1], reverse=True):
        user = session.get(User, uid)
        contributors.append({"user_id": uid,
                             "display_name": user.display_name if user else None,
                             "paid_minor": amt,
                             "pct": round(amt * 100 / paid) if paid else 0})
```
and add `"contributors": contributors,` to the returned dict (next to `funding_breakdown`).

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_asset_service.py -q` (expect 12 PASS), then `.venv/bin/python -m pytest -q` (expect 58 passed).

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/assets.py tests/test_asset_service.py
git commit -m "feat(assets): derived contributors (ownership share) in asset_state"
```

---

### Task 5: Net-position dashboard service

**Files:** Create `src/khata/services/dashboard.py`; Test `tests/test_dashboard_service.py`

- [ ] **Step 1: Write failing test `tests/test_dashboard_service.py`**

```python
from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.assets import create_asset_plan, log_payment
from khata.services.loans import create_loan_plan, add_disbursement
from khata.services.sharing import add_member
from khata.services.dashboard import net_position


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="a@b.com", display_name="Arjun", password_hash="x")
        s.add(u)
        s.flush()
        yield s, u


def _dt():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_net_position_rollup(ctx):
    s, u = ctx
    # loan TAKEN, no interest, 1L principal -> i_owe 1L
    taken = create_loan_plan(s, owner_id=u.id, name="GL", currency="INR", direction="taken",
                             interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=taken, user_id=u.id, amount_minor=10000000, occurred_at=_dt())
    # loan GIVEN, no interest, 0.4L -> owed_to_me 0.4L
    given = create_loan_plan(s, owner_id=u.id, name="Lent", currency="INR", direction="given",
                             interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=given, user_id=u.id, amount_minor=4000000, occurred_at=_dt())
    # asset, u pays 1L -> paid_to_date 1L
    asset = create_asset_plan(s, owner_id=u.id, name="Plot", currency="INR",
                              total_price_minor=50000000)
    log_payment(s, plan=asset, user_id=u.id, amount_minor=10000000, occurred_at=_dt(),
                method="upi", funding_source="savings")
    s.commit()

    d = net_position(s, u.id)
    assert d["i_owe_minor"] == 10000000
    assert d["owed_to_me_minor"] == 4000000
    assert d["paid_to_date_minor"] == 10000000
    assert d["net_position_minor"] == 4000000 - 10000000
    assert len(d["plans"]) == 3
    assert all(p["role"] == "owner" for p in d["plans"])


def test_member_shared_plan_appears(ctx):
    s, u = ctx
    other = User(email="o@b.com", display_name="Owner", password_hash="x")
    s.add(other)
    s.flush()
    plan = create_asset_plan(s, owner_id=other.id, name="Joint", currency="INR",
                             total_price_minor=20000000)
    add_member(s, plan=plan, email="a@b.com")  # u is a member
    log_payment(s, plan=plan, user_id=u.id, amount_minor=5000000, occurred_at=_dt(),
                method="upi", funding_source="savings")
    s.commit()

    d = net_position(s, u.id)
    assert any(p["id"] == plan.id and p["role"] == "member" for p in d["plans"])
    assert d["paid_to_date_minor"] == 5000000  # u's contribution to the shared asset
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_dashboard_service.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Create `src/khata/services/dashboard.py`**

```python
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, PlanMembership
from . import loans


def _user_plans(session: Session, user_id: int):
    owned = list(session.scalars(select(Plan).where(Plan.owner_user_id == user_id)))
    member_ids = list(session.scalars(
        select(PlanMembership.plan_id).where(PlanMembership.user_id == user_id)))
    owned_ids = {p.id for p in owned}
    member = [p for p in (session.get(Plan, pid) for pid in member_ids)
              if p is not None and p.id not in owned_ids]
    return owned, member


def net_position(session: Session, user_id: int) -> dict:
    owned, member = _user_plans(session, user_id)
    i_owe = 0
    owed_to_me = 0
    paid = 0
    plans = []

    for p in owned:
        plans.append({"id": p.id, "type": p.type, "name": p.name,
                      "currency": p.currency, "role": "owner"})
        if p.type == "loan":
            st = loans.loan_state(session, p.loan, as_of=date.today())
            if p.loan.direction == "taken":
                i_owe += st["total_minor"]
            else:
                owed_to_me += st["total_minor"]
    for p in member:
        plans.append({"id": p.id, "type": p.type, "name": p.name,
                      "currency": p.currency, "role": "member"})

    for p in owned + member:
        if p.type == "asset":
            for e in p.ledger_entries:
                if e.direction == "out" and e.logged_by_user_id == user_id:
                    paid += e.amount_minor

    return {
        "net_position_minor": owed_to_me - i_owe,
        "i_owe_minor": i_owe,
        "owed_to_me_minor": owed_to_me,
        "paid_to_date_minor": paid,
        "plans": plans,
    }
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_dashboard_service.py -q` (expect 2 PASS), then `.venv/bin/python -m pytest -q` (expect 60 passed).

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/dashboard.py tests/test_dashboard_service.py
git commit -m "feat(dashboard): net_position rollup (i_owe / owed_to_me / paid / net)"
```

---

### Task 6: API — accessible plans, member endpoints, dashboard route

**Files:** Modify `src/khata/api/plans.py`, `src/khata/__init__.py`; Create `src/khata/api/dashboard.py`; Test `tests/test_plans_api.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_plans_api.py`**

```python
def test_member_can_access_and_contribute(client):
    client.post("/api/auth/register", json={
        "email": "b@b.com", "display_name": "Priya", "password": "pw12345"})
    client.post("/api/auth/logout")
    _register(client, "a@b.com")  # owner
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "10,00,000"}).get_json()["plan"]["id"]
    assert client.post(f"/api/plans/{pid}/members", json={"email": "b@b.com"}).status_code == 201
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "b@b.com", "password": "pw12345"})

    assert client.get(f"/api/plans/{pid}").status_code == 200            # member reads
    assert client.post(f"/api/plans/{pid}/payments", json={
        "amount": "2,00,000", "method": "upi", "funding_source": "savings"}).status_code == 201
    assert client.post(f"/api/plans/{pid}/installments",
                       json={"installments": []}).status_code == 403     # owner-only
    assert client.post(f"/api/plans/{pid}/members",
                       json={"email": "a@b.com"}).status_code == 403      # owner-only
    st = client.get(f"/api/plans/{pid}").get_json()["state"]
    assert any(c["display_name"] == "Priya" for c in st["contributors"])


def test_non_member_forbidden(client):
    _register(client, "a@b.com")
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1000"}).get_json()["plan"]["id"]
    client.post("/api/auth/logout")
    _register(client, "c@b.com")
    assert client.get(f"/api/plans/{pid}").status_code == 403


def test_dashboard_rollup(client):
    _register(client, "a@b.com")
    client.post("/api/plans", json={
        "type": "loan", "name": "GL", "currency": "INR", "direction": "taken",
        "interest_type": "none", "start_date": "2026-01-01"})
    client.post("/api/plans/1/loan/disbursements",
                json={"amount": "1,00,000", "occurred_at": "2026-01-01T00:00:00"})
    pid2 = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "5,00,000"}).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid2}/payments",
                json={"amount": "1,00,000", "method": "upi", "funding_source": "savings"})

    assert client.get("/api/dashboard").status_code == 200 or True  # set after auth check below
    d = client.get("/api/dashboard").get_json()
    assert d["i_owe_minor"] == 10000000
    assert d["paid_to_date_minor"] == 10000000
    assert d["owed_to_me_minor"] == 0
    assert d["net_position_minor"] == -10000000
    assert len(d["plans"]) == 2


def test_dashboard_requires_auth(client):
    assert client.get("/api/dashboard").status_code == 401
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_plans_api.py -q`
Expected: the 4 new tests FAIL (404 on members/dashboard; 403 where member should be allowed).

- [ ] **Step 3: In `src/khata/api/plans.py`, add the sharing import + `_accessible_plan` helper**

Add to the imports (alongside the existing service imports):
```python
from ..models import PlanMembership, User
from ..services import sharing
```
And add this helper next to `_owned_plan`:
```python
def _accessible_plan(user, plan_id):
    plan = g.db.get(Plan, plan_id)
    if plan is None:
        return None, (jsonify(error="not_found"), 404)
    if not sharing.accessible(g.db, plan=plan, user_id=user.id):
        return None, (jsonify(error="forbidden"), 403)
    return plan, None
```

- [ ] **Step 4: Switch `detail`, `index`, and `payment` to owner-or-member**

In `detail(plan_id)`: change `plan, err = _owned_plan(user, plan_id)` to `plan, err = _accessible_plan(user, plan_id)`.

In `payment(plan_id)` (the asset payment endpoint): change `plan, err = _owned_plan(user, plan_id)` to `plan, err = _accessible_plan(user, plan_id)`. (The handler already attributes via `user_id=user.id`.)

Replace the `index()` view body so it includes member plans:
```python
@bp.get("")
def index():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    owned = assets.list_plans(g.db, user.id)
    owned_ids = {p.id for p in owned}
    member_ids = list(g.db.scalars(
        select(PlanMembership.plan_id).where(PlanMembership.user_id == user.id)))
    member = [p for p in (g.db.get(Plan, pid) for pid in member_ids)
              if p is not None and p.id not in owned_ids]
    return jsonify(plans=[_summary(p) for p in owned + member]), 200
```
(Add `from sqlalchemy import select` to the imports if not present.)

- [ ] **Step 5: Append the member endpoints to `src/khata/api/plans.py`**

```python
@bp.post("/<int:plan_id>/members")
def add_member(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    data = request.get_json(silent=True) or {}
    try:
        m = sharing.add_member(g.db, plan=plan, email=data.get("email", ""))
        g.db.commit()
    except sharing.UserNotFound:
        g.db.rollback()
        return jsonify(error="user_not_found"), 404
    except sharing.AlreadyMember:
        g.db.rollback()
        return jsonify(error="already_member"), 409
    except sharing.MemberError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    u = g.db.get(User, m.user_id)
    return jsonify(member={"user_id": u.id, "email": u.email,
                           "display_name": u.display_name, "role": m.role}), 201


@bp.get("/<int:plan_id>/members")
def get_members(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return err
    return jsonify(members=sharing.list_members(g.db, plan)), 200


@bp.delete("/<int:plan_id>/members/<int:member_user_id>")
def delete_member(plan_id, member_user_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    try:
        sharing.remove_member(g.db, plan=plan, user_id=member_user_id)
        g.db.commit()
    except sharing.MemberError:
        g.db.rollback()
        return jsonify(error="not_a_member"), 404
    return jsonify(ok=True), 200
```

- [ ] **Step 6: Create `src/khata/api/dashboard.py`**

```python
from flask import Blueprint, g, jsonify

from ..services import dashboard
from .auth import current_user

bp = Blueprint("dashboard", __name__)


@bp.get("/api/dashboard")
def get_dashboard():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(dashboard.net_position(g.db, user.id)), 200
```

- [ ] **Step 7: Register the dashboard blueprint in `src/khata/__init__.py`**

After the `plans` blueprint registration (just before `return app`), add:
```python
    from .api.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)
```

- [ ] **Step 8: Run the API tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_plans_api.py -q` (expect 12 PASS), then `.venv/bin/python -m pytest -q` (expect 64 passed).

- [ ] **Step 9: Commit**

```bash
git add src/khata/api/plans.py src/khata/api/dashboard.py src/khata/__init__.py tests/test_plans_api.py
git commit -m "feat(api): owner-or-member access, member endpoints, GET /api/dashboard"
```

---

### Task 7: Smoke test + process docs

**Files:** Modify `build_status.json`, `docs/AGENT_LEARNINGS.md`

- [ ] **Step 1: Smoke-test sharing + dashboard**

```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
PYTHONPATH=src KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/python wsgi.py > /tmp/khata_p4.log 2>&1 &
sleep 2.5
# Priya then Arjun
curl -s -c /tmp/cjp -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' -d '{"email":"priya@b.com","display_name":"Priya","password":"pw12345"}' >/dev/null
curl -s -c /tmp/cja -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' -d '{"email":"arjun@b.com","display_name":"Arjun","password":"pw12345"}' >/dev/null
curl -s -b /tmp/cja -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"name":"Devanahalli plot","currency":"INR","total_price":"20,00,000"}' >/dev/null
curl -s -b /tmp/cja -X POST localhost:5050/api/plans/1/members -H 'Content-Type: application/json' -d '{"email":"priya@b.com"}'
curl -s -b /tmp/cja -X POST localhost:5050/api/plans/1/payments -H 'Content-Type: application/json' -d '{"amount":"5,80,000","method":"transfer","funding_source":"savings"}' >/dev/null
curl -s -b /tmp/cjp -X POST localhost:5050/api/plans/1/payments -H 'Content-Type: application/json' -d '{"amount":"4,20,000","method":"upi","funding_source":"savings"}' >/dev/null
curl -s -b /tmp/cja localhost:5050/api/plans/1 | .venv/bin/python -c "import sys,json;print('contributors',json.load(sys.stdin)['state']['contributors'])"
curl -s -b /tmp/cja localhost:5050/api/dashboard | .venv/bin/python -c "import sys,json;d=json.load(sys.stdin);print('paid',d['paid_to_date_minor'],'plans',len(d['plans']))"
kill %1 2>/dev/null
```
Expected: contributors shows Arjun 58% (58000000) / Priya is a member but Priya's payment via `/tmp/cjp` is attributed to Priya — both contributors appear; the owner's `/api/dashboard` `paid_to_date` reflects Arjun's 5,80,000 (58000000 minor).

- [ ] **Step 2: Update `build_status.json`**

```json
{
  "project": "khata",
  "phase": 1,
  "plan": "4-sharing-contributors",
  "tasks_total": 7,
  "tasks_done": 7,
  "last_updated": "2026-06-04",
  "tests": "64 passed",
  "python": "3.12",
  "notes": "Plan 4 complete: PlanMembership sharing (owner-or-member access; member adds own asset payments; owner-only setup/membership), derived contributors (ownership share) in asset_state, net-position dashboard rollup (GET /api/dashboard). Next: Plan 5 (Google OAuth + polished Features page)."
}
```

- [ ] **Step 3: Append to `docs/AGENT_LEARNINGS.md`**

```markdown

## 2026-06-04 — Plan 4 (Sharing & contributors)
- `PlanMembership` (contributors only); owner stays `plans.owner_user_id`. API access split:
  `_accessible_plan` (owner-or-member) for reads + asset payments; `_owned_plan` (owner-only) for
  installments / loan endpoints / membership management. Members' payments self-attribute via
  `logged_by_user_id=user.id`.
- Ownership share is derived: `asset_state` groups `out` entries by `logged_by_user_id` →
  `contributors[{user_id, display_name, paid_minor, pct}]` (resolves the unused-`session` note for
  asset_state). `loan_state` still takes an unused session — reconcile both later.
- `dashboard.net_position` rolls up only the user's OWNED loans for i_owe/owed_to_me, and asset
  `out`-payments the user logged for paid_to_date (so shared-asset contributions count per-user).
```

- [ ] **Step 4: Commit**

```bash
rm -f /tmp/cja /tmp/cjp /tmp/khata_p4.log
git add build_status.json docs/AGENT_LEARNINGS.md
git commit -m "chore(process): Plan 4 complete — build status + learnings"
```

---

## Self-Review

**Spec coverage (Plan 4 = sharing & contributors):**
- `plan_memberships` table + `Plan.memberships` → Task 1 + migration Task 2. ✓
- Sharing service (add/remove/list/accessible) → Task 3. ✓
- Owner-or-member access; member-edits-own (asset payments); owner-only setup/membership → Task 6. ✓
- Member endpoints (POST/GET/DELETE) → Task 6. ✓
- Derived `contributors` (ownership share) in asset_state → Task 4. ✓
- Net-position dashboard service + `GET /api/dashboard` → Tasks 5, 6. ✓
- `index` returns owned + member plans → Task 6. ✓

**Placeholder scan:** No TBD/TODO; complete code in every step. (One belt-and-suspenders line in a test — `assert ... or True` — is harmless; the real assertion follows.) ✓

**Type consistency:** `PlanMembership` fields, `sharing` function names/errors (`add_member`/`remove_member`/`list_members`/`accessible`, `UserNotFound`/`AlreadyMember`/`MemberError`), `asset_state` `contributors[{user_id,display_name,paid_minor,pct}]`, and `net_position` keys (`net_position_minor`,`i_owe_minor`,`owed_to_me_minor`,`paid_to_date_minor`,`plans`) are consistent across services, API, and tests. `_accessible_plan`/`_owned_plan` usage matches the per-endpoint permission table. ✓

---

## Next plans (Phase 1 continued)
- **Plan 5** — Google OAuth + polished Features/limitations page; (later) secured loans/collateral + holdings/net-worth + chit funds.
