# Khata Phase 4 · Plan 4.1 — Chit Funds Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8) per task; done-gate = real end-to-end. **Money logic → full dual review (spec + quality) on Tasks 2–3.** Do NOT touch `build_status.json`.

**Goal:** A `chit` plan type tracking the user's auction-chit participation (contribution/dividend/prize cashflows) with derived net position + a pure dividend calculator, plus a `chit-detail` UI. Builds on the plan/ledger spine.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy, Alembic, pytest, vanilla-JS.

---

### Task 1: Chit model + migration

**Files:** Create `src/khata/models/chit.py`; Modify `src/khata/models/plan.py`, `src/khata/models/__init__.py`; Create `alembic/versions/<rev>_chits.py`; Test `tests/test_chit_models.py`

- [ ] **Step 1: Write failing test `tests/test_chit_models.py`**
```python
from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, Chit, LedgerEntry


def _s():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    return make_session_factory(e)()


def test_chit_persists_and_cascade():
    s = _s()
    u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
    p = Plan(owner_user_id=u.id, type="chit", name="20mo chit", currency="INR"); s.add(p); s.flush()
    s.add(Chit(plan_id=p.id, chit_value_minor=100000000, n_members=20, commission_bps=500,
               start_date=__import__("datetime").date(2026, 1, 1)))
    from datetime import datetime, timezone
    s.add(LedgerEntry(plan_id=p.id, logged_by_user_id=u.id, kind="chit_contribution", direction="out",
                      amount_minor=500000, currency="INR", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    s.commit()
    got = s.get(Plan, p.id)
    assert got.chit.n_members == 20 and got.chit.commission_bps == 500
    assert got.ledger_entries[0].kind == "chit_contribution"
    pid = p.id; s.delete(s.get(Plan, pid)); s.commit()
    assert s.get(Chit, pid) is None
```

- [ ] **Step 2: Run → FAIL** (cannot import Chit).

- [ ] **Step 3: Create `src/khata/models/chit.py`**
```python
from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Chit(Base):
    __tablename__ = "chits"

    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    chit_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    n_members: Mapped[int] = mapped_column(Integer, nullable=False)
    commission_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)

    plan: Mapped["Plan"] = relationship(back_populates="chit")
```

- [ ] **Step 4: `src/khata/models/plan.py`** — after the `holding` relationship, add:
```python
    chit: Mapped["Chit | None"] = relationship(
        back_populates="plan", uselist=False, cascade="all, delete-orphan")
```

- [ ] **Step 5: `src/khata/models/__init__.py`** — append `from .chit import Chit  # noqa: F401`.

- [ ] **Step 6: Migration** (free port; reset scratch DB to current head, autogenerate):
```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic revision --autogenerate -m "chits"
```
Confirm the new file: `down_revision = '26b0e2444049'`; `upgrade()` creates ONLY `chits` (plan_id PK/FK
CASCADE, chit_value_minor, n_members, commission_bps, start_date); `downgrade()` drops it. If any other
table appears, STOP/trim. Apply + round-trip:
```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic downgrade -1 && KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
rm -f khata.db khata.db-wal khata.db-shm
```

- [ ] **Step 7: Run + full suite** — `pytest tests/test_chit_models.py -q`, then `pytest -q` (expect 119 — 118 + 1).

- [ ] **Step 8: Commit**
```bash
git add src/khata/models/chit.py src/khata/models/plan.py src/khata/models/__init__.py alembic/versions/ tests/test_chit_models.py
git commit -m "feat(models+db): Chit plan type + chits table migration

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Chit service (net math + dividend calculator)  ⟶ FULL DUAL REVIEW (money)

**Files:** Create `src/khata/services/chits.py`; Test `tests/test_chit_service.py`

- [ ] **Step 1: Write failing test `tests/test_chit_service.py`**
```python
from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.chits import (create_chit_plan, log_chit_entry, chit_state,
                                  auction_dividend, ChitError, ValidationError)


@pytest.fixture
def ctx():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    S = make_session_factory(e)
    with S() as s:
        u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
        yield s, u


