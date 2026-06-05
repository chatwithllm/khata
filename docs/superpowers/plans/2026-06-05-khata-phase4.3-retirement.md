# Khata Phase 4 · Plan 4.3 — Retirement / 401(k) Planner Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8) per task; done-gate = real end-to-end. **Compound-projection math → DUAL REVIEW on Task 2.** Do NOT touch `build_status.json`, `khata_live.db*`, `OD_khata_mockup/`.

**Goal:** A `retirement` plan type — a compound-growth projection of a corpus (balance + contributions + employer match, at an assumed return, discounted by inflation). Backend + UI.

---

### Task 1: Retirement model + migration

**Files:** Create `src/khata/models/retirement.py`; Modify `src/khata/models/plan.py`, `src/khata/models/__init__.py`; Create `alembic/versions/<rev>_retirements.py`; Test `tests/test_retirement_models.py`

- [ ] **Step 1: Write `tests/test_retirement_models.py`**
```python
from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, Retirement


def _s():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    return make_session_factory(e)()


def test_retirement_persists_and_cascade():
    s = _s()
    u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
    p = Plan(owner_user_id=u.id, type="retirement", name="401k", currency="INR"); s.add(p); s.flush()
    s.add(Retirement(plan_id=p.id, current_balance_minor=2500000, monthly_contribution_minor=1000000,
                     employer_match_bps=5000, annual_return_bps=800, inflation_bps=600,
                     current_age=30, retirement_age=60))
    s.commit()
    got = s.get(Plan, p.id).retirement
    assert got.retirement_age == 60 and got.employer_match_bps == 5000
    pid = p.id; s.delete(s.get(Plan, pid)); s.commit()
    assert s.get(Retirement, pid) is None
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Create `src/khata/models/retirement.py`**
```python
from sqlalchemy import BigInteger, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Retirement(Base):
    __tablename__ = "retirements"

    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    current_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    monthly_contribution_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    employer_match_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    annual_return_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    inflation_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    current_age: Mapped[int] = mapped_column(Integer, nullable=False)
    retirement_age: Mapped[int] = mapped_column(Integer, nullable=False)

    plan: Mapped["Plan"] = relationship(back_populates="retirement")
```

- [ ] **Step 4: `src/khata/models/plan.py`** — after the `chit` relationship add:
```python
    retirement: Mapped["Retirement | None"] = relationship(
        back_populates="plan", uselist=False, cascade="all, delete-orphan")
```

- [ ] **Step 5: `src/khata/models/__init__.py`** — append `from .retirement import Retirement  # noqa: F401`.

- [ ] **Step 6: Migration**:
```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic revision --autogenerate -m "retirements"
```
Confirm: `down_revision = '609c94a2ee5f'` (loan-collateral head); `upgrade()` creates ONLY `retirements`;
`downgrade()` drops it. Apply + round-trip; `rm -f khata.db*`.

- [ ] **Step 7: Full suite** — `pytest -q` (expect 143 — 142 + 1).

- [ ] **Step 8: Commit** `feat(models+db): Retirement plan type + retirements table`.

---

### Task 2: Retirement service (compound projection)  ⟶ DUAL REVIEW

**Files:** Create `src/khata/services/retirement.py`; Test `tests/test_retirement_service.py`