def _dt(d=1): return datetime(2026, 1, d, tzinfo=timezone.utc)


def _chit(s, u):
    return create_chit_plan(s, owner_id=u.id, name="C", currency="INR",
                            chit_value_minor=100000000, n_members=20, commission_bps=500,
                            start_date=date(2026, 1, 1))


def test_subscription_and_net(ctx):
    s, u = ctx
    p = _chit(s, u)
    # chit value 10,00,000 over 20 members → subscription 50,000 (5000000 minor)
    log_chit_entry(s, plan=p, user_id=u.id, kind="chit_contribution", amount_minor=5000000, occurred_at=_dt(1))
    log_chit_entry(s, plan=p, user_id=u.id, kind="chit_dividend", amount_minor=200000, occurred_at=_dt(1))
    s.commit()
    st = chit_state(s, p.chit)
    assert st["subscription_minor"] == 5000000
    assert st["total_contributed_minor"] == 5000000
    assert st["total_dividends_minor"] == 200000
    assert st["net_contributed_minor"] == 4800000
    assert st["net_position_minor"] == 200000 - 5000000
    assert st["won"] is False


def test_win_makes_net_positive(ctx):
    s, u = ctx
    p = _chit(s, u)
    log_chit_entry(s, plan=p, user_id=u.id, kind="chit_contribution", amount_minor=5000000, occurred_at=_dt(1))
    log_chit_entry(s, plan=p, user_id=u.id, kind="chit_prize", amount_minor=92000000, occurred_at=_dt(2))
    s.commit()
    st = chit_state(s, p.chit)
    assert st["prize_received_minor"] == 92000000
    assert st["won"] is True
    assert st["net_position_minor"] == 92000000 - 5000000


def test_auction_dividend_math():
    # chit value 10,00,000; commission 5% = 50,000; winning bid 1,00,000
    d = auction_dividend(chit_value_minor=100000000, commission_bps=500, n_members=20,
                         winning_bid_minor=10000000)
    assert d["commission_minor"] == 5000000           # 50,000
    assert d["dividend_pool_minor"] == 5000000         # bid 1,00,000 − commission 50,000
    assert d["dividend_per_member_minor"] == 250000    # / 20 = 2,500
    assert d["prize_minor"] == 90000000                # chit value − bid = 9,00,000


def test_validation(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_chit_plan(s, owner_id=u.id, name="C", currency="INR", chit_value_minor=100000000,
                         n_members=1, commission_bps=0, start_date=date(2026, 1, 1))  # n<2
    p = _chit(s, u)
    with pytest.raises(ValidationError):
        log_chit_entry(s, plan=p, user_id=u.id, kind="bogus", amount_minor=1, occurred_at=_dt(1))
```

- [ ] **Step 2: Run → FAIL** (module not found).

- [ ] **Step 3: Create `src/khata/services/chits.py`**
```python
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from ..models import Plan, Chit, LedgerEntry
from ..money import SUPPORTED_CURRENCIES

CHIT_KINDS = {"chit_contribution", "chit_dividend", "chit_prize"}


class ChitError(Exception):
    pass


class ValidationError(ChitError):
    pass


def _round(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def create_chit_plan(session: Session, *, owner_id, name, currency, chit_value_minor, n_members,
                     commission_bps, start_date) -> Plan:
    if (currency or "").upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {currency!r}")
    if n_members < 2:
        raise ValidationError("n_members must be >= 2")
    if chit_value_minor <= 0:
        raise ValidationError("chit_value must be > 0")
    if not (0 <= commission_bps <= 10000):
        raise ValidationError("commission_bps must be 0..10000")
    plan = Plan(owner_user_id=owner_id, type="chit",
                name=(name or "").strip() or "Untitled chit", currency=currency.upper(), status="active")
    session.add(plan)
    session.flush()
    session.add(Chit(plan_id=plan.id, chit_value_minor=chit_value_minor, n_members=n_members,
                     commission_bps=commission_bps, start_date=start_date))
    session.flush()
    return plan


def log_chit_entry(session: Session, *, plan: Plan, user_id, kind, amount_minor, occurred_at, note=None) -> LedgerEntry:
    if kind not in CHIT_KINDS:
        raise ValidationError(f"unknown chit kind: {kind}")
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    direction = "out" if kind == "chit_contribution" else "in"
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, kind=kind, direction=direction,
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at, note=note)
    plan.ledger_entries.append(entry)
    session.flush()
    return entry


def auction_dividend(*, chit_value_minor, commission_bps, n_members, winning_bid_minor) -> dict:
    commission = _round(Decimal(chit_value_minor) * commission_bps / 10000)
    pool = max(0, winning_bid_minor - commission)
    per_member = _round(Decimal(pool) / n_members) if n_members else 0
    return {"commission_minor": commission, "dividend_pool_minor": pool,
            "dividend_per_member_minor": per_member, "prize_minor": chit_value_minor - winning_bid_minor}


def chit_state(session: Session, chit: Chit) -> dict:
    plan = chit.plan
    def total(kind): return sum(e.amount_minor for e in plan.ledger_entries if e.kind == kind)
    contributed = total("chit_contribution")
    dividends = total("chit_dividend")
    prize = total("chit_prize")
    subscription = _round(Decimal(chit.chit_value_minor) / chit.n_members) if chit.n_members else 0
    months_recorded = sum(1 for e in plan.ledger_entries if e.kind == "chit_contribution")
    ledger = [{"kind": e.kind, "direction": e.direction, "amount_minor": e.amount_minor,
               "occurred_at": e.occurred_at.isoformat(), "note": e.note}
              for e in plan.ledger_entries if e.kind in CHIT_KINDS]
    return {
        "currency": plan.currency, "chit_value_minor": chit.chit_value_minor,
        "n_members": chit.n_members, "commission_bps": chit.commission_bps,
        "subscription_minor": subscription,
        "total_contributed_minor": contributed, "total_dividends_minor": dividends,
        "prize_received_minor": prize, "net_contributed_minor": contributed - dividends,
        "net_position_minor": prize + dividends - contributed, "won": prize > 0,
        "months_recorded": months_recorded, "ledger": ledger,
    }
```

- [ ] **Step 4: Run + full suite** — `pytest tests/test_chit_service.py -q` (4 pass), then `pytest -q` (expect 123 — 119 + 4).

- [ ] **Step 5: Commit**
```bash
git add src/khata/services/chits.py tests/test_chit_service.py
git commit -m "feat(chits): net-position state + auction dividend calculator (Decimal, derived)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: API — chit dispatch + entries + dividend endpoints  ⟶ FULL DUAL REVIEW

**Files:** Modify `src/khata/api/plans.py`; Test `tests/test_chits_api.py`

- [ ] **Step 1: Write failing test `tests/test_chits_api.py`** (mirror `test_holdings_api.py` fixture):
```python
import pytest
from khata import create_app
from khata.config import Config
from khata.db import Base


@pytest.fixture
def client():
    cfg = Config(); cfg.database_url = "sqlite:///:memory:"
    app = create_app(cfg); app.config["TESTING"] = True
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def _reg(c): return c.post("/api/auth/register", json={"email": "a@b.com", "display_name": "A", "password": "pw12345"})


def _mk(c):
    return c.post("/api/plans", json={"type": "chit", "name": "C", "currency": "INR",
                  "chit_value": "10,00,000", "n_members": 20, "commission": "5", "start_date": "2026-01-01"})


def test_create_chit_and_state(client):
    _reg(client); r = _mk(client)
    assert r.status_code == 201
    b = r.get_json(); assert b["plan"]["type"] == "chit"; assert b["state"]["subscription_minor"] == 5000000


def test_chit_entry_and_dividend(client):
    _reg(client); pid = _mk(client).get_json()["plan"]["id"]
    assert client.post(f"/api/plans/{pid}/chit/entries", json={"kind": "chit_contribution", "amount": "50,000"}).status_code == 201
    d = client.get(f"/api/plans/{pid}/chit/dividend?bid=1,00,000").get_json()
    assert d["dividend_per_member_minor"] == 250000 and d["prize_minor"] == 90000000
    st = client.get(f"/api/plans/{pid}").get_json()["state"]
    assert st["total_contributed_minor"] == 5000000


def test_chit_auth(client):
    assert client.post("/api/plans/1/chit/entries", json={}).status_code == 401
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Wire `src/khata/api/plans.py`** — import `chits` + `ChitError`; `_summary` chit branch (`chit_value_minor,n_members,commission_bps`); `_detail` dispatch `chits.chit_state(g.db, plan.chit)`; `create()` `elif ptype == "chit"` → `chits.create_chit_plan(... chit_value_minor=to_minor(data.get("chit_value",""),currency), n_members=int(data.get("n_members",0)), commission_bps=pct_to_bps(data.get("commission","0")), start_date=date.fromisoformat(...))`; add `ChitError` to the create except tuple. Add endpoints:
```python
@bp.post("/<int:plan_id>/chit/entries")
def chit_entry(plan_id):
    user = current_user()
    if user is None: return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err: return err
    if plan.type != "chit": return jsonify(error="not_a_chit"), 400
    data = request.get_json(silent=True) or {}
    try:
        entry = chits.log_chit_entry(g.db, plan=plan, user_id=user.id, kind=data.get("kind", ""),
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"))
        g.db.commit()
    except (ChitError, ValueError, TypeError) as e:
        g.db.rollback(); return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan), state=chits.chit_state(g.db, plan.chit)), 201