- [ ] **Step 1: Write `tests/test_retirement_service.py`** (exact constants pre-computed with Decimal):
```python
import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.retirement import (create_retirement_plan, update_retirement,
                                       retirement_state, RetirementError, ValidationError)


@pytest.fixture
def ctx():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    S = make_session_factory(e)
    with S() as s:
        u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
        yield s, u


def test_zero_return_is_balance_plus_contributions(ctx):
    s, u = ctx
    # balance 10,000 + 5,000/mo for 12yr (n=144) at 0% return, 0% inflation, no match
    p = create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
        current_balance_minor=1000000, monthly_contribution_minor=500000, employer_match_bps=0,
        annual_return_bps=0, inflation_bps=0, current_age=48, retirement_age=60)
    s.commit()
    st = retirement_state(s, p.retirement)
    assert st["months_to_retirement"] == 144
    assert st["effective_monthly_minor"] == 500000
    assert st["total_contributions_minor"] == 72000000          # 5000 × 144
    assert st["projected_corpus_minor"] == 73000000             # 10000 + 72000
    assert st["projected_corpus_real_minor"] == 73000000        # 0% inflation


def test_already_at_retirement_age_is_current_balance(ctx):
    s, u = ctx
    p = create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
        current_balance_minor=2500000, monthly_contribution_minor=1000000, employer_match_bps=0,
        annual_return_bps=800, inflation_bps=600, current_age=60, retirement_age=60)
    s.commit()
    st = retirement_state(s, p.retirement)
    assert st["months_to_retirement"] == 0
    assert st["projected_corpus_minor"] == 2500000             # n=0 → just the balance


def test_compound_projection_8pct(ctx):
    s, u = ctx
    # 10,000/mo, 8% return, 6% inflation, 30→60 (n=360), no match, no starting balance
    p = create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
        current_balance_minor=0, monthly_contribution_minor=1000000, employer_match_bps=0,
        annual_return_bps=800, inflation_bps=600, current_age=30, retirement_age=60)
    s.commit()
    st = retirement_state(s, p.retirement)
    assert st["projected_corpus_minor"] == 1490359449          # nominal
    assert st["projected_corpus_real_minor"] == 247462156      # today's money (< nominal)


def test_employer_match_increases_effective(ctx):
    s, u = ctx
    p = create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
        current_balance_minor=0, monthly_contribution_minor=1000000, employer_match_bps=5000,
        annual_return_bps=0, inflation_bps=0, current_age=59, retirement_age=60)
    s.commit()
    st = retirement_state(s, p.retirement)
    assert st["effective_monthly_minor"] == 1500000            # 10000 × 1.5
    assert st["projected_corpus_minor"] == 18000000            # 15000 × 12


def test_validation_and_update(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
            current_age=60, retirement_age=50)                 # retirement < current
    p = create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
        current_balance_minor=0, monthly_contribution_minor=1000000, annual_return_bps=0,
        inflation_bps=0, current_age=50, retirement_age=60)
    update_retirement(s, plan=p, monthly_contribution_minor=2000000)
    s.commit()
    assert retirement_state(s, p.retirement)["projected_corpus_minor"] == 2000000 * 120  # 20000 × 120mo
```

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Create `src/khata/services/retirement.py`**
```python
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from ..models import Plan, Retirement
from ..money import SUPPORTED_CURRENCIES

SETTABLE = ("current_balance_minor", "monthly_contribution_minor", "employer_match_bps",
            "annual_return_bps", "inflation_bps", "current_age", "retirement_age")


class RetirementError(Exception):
    pass


class ValidationError(RetirementError):
    pass


def _round(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _validate(*, current_balance_minor, monthly_contribution_minor, employer_match_bps,
              annual_return_bps, inflation_bps, current_age, retirement_age):
    if current_age < 0 or retirement_age < current_age:
        raise ValidationError("retirement_age must be >= current_age >= 0")
    if current_balance_minor < 0 or monthly_contribution_minor < 0:
        raise ValidationError("amounts must be >= 0")
    if employer_match_bps < 0 or annual_return_bps < 0 or inflation_bps < 0:
        raise ValidationError("rates must be >= 0")


def create_retirement_plan(session: Session, *, owner_id, name, currency, current_age, retirement_age,
                           current_balance_minor=0, monthly_contribution_minor=0, employer_match_bps=0,
                           annual_return_bps=800, inflation_bps=600) -> Plan:
    if (currency or "").upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {currency!r}")
    _validate(current_balance_minor=current_balance_minor,
              monthly_contribution_minor=monthly_contribution_minor, employer_match_bps=employer_match_bps,
              annual_return_bps=annual_return_bps, inflation_bps=inflation_bps,
              current_age=current_age, retirement_age=retirement_age)
    plan = Plan(owner_user_id=owner_id, type="retirement",
                name=(name or "").strip() or "Retirement", currency=currency.upper(), status="active")
    session.add(plan)
    session.flush()
    session.add(Retirement(plan_id=plan.id, current_balance_minor=current_balance_minor,
                monthly_contribution_minor=monthly_contribution_minor, employer_match_bps=employer_match_bps,
                annual_return_bps=annual_return_bps, inflation_bps=inflation_bps,
                current_age=current_age, retirement_age=retirement_age))
    session.flush()
    return plan


def update_retirement(session: Session, *, plan: Plan, **fields) -> Retirement:
    r = plan.retirement
    merged = {k: getattr(r, k) for k in SETTABLE}
    for k, v in fields.items():
        if k in SETTABLE and v is not None:
            merged[k] = v
    _validate(**merged)
    for k, v in merged.items():
        setattr(r, k, v)
    session.flush()
    return r


def retirement_state(session: Session, retirement: Retirement) -> dict:
    r = retirement
    n = max(0, r.retirement_age - r.current_age) * 12
    mr = Decimal(r.annual_return_bps) / 120000
    im = Decimal(r.inflation_bps) / 120000
    eff = Decimal(r.monthly_contribution_minor) * (1 + Decimal(r.employer_match_bps) / 10000)
    g = Decimal(1) + mr
    gn = g ** n
    fv_current = Decimal(r.current_balance_minor) * gn
    annuity = ((gn - 1) / mr) if mr > 0 else Decimal(n)
    fv_contrib = eff * annuity
    proj = fv_current + fv_contrib
    infl = (Decimal(1) + im) ** n
    return {
        "currency": r.plan.currency,
        "current_balance_minor": r.current_balance_minor,
        "monthly_contribution_minor": r.monthly_contribution_minor,
        "employer_match_bps": r.employer_match_bps, "annual_return_bps": r.annual_return_bps,
        "inflation_bps": r.inflation_bps, "current_age": r.current_age, "retirement_age": r.retirement_age,
        "months_to_retirement": n, "effective_monthly_minor": _round(eff),
        "total_contributions_minor": _round(eff * n),
        "projected_corpus_minor": _round(proj),
        "projected_corpus_real_minor": _round(proj / infl),
    }
```

- [ ] **Step 4: Full suite** — `pytest tests/test_retirement_service.py -q` (5), then `pytest -q` (expect 148 — 143 + 5).

- [ ] **Step 5: Commit** `feat(retirement): compound corpus projection (Decimal**int, nominal + real)`.

---

### Task 3: API — retirement dispatch + /retirement/update

**Files:** Modify `src/khata/api/plans.py`; Test `tests/test_retirement_api.py`

- [ ] Wire: import `retirement` service + `RetirementError`; `_summary` retirement branch
  (`current_age, retirement_age`); `_detail` dispatch `retirement.retirement_state(g.db, plan.retirement)`;
  `create()` `elif ptype == "retirement"` →
  `retirement.create_retirement_plan(g.db, owner_id=user.id, name=…, currency=currency,
  current_age=int(data.get("current_age",0)), retirement_age=int(data.get("retirement_age",0)),
  current_balance_minor=to_minor(data.get("current_balance","0"),currency),
  monthly_contribution_minor=to_minor(data.get("monthly_contribution","0"),currency),
  employer_match_bps=pct_to_bps(data.get("employer_match","0")),
  annual_return_bps=pct_to_bps(data.get("annual_return","8")),
  inflation_bps=pct_to_bps(data.get("inflation","6")))`; add `RetirementError` to the create except tuple.
  Add endpoint:
```python
@bp.post("/<int:plan_id>/retirement/update")
def retirement_update(plan_id):
    user = current_user()
    if user is None: return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err: return err
    if plan.type != "retirement": return jsonify(error="not_a_retirement"), 400
    data = request.get_json(silent=True) or {}
    fields = {}
    for src, dst, conv in [("current_balance", "current_balance_minor", lambda v: to_minor(v, plan.currency)),
                           ("monthly_contribution", "monthly_contribution_minor", lambda v: to_minor(v, plan.currency)),
                           ("employer_match", "employer_match_bps", pct_to_bps),
                           ("annual_return", "annual_return_bps", pct_to_bps),
                           ("inflation", "inflation_bps", pct_to_bps),
                           ("current_age", "current_age", int), ("retirement_age", "retirement_age", int)]:
        if data.get(src) not in (None, ""):
            fields[dst] = conv(data.get(src))
    try:
        retirement.update_retirement(g.db, plan=plan, **fields)
        g.db.commit()
    except (RetirementError, ValueError, TypeError) as e:
        g.db.rollback(); return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(state=retirement.retirement_state(g.db, plan.retirement)), 200
```
- [ ] Tests (`tests/test_retirement_api.py`, mirror holdings-api fixture): create retirement (current_age 30, retirement_age 60, monthly_contribution "10,000", annual_return "8", inflation "6") → 201, state projected_corpus_minor 1490359449; `/retirement/update {monthly_contribution:"20,000"}` → 200 state changes; auth 401 / ownership 403; other types still create. Full suite green. Commit `feat(api): retirement create dispatch + /retirement/update`.

---

### Task 4: UI — retirement-detail + create tab + route

**Files:** Create `src/khata/static/retirement-detail.html`; Modify `src/khata/web.py`, `src/khata/static/create-plan.html`, `src/khata/static/app.html`; Test `tests/test_web.py`

- [ ] `/retirement/<int:plan_id>` route. `retirement-detail.html` (modeled on holding-detail.html):
  cards **Projected corpus** (projected_corpus_minor) · **In today's money** (projected_corpus_real_minor) ·
  **Years to retirement** (months_to_retirement/12); assumptions status line (balance · contribution ·
  match% = employer_match_bps/100 · return% = annual_return_bps/100 · inflation% = inflation_bps/100); an
  **Update** modal (current_balance, monthly_contribution, employer_match %, annual_return %, inflation %,
  current_age, retirement_age) → `POST /retirement/update` → reload; `#sharing` + sharing.js. All
  createElement (K4); auth guard 401→/, non-retirement→/app. Add a **Retirement** tab to
  `create-plan.html` (same fields → `{type:"retirement",…}`) and a Retirement chip+count to `app.html`.
  Test: `/retirement/1` 200 + `/retirement/update`, `ledger.css`, `sharing.js`. Done-gate: create a
  retirement via the create payload, GET /retirement/1 200, projected corpus present. Commit
  `feat(web): retirement planner page + create tab`.

---

### Task 5: Smoke + docs
- [ ] End-to-end smoke (create retirement → projected corpus 1490359449 → update → changes). Append 4.3
  learnings (note **Phase 4 complete**). Flip 4.3 box + mark Phase 4 done in Progress.md + ROADMAP.md.
  Commit (orchestrator owns build_status.json).

---

## Self-Review
Projection = FV of balance + employer-matched-contribution annuity, monthly compound, Decimal**int
(exact, no float, no roots); real = nominal ÷ inflation factor. Constants pre-computed with Decimal
(73000000; 1490359449/247462156). Validation retirement_age≥current_age. Dual review on Task 2. ✓

## Next
Phase 4 complete → Phase 5 (settings · hardening · analysis · feeds).