@bp.get("/<int:plan_id>/chit/dividend")
def chit_dividend(plan_id):
    user = current_user()
    if user is None: return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err: return err
    if plan.type != "chit": return jsonify(error="not_a_chit"), 400
    try:
        bid = to_minor(request.args.get("bid", ""), plan.currency)
    except (ValueError, TypeError) as e:
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(chits.auction_dividend(chit_value_minor=plan.chit.chit_value_minor,
        commission_bps=plan.chit.commission_bps, n_members=plan.chit.n_members, winning_bid_minor=bid)), 200
```

- [ ] **Step 4: Run + full suite** — `pytest tests/test_chits_api.py -q` (3), then `pytest -q` (expect 126 — 123 + 3).

- [ ] **Step 5: Commit** `feat(api): chit create dispatch + /chit/entries + /chit/dividend`.

---

### Task 4: Chit detail UI + create tab + route

**Files:** Create `src/khata/static/chit-detail.html`; Modify `src/khata/web.py`, `src/khata/static/create-plan.html`, `src/khata/static/app.html`; Test `tests/test_web.py`

- [ ] Add `/chit/<int:plan_id>` route. Build `chit-detail.html` (cards: net position / prize received / net contributed; status line: subscription · months_recorded/n_members · won; a **dividend calculator** input → `GET /chit/dividend?bid=`; an entry modal: kind ∈ {contribution,dividend,prize} + amount; the chit ledger list; `sharing.js`). Add a **Chit** tab to `create-plan.html` (`chit_value`, `n_members`, `commission %`, `start_date` → `{type:"chit",…}`). Add a "Chit funds" filter chip + `ct-chit` count to `app.html`. Test: `/chit/1` 200 + markers (`/chit/entries`, `/chit/dividend`, `sharing.js`, `ledger.css`). All DOM via createElement (K4). Done-gate: create a chit via the create payload, log a contribution, GET `/chit/1` 200, dividend endpoint returns the right numbers. Full suite +1 web test. Commit.

---

### Task 5: Smoke + docs
- [ ] End-to-end smoke (create chit → entry → dividend → state). Append 4.1 learnings. Flip 4.1 boxes in Progress.md + ROADMAP.md. Commit (orchestrator updates build_status.json).

---

## Self-Review
Chit model = participant-cashflow (chosen tractable model). `chit_state` net math + `auction_dividend` calculator both Decimal/derived. API dispatch adds chit to asset|loan|holding|chit. Tests chain 118→119→123→126(+UI). Money logic gets full dual review (Tasks 2–3). ✓

## Next
4.2 Secured loans / collateral.
