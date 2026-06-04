# Khata Phase 1 · Plan 3 — Loan (given/taken, unsecured) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `loan` plan type — given/taken, tranches, reducing-balance simple interest, bullet/interest-only — reusing the Plan-2 ledger spine, with fully derived loan state, test-first.

**Architecture:** Loan terms live in a `loans` detail table on the shared `plans` base. Loan movements are `ledger_entries` rows distinguished by a new `kind` column (`disbursement`/`interest_payment`/`principal_repayment`; asset payments = `payment`); `method`/`funding_source` become nullable. Interest is computed (never stored) with `Decimal` over integer minor units; rates are integer basis points. The `/api/plans` blueprint gains a `type` dispatch + loan endpoints. Builds on Plan 2.

**Tech Stack:** Python 3.12, Flask 3.1, SQLAlchemy 2.0, Alembic (batch mode for SQLite), pytest.

---

## File Structure

```
src/khata/
├── money.py                 # MODIFY: add pct_to_bps / format_bps
├── models/
│   ├── __init__.py          # MODIFY: register Loan
│   ├── plan.py              # MODIFY: add Plan.loan relationship
│   ├── ledger.py            # MODIFY: add `kind`; method/funding_source → nullable
│   └── loan.py              # NEW: Loan detail table
├── services/
│   └── loans.py             # NEW: create_loan_plan / add_disbursement / log_loan_entry / loan_state
└── api/
    └── plans.py             # MODIFY: type dispatch on create+detail; loan endpoints
alembic/
├── env.py                   # MODIFY: render_as_batch=True
└── versions/<rev>_loans.py  # NEW: loans table + kind column + nullable alters
tests/
├── test_money.py            # MODIFY: pct_to_bps/format_bps
├── test_loan_models.py      # NEW
├── test_loan_service.py     # NEW
└── test_plans_api.py        # MODIFY: loan API tests appended
```

---

### Task 1: Rate helpers in money.py (basis points)

**Files:** Modify `src/khata/money.py`; Test `tests/test_money.py`

- [ ] **Step 1: Append failing tests to `tests/test_money.py`**

```python
def test_pct_to_bps_and_format():
    from khata.money import pct_to_bps, format_bps
    assert pct_to_bps("8.5") == 850
    assert pct_to_bps("2") == 200
    assert pct_to_bps("8.5%") == 850
    assert format_bps(850) == "8.5"
    assert format_bps(200) == "2"
    assert format_bps(0) == "0"


def test_pct_to_bps_rejects_float_and_empty():
    from khata.money import pct_to_bps
    with pytest.raises(TypeError):
        pct_to_bps(8.5)
    with pytest.raises(ValueError):
        pct_to_bps("")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_money.py -q`
Expected: FAIL (ImportError: cannot import name 'pct_to_bps').

- [ ] **Step 3: Append to `src/khata/money.py`**

```python
def pct_to_bps(value) -> int:
    """Parse a human percent ("8.5", "8.5%", 2) into integer basis points (8.5 -> 850)."""
    if isinstance(value, float):
        raise TypeError("rate must be str or int, not float (rates are exact basis points)")
    s = str(value).strip().replace(",", "").replace("_", "").rstrip("%").strip()
    if not s:
        raise ValueError("empty rate")
    d = Decimal(s)
    if not d.is_finite():
        raise ValueError(f"non-finite rate: {s!r}")
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_bps(bps: int) -> str:
    """Integer basis points -> percent string (850 -> '8.5')."""
    sign = "-" if bps < 0 else ""
    whole, frac = divmod(abs(int(bps)), 100)
    body = f"{whole}.{frac:02d}".rstrip("0").rstrip(".")
    return f"{sign}{body}"
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_money.py -q`
Expected: PASS (9 tests in this file now).

- [ ] **Step 5: Commit**

```bash
git add src/khata/money.py tests/test_money.py
git commit -m "feat(money): pct_to_bps/format_bps (rates as integer basis points)"
```

---

### Task 2: Models — Loan + ledger `kind` + nullable method/funding_source

**Files:** Create `src/khata/models/loan.py`; Modify `src/khata/models/plan.py`, `src/khata/models/ledger.py`, `src/khata/models/__init__.py`; Test `tests/test_loan_models.py`

- [ ] **Step 1: Write failing test `tests/test_loan_models.py`**

```python
from datetime import date, datetime, timezone

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, Loan, LedgerEntry


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_loan_and_kind_entry_persist():
    s = _session()
    u = User(email="a@b.com", display_name="A", password_hash="x")
    s.add(u)
    s.flush()
    plan = Plan(owner_user_id=u.id, type="loan", name="Gold loan", currency="INR")
    s.add(plan)
    s.flush()
    s.add(Loan(plan_id=plan.id, direction="taken", interest_type="yearly",
               rate_bps=850, start_date=date(2026, 1, 14)))
    s.add(LedgerEntry(plan_id=plan.id, logged_by_user_id=u.id, direction="in",
                      kind="disbursement", amount_minor=60000000, currency="INR",
                      occurred_at=datetime.now(timezone.utc)))
    s.commit()

    got = s.get(Plan, plan.id)
    assert got.loan.direction == "taken" and got.loan.rate_bps == 850
    e = got.ledger_entries[0]
    assert e.kind == "disbursement" and e.method is None and e.funding_source is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_loan_models.py -q`
Expected: FAIL (cannot import Loan; and `kind`/nullable not present).

- [ ] **Step 3: Create `src/khata/models/loan.py`**

```python
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Loan(Base):
    __tablename__ = "loans"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)         # given | taken
    counterparty: Mapped[str | None] = mapped_column(Text, nullable=True)
    interest_type: Mapped[str] = mapped_column(String(10), nullable=False)    # none | monthly | yearly
    rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    basis: Mapped[str] = mapped_column(String(12), nullable=False, default="reducing")
    repayment: Mapped[str] = mapped_column(String(12), nullable=False, default="bullet")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    tenure_months: Mapped[int | None] = mapped_column(Integer, nullable=True)

    plan: Mapped["Plan"] = relationship(back_populates="loan")
```

- [ ] **Step 4: Modify `src/khata/models/plan.py` — add the `loan` relationship to `Plan`**

In the `Plan` class, right after the existing `asset: Mapped["AssetPurchase | None"] = relationship(...)` line, add:
```python
    loan: Mapped["Loan | None"] = relationship(
        back_populates="plan", uselist=False, cascade="all, delete-orphan")
```

- [ ] **Step 5: Modify `src/khata/models/ledger.py` — add `kind`, make method/funding_source nullable**

In `LedgerEntry`, change the `method` and `funding_source` lines and add `kind` directly after `direction`:
```python
    direction: Mapped[str] = mapped_column(String(3), nullable=False, default="out")
    kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    funding_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
```
(Leave the other columns unchanged.)

- [ ] **Step 6: Modify `src/khata/models/__init__.py` — register `Loan`**

```python
# Importing models here registers them on Base.metadata.
from .user import User  # noqa: F401
from .plan import Plan, AssetPurchase, Installment  # noqa: F401
from .ledger import LedgerEntry  # noqa: F401
from .loan import Loan  # noqa: F401
```

- [ ] **Step 7: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_loan_models.py -q` (expect 1 PASS), then `.venv/bin/python -m pytest -q` (expect 38 PASS — asset tests unaffected; the existing asset service still sets method/funding_source).

- [ ] **Step 8: Commit**

```bash
git add src/khata/models/loan.py src/khata/models/plan.py src/khata/models/ledger.py src/khata/models/__init__.py tests/test_loan_models.py
git commit -m "feat(models): Loan table + ledger kind column + nullable method/funding_source"
```

---

### Task 3: Alembic migration (batch mode) — loans + kind + nullable

**Files:** Modify `alembic/env.py`; Create `alembic/versions/<rev>_loans.py`

- [ ] **Step 1: Enable SQLite batch mode in `alembic/env.py`**

In `run_migrations_online()`, the `context.configure(connection=connection, target_metadata=target_metadata)` call — add `render_as_batch=True`:
```python
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
```

- [ ] **Step 2: Reset the scratch DB to the Plan-2 head so autogenerate diffs correctly**

```bash
cd /Users/assistant/dev/active/khata
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
(DB now has users + plans/asset/installments/ledger at revision `1dffc81d30c6`.)

- [ ] **Step 3: Autogenerate the migration**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic revision --autogenerate -m "loans table + ledger kind + nullable"
```
Expected log: `Detected added table 'loans'`, `Detected added column 'ledger_entries.kind'`, and nullable changes on `ledger_entries.method` / `.funding_source`.

- [ ] **Step 4: Sanity-check the generated file**

Open the new `alembic/versions/*_loans*.py`:
- `down_revision = '1dffc81d30c6'`.
- `upgrade()` contains `op.create_table('loans', ...)` and a `with op.batch_alter_table('ledger_entries') as batch_op:` block that `add_column('kind')` and `alter_column('method'/'funding_source', nullable=True)`.
- If the nullable `alter_column` calls are missing (autogenerate sometimes omits them), add them by hand inside the batch block:
```python
    with op.batch_alter_table('ledger_entries') as batch_op:
        batch_op.add_column(sa.Column('kind', sa.String(length=24), nullable=True))
        batch_op.alter_column('method', existing_type=sa.String(length=20), nullable=True)
        batch_op.alter_column('funding_source', existing_type=sa.String(length=20), nullable=True)
```
and the reverse in `downgrade()`.

- [ ] **Step 5: Apply + verify**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
.venv/bin/python -c "import sqlite3;c=sqlite3.connect('khata.db');print('loans' in [r[0] for r in c.execute(\"select name from sqlite_master where type='table'\")]);print([ (r[1],r[3]) for r in c.execute('PRAGMA table_info(ledger_entries)') if r[1] in ('kind','method','funding_source')])"
```
Expected: `True` (loans table exists) and `[('kind', 0), ('method', 0), ('funding_source', 0)]` — the `0` in the 4th PRAGMA field (`notnull`) means nullable.

- [ ] **Step 6: Round-trip the migration (reversible)**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic downgrade -1 && KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
Expected: both succeed.

- [ ] **Step 7: Full suite + commit**

```bash
.venv/bin/python -m pytest -q   # 38 passed
git add alembic/env.py alembic/versions/
git commit -m "feat(db): migration — loans table, ledger kind, nullable method/funding_source (batch)"
```

---

### Task 4: Loan service — create, disbursement, entries, direction wiring

**Files:** Create `src/khata/services/loans.py`; Test `tests/test_loan_service.py`

- [ ] **Step 1: Write failing test `tests/test_loan_service.py`**

```python
from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.loans import (
    create_loan_plan,
    add_disbursement,
    log_loan_entry,
    loan_state,
    ValidationError,
)


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


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_create_loan_and_direction_wiring(ctx):
    s, u = ctx
    plan = create_loan_plan(s, owner_id=u.id, name="Gold loan", currency="INR",
                            direction="taken", interest_type="yearly", rate_bps=850,
                            start_date=date(2026, 1, 14))
    s.commit()
    assert plan.loan.direction == "taken" and plan.loan.rate_bps == 850
    d = add_disbursement(s, plan=plan, user_id=u.id, amount_minor=60000000,
                         occurred_at=_dt(2026, 1, 14))
    assert d.kind == "disbursement" and d.direction == "in"  # taken -> money to me
    p = log_loan_entry(s, plan=plan, user_id=u.id, kind="interest_payment",
                       amount_minor=2805, occurred_at=_dt(2026, 2, 14))
    assert p.direction == "out"  # taken -> I pay


def test_given_direction_flips_cashflow(ctx):
    s, u = ctx
    plan = create_loan_plan(s, owner_id=u.id, name="Lent S.Mehta", currency="INR",
                            direction="given", interest_type="monthly", rate_bps=200,
                            start_date=date(2026, 4, 2))
    d = add_disbursement(s, plan=plan, user_id=u.id, amount_minor=50000000,
                         occurred_at=_dt(2026, 4, 2))
    assert d.direction == "out"  # given -> money I lend
    r = log_loan_entry(s, plan=plan, user_id=u.id, kind="principal_repayment",
                       amount_minor=10000000, occurred_at=_dt(2026, 5, 2))
    assert r.direction == "in"  # given -> repaid to me


def test_create_loan_validates(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_loan_plan(s, owner_id=u.id, name="x", currency="INR", direction="sideways",
                         interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        create_loan_plan(s, owner_id=u.id, name="x", currency="INR", direction="taken",
                         interest_type="weekly", rate_bps=0, start_date=date(2026, 1, 1))


def test_log_loan_entry_validates(ctx):
    s, u = ctx
    plan = create_loan_plan(s, owner_id=u.id, name="L", currency="INR", direction="taken",
                            interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    with pytest.raises(ValidationError):
        log_loan_entry(s, plan=plan, user_id=u.id, kind="bribe", amount_minor=100,
                       occurred_at=_dt(2026, 1, 1))
    with pytest.raises(ValidationError):
        log_loan_entry(s, plan=plan, user_id=u.id, kind="interest_payment", amount_minor=0,
                       occurred_at=_dt(2026, 1, 1))
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_loan_service.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Create `src/khata/services/loans.py`**

```python
from sqlalchemy.orm import Session

from ..models import Plan, Loan, LedgerEntry
from ..money import SUPPORTED_CURRENCIES

DIRECTIONS = {"given", "taken"}
INTEREST_TYPES = {"none", "monthly", "yearly"}
LOAN_ENTRY_KINDS = {"interest_payment", "principal_repayment"}


class LoanError(Exception):
    pass


class ValidationError(LoanError):
    pass


def create_loan_plan(session: Session, *, owner_id, name, currency, direction, interest_type,
                     rate_bps, start_date, counterparty=None, tenure_months=None) -> Plan:
    if direction not in DIRECTIONS:
        raise ValidationError(f"unknown direction: {direction}")
    if interest_type not in INTEREST_TYPES:
        raise ValidationError(f"unknown interest_type: {interest_type}")
    if currency.upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {currency!r}")
    if rate_bps < 0:
        raise ValidationError("rate must be >= 0")
    plan = Plan(owner_user_id=owner_id, type="loan",
                name=(name or "").strip() or "Untitled loan",
                currency=currency.upper(), status="active")
    session.add(plan)
    session.flush()
    session.add(Loan(plan_id=plan.id, direction=direction, counterparty=counterparty,
                     interest_type=interest_type,
                     rate_bps=rate_bps if interest_type != "none" else 0,
                     start_date=start_date, tenure_months=tenure_months))
    session.flush()
    return plan


def _direction_for(loan_direction: str, kind: str) -> str:
    # taken: disbursement is money to me (in); my payments are out.
    # given: disbursement is money I lend (out); repayments to me are in.
    if loan_direction == "taken":
        return "in" if kind == "disbursement" else "out"
    return "out" if kind == "disbursement" else "in"


def add_disbursement(session: Session, *, plan: Plan, user_id, amount_minor, occurred_at,
                     note=None) -> LedgerEntry:
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, kind="disbursement",
                        direction=_direction_for(plan.loan.direction, "disbursement"),
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at,
                        method=None, funding_source=None, note=note)
    session.add(entry)
    session.flush()
    return entry


def log_loan_entry(session: Session, *, plan: Plan, user_id, kind, amount_minor, occurred_at,
                   method=None, note=None) -> LedgerEntry:
    if kind not in LOAN_ENTRY_KINDS:
        raise ValidationError(f"unknown loan entry kind: {kind}")
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, kind=kind,
                        direction=_direction_for(plan.loan.direction, kind),
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at,
                        method=method, funding_source=None, note=note)
    session.add(entry)
    session.flush()
    return entry


def loan_state(session: Session, loan: Loan, as_of) -> dict:  # implemented in Task 5
    raise NotImplementedError
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_loan_service.py -q`
Expected: 4 PASS (the stub `loan_state` is not called by these tests).

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/loans.py tests/test_loan_service.py
git commit -m "feat(loans): create loan / disbursement / loan entries + direction wiring"
```

---

### Task 5: Loan service — derived interest + schedule (`loan_state`)

**Files:** Modify `src/khata/services/loans.py` (replace the `loan_state` stub + add month helpers); Test `tests/test_loan_service.py` (append)

- [ ] **Step 1: Append failing scenario tests to `tests/test_loan_service.py`**

```python
def _loan(s, u, **kw):
    base = dict(name="L", currency="INR", direction="taken", interest_type="monthly",
                rate_bps=200, start_date=date(2026, 1, 1))
    base.update(kw)
    return create_loan_plan(s, owner_id=u.id, **base)


def test_interest_single_tranche_monthly(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=200, interest_type="monthly", start_date=date(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 1))
    st = loan_state(s, plan.loan, as_of=date(2026, 4, 1))  # 3 complete months @ 2% of 1,00,000
    assert st["principal_outstanding_minor"] == 10000000
    assert st["interest_accrued_minor"] == 600000   # 3 × 2,000.00
    assert st["interest_due_minor"] == 600000
    assert len(st["schedule"]) == 3
    assert st["next_due_month"] == 0 and st["months_behind"] == 3


def test_interest_yearly_rate(ctx):
    s, u = ctx
    plan = _loan(s, u, interest_type="yearly", rate_bps=1200, start_date=date(2026, 1, 1))  # 12%/yr = 1%/mo
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 1))
    st = loan_state(s, plan.loan, as_of=date(2026, 3, 1))  # 2 months
    assert st["interest_accrued_minor"] == 200000  # 2 × 1,000.00


def test_topup_tranche_increases_accrual(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=200, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 2, 1))
    st = loan_state(s, plan.loan, as_of=date(2026, 3, 1))  # 2 months
    # m0 opening 1L -> 2,000 ; m1 opening 2L -> 4,000 ; total 6,000
    assert st["interest_accrued_minor"] == 600000
    assert st["principal_outstanding_minor"] == 20000000


def test_partial_principal_repayment_reduces_accrual(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=200, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=20000000, occurred_at=_dt(2026, 1, 1))
    log_loan_entry(s, plan=plan, user_id=u.id, kind="principal_repayment",
                   amount_minor=10000000, occurred_at=_dt(2026, 2, 1))
    st = loan_state(s, plan.loan, as_of=date(2026, 3, 1))  # 2 months
    # m0 opening 2L -> 4,000 ; m1 opening 1L -> 2,000 ; total 6,000
    assert st["interest_accrued_minor"] == 600000
    assert st["principal_outstanding_minor"] == 10000000


def test_none_interest_zero(ctx):
    s, u = ctx
    plan = _loan(s, u, interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=50000000, occurred_at=_dt(2026, 1, 1))
    st = loan_state(s, plan.loan, as_of=date(2027, 1, 1))
    assert st["interest_accrued_minor"] == 0 and st["schedule"] == []
    assert st["principal_outstanding_minor"] == 50000000


def test_interest_payments_greedy_schedule(ctx):
    s, u = ctx
    plan = _loan(s, u, rate_bps=200, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=10000000, occurred_at=_dt(2026, 1, 1))
    log_loan_entry(s, plan=plan, user_id=u.id, kind="interest_payment",
                   amount_minor=300000, occurred_at=_dt(2026, 2, 1))  # pay 3,000
    st = loan_state(s, plan.loan, as_of=date(2026, 4, 1))  # 3 months × 2,000 = 6,000 accrued
    assert st["interest_paid_minor"] == 300000
    assert st["interest_due_minor"] == 300000
    sch = st["schedule"]
    assert sch[0]["status"] == "paid"
    assert sch[1]["status"] == "partial" and sch[1]["applied_minor"] == 100000
    assert sch[2]["status"] == "due"
    assert st["next_due_month"] == 1 and st["months_behind"] == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_loan_service.py -q`
Expected: the 6 new tests FAIL with `NotImplementedError`.

- [ ] **Step 3: Replace the `loan_state` stub in `src/khata/services/loans.py`**

Add these imports at the top of the file:
```python
import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
```
Then replace `def loan_state(...): raise NotImplementedError` with:
```python
def _month_add(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    mo = m % 12 + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def _complete_months(start: date, as_of: date) -> int:
    months = (as_of.year - start.year) * 12 + (as_of.month - start.month)
    if as_of.day < start.day:
        months -= 1
    return max(0, months)


def loan_state(session: Session, loan: Loan, as_of: date) -> dict:
    plan = loan.plan
    disb = [(e.occurred_at.date(), e.amount_minor) for e in plan.ledger_entries
            if e.kind == "disbursement"]
    prin = [(e.occurred_at.date(), e.amount_minor) for e in plan.ledger_entries
            if e.kind == "principal_repayment"]
    interest_paid = sum(e.amount_minor for e in plan.ledger_entries
                        if e.kind == "interest_payment")
    principal_outstanding = sum(a for _, a in disb) - sum(a for _, a in prin)

    if loan.interest_type == "monthly":
        monthly_rate = Decimal(loan.rate_bps) / Decimal(10000)
    elif loan.interest_type == "yearly":
        monthly_rate = Decimal(loan.rate_bps) / Decimal(120000)
    else:
        monthly_rate = Decimal(0)

    schedule = []
    interest_accrued = 0
    if monthly_rate > 0:
        for m in range(_complete_months(loan.start_date, as_of)):
            pm = _month_add(loan.start_date, m)
            opening = (sum(a for dt, a in disb if dt <= pm)
                       - sum(a for dt, a in prin if dt <= pm))
            opening = max(0, opening)
            expected = int((Decimal(opening) * monthly_rate).quantize(
                Decimal(1), rounding=ROUND_HALF_UP))
            interest_accrued += expected
            schedule.append({"month_index": m, "period_start": pm.isoformat(),
                             "expected_minor": expected})

    pool = interest_paid
    next_due_month = None
    months_behind = 0
    for row in schedule:
        expected = row["expected_minor"]
        applied = min(pool, expected)
        pool -= applied
        row["applied_minor"] = applied
        if expected == 0 or applied == expected:
            row["status"] = "paid"
        elif applied > 0:
            row["status"] = "partial"
        else:
            row["status"] = "due"
        if row["status"] != "paid":
            months_behind += 1
            if next_due_month is None:
                next_due_month = row["month_index"]

    interest_due = max(0, interest_accrued - interest_paid)
    return {
        "direction": loan.direction,
        "currency": plan.currency,
        "principal_outstanding_minor": max(0, principal_outstanding),
        "interest_accrued_minor": interest_accrued,
        "interest_paid_minor": interest_paid,
        "interest_due_minor": interest_due,
        "total_minor": max(0, principal_outstanding) + interest_due,
        "as_of": as_of.isoformat(),
        "schedule": schedule,
        "next_due_month": next_due_month,
        "months_behind": months_behind,
    }
```
(Remove the temporary `raise NotImplementedError` stub.)

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_loan_service.py -q` (expect 10 PASS in file), then `.venv/bin/python -m pytest -q` (expect 44 PASS).

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/loans.py tests/test_loan_service.py
git commit -m "feat(loans): derived reducing-balance simple interest + greedy monthly schedule"
```

---

### Task 6: API — type dispatch + loan endpoints

**Files:** Modify `src/khata/api/plans.py`; Test `tests/test_plans_api.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_plans_api.py`**

```python
def test_create_loan_disbursement_payment_and_state(client):
    _register(client)
    r = client.post("/api/plans", json={
        "type": "loan", "name": "Gold loan", "currency": "INR", "direction": "taken",
        "interest_type": "yearly", "rate": "8.5", "start_date": "2026-01-14"})
    assert r.status_code == 201
    body = r.get_json()
    pid = body["plan"]["id"]
    assert body["plan"]["direction"] == "taken" and body["plan"]["rate_bps"] == 850

    r = client.post(f"/api/plans/{pid}/loan/disbursements",
                    json={"amount": "6,00,000", "occurred_at": "2026-01-14T11:40:00"})
    assert r.status_code == 201
    assert r.get_json()["entry"]["kind"] == "disbursement"
    assert r.get_json()["entry"]["direction"] == "in"
    assert r.get_json()["state"]["principal_outstanding_minor"] == 60000000

    r = client.post(f"/api/plans/{pid}/loan/entries",
                    json={"kind": "interest_payment", "amount": "2,805"})
    assert r.status_code == 201

    r = client.get(f"/api/plans/{pid}")
    assert r.status_code == 200 and r.get_json()["state"]["direction"] == "taken"


def test_asset_create_still_works(client):
    _register(client)
    r = client.post("/api/plans", json={"name": "Plot", "currency": "INR",
                                        "total_price": "10,00,000"})
    assert r.status_code == 201
    assert r.get_json()["plan"]["total_price_minor"] == 100000000
    assert r.get_json()["state"]["remaining_minor"] == 100000000


def test_loan_endpoints_auth_and_ownership(client):
    _register(client, "a@b.com")
    pid = client.post("/api/plans", json={
        "type": "loan", "name": "L", "currency": "INR", "direction": "given",
        "interest_type": "none", "start_date": "2026-01-01"}).get_json()["plan"]["id"]
    client.post("/api/auth/logout")
    assert client.post(f"/api/plans/{pid}/loan/disbursements",
                       json={"amount": "100"}).status_code == 401
    _register(client, "b@b.com")
    assert client.post(f"/api/plans/{pid}/loan/disbursements",
                       json={"amount": "100"}).status_code == 403
    assert client.post(f"/api/plans/{pid}/loan/entries",
                       json={"kind": "interest_payment", "amount": "100"}).status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_plans_api.py -q`
Expected: the 3 new tests FAIL (loan create not dispatched / 404 on loan endpoints).

- [ ] **Step 3: Update the imports at the top of `src/khata/api/plans.py`**

Replace the import block with:
```python
from datetime import date, datetime, timezone

from flask import Blueprint, g, jsonify, request

from ..models import Plan
from ..money import format_minor, pct_to_bps, to_minor
from ..services import assets, loans
from ..services.assets import PlanError
from ..services.loans import LoanError
from .auth import current_user
```

- [ ] **Step 4: Add helpers + replace `_summary`/`_detail` in `src/khata/api/plans.py`**

Replace the existing `_summary` and `_detail` functions with:
```python
def _parse_dt(v):
    dt = datetime.fromisoformat(v) if v else datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _entry_json(entry, plan):
    return {"id": entry.id, "kind": entry.kind, "direction": entry.direction,
            "amount_minor": entry.amount_minor,
            "amount_display": format_minor(entry.amount_minor, plan.currency),
            "method": entry.method, "funding_source": entry.funding_source}


def _summary(plan: Plan) -> dict:
    base = {"id": plan.id, "type": plan.type, "name": plan.name,
            "currency": plan.currency, "status": plan.status}
    if plan.type == "loan" and plan.loan is not None:
        base.update({"direction": plan.loan.direction, "interest_type": plan.loan.interest_type,
                     "rate_bps": plan.loan.rate_bps, "counterparty": plan.loan.counterparty})
    else:
        base["total_price_minor"] = plan.asset.total_price_minor if plan.asset else None
    return base


def _detail(plan: Plan) -> dict:
    if plan.type == "loan":
        state = loans.loan_state(g.db, plan.loan, as_of=date.today())
    else:
        state = assets.asset_state(g.db, plan)
    return {"plan": _summary(plan), "state": state}
```

- [ ] **Step 5: Replace the `create()` view in `src/khata/api/plans.py` with a type dispatch**

```python
@bp.post("")
def create():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    ptype = (data.get("type") or "asset").lower()
    currency = (data.get("currency") or "INR").upper()
    try:
        if ptype == "loan":
            interest_type = (data.get("interest_type") or "none")
            plan = loans.create_loan_plan(
                g.db, owner_id=user.id, name=data.get("name", ""), currency=currency,
                direction=data.get("direction", ""), counterparty=data.get("counterparty"),
                interest_type=interest_type,
                rate_bps=pct_to_bps(data.get("rate", "0")) if interest_type != "none" else 0,
                start_date=date.fromisoformat(data["start_date"]) if data.get("start_date") else date.today(),
                tenure_months=data.get("tenure_months"))
        else:
            total = to_minor(data.get("total_price", ""), currency)
            plan = assets.create_asset_plan(g.db, owner_id=user.id, name=data.get("name", ""),
                                            currency=currency, total_price_minor=total)
            items = data.get("installments") or []
            if items:
                assets.set_installments(g.db, plan=plan, items=_parse_items(items, currency))
        g.db.commit()
    except (PlanError, LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(_detail(plan)), 201
```

- [ ] **Step 6: Append the two loan endpoints at the end of `src/khata/api/plans.py`**

```python
@bp.post("/<int:plan_id>/loan/disbursements")
def loan_disbursement(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "loan":
        return jsonify(error="not_a_loan"), 400
    data = request.get_json(silent=True) or {}
    try:
        entry = loans.add_disbursement(
            g.db, plan=plan, user_id=user.id, amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"))
        g.db.commit()
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=loans.loan_state(g.db, plan.loan, as_of=date.today())), 201


@bp.post("/<int:plan_id>/loan/entries")
def loan_entry(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "loan":
        return jsonify(error="not_a_loan"), 400
    data = request.get_json(silent=True) or {}
    try:
        entry = loans.log_loan_entry(
            g.db, plan=plan, user_id=user.id, kind=data.get("kind", ""),
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")),
            method=data.get("method"), note=data.get("note"))
        g.db.commit()
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=loans.loan_state(g.db, plan.loan, as_of=date.today())), 201
```

- [ ] **Step 7: Run the API tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_plans_api.py -q` (expect 7 PASS), then `.venv/bin/python -m pytest -q` (expect 47 PASS).

- [ ] **Step 8: Commit**

```bash
git add src/khata/api/plans.py tests/test_plans_api.py
git commit -m "feat(api): /api/plans type dispatch (asset|loan) + loan disbursement/entry endpoints"
```

---

### Task 7: Smoke test + process docs

**Files:** Modify `build_status.json`, `docs/AGENT_LEARNINGS.md`

- [ ] **Step 1: Smoke-test the real server (gold loan, taken)**

```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
PYTHONPATH=src KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/python wsgi.py > /tmp/khata_p3.log 2>&1 &
sleep 2.5
curl -s -c /tmp/cj3 -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"a@b.com","display_name":"Arjun","password":"pw12345"}' >/dev/null
curl -s -b /tmp/cj3 -X POST localhost:5050/api/plans -H 'Content-Type: application/json' \
  -d '{"type":"loan","name":"HDFC gold loan","currency":"INR","direction":"taken","interest_type":"yearly","rate":"8.5","start_date":"2026-01-14"}'
curl -s -b /tmp/cj3 -X POST localhost:5050/api/plans/1/loan/disbursements -H 'Content-Type: application/json' \
  -d '{"amount":"6,00,000","occurred_at":"2026-01-14T11:40:00"}'
kill %1 2>/dev/null
```
Expected: create returns a loan plan (`direction: taken`, `rate_bps: 850`); disbursement returns `entry.kind=disbursement`, `direction=in`, `state.principal_outstanding_minor=60000000`.

- [ ] **Step 2: Update `build_status.json`**

```json
{
  "project": "khata",
  "phase": 1,
  "plan": "3-loan",
  "tasks_total": 7,
  "tasks_done": 7,
  "last_updated": "2026-06-04",
  "tests": "47 passed",
  "python": "3.12",
  "notes": "Plan 3 complete: Loan type (given/taken, unsecured) — tranches, reducing-balance simple interest (rates as basis points), bullet/interest-only, principal-vs-interest ledger via `kind`, derived loan_state + monthly schedule, /api/plans type dispatch + loan endpoints. Next: Plan 4 (sharing & contributors)."
}
```

- [ ] **Step 3: Append to `docs/AGENT_LEARNINGS.md`**

```markdown

## 2026-06-04 — Plan 3 (Loan)
- Loan movements reuse `ledger_entries` via a `kind` column (disbursement / interest_payment /
  principal_repayment); `method`/`funding_source` made nullable. SQLite can't drop NOT NULL in
  place → set `render_as_batch=True` in `alembic/env.py` so the migration recreates the table.
- Interest is derived (reducing-balance, simple, whole-month) with `Decimal` over integer minor
  units; rates stored as integer basis points (`pct_to_bps`) — no float anywhere.
- `direction` (in/out) is set from (loan.direction, kind) for cashflow display; loan math uses
  `kind`+amount magnitudes only.
- The Plan-2 `_detail`/`create` now dispatch on `plan.type` (asset|loan) — the follow-up flagged
  in Plan 2 is done.
```

- [ ] **Step 4: Commit**

```bash
rm -f /tmp/cj3 /tmp/khata_p3.log
git add build_status.json docs/AGENT_LEARNINGS.md
git commit -m "chore(process): Plan 3 complete — build status + learnings"
```

---

## Self-Review

**Spec coverage (Plan 3 = unsecured loan):**
- `loans` detail + direction/counterparty/interest_type/rate_bps/start_date/tenure → Task 2 + migration Task 3. ✓
- Ledger `kind` + nullable method/funding_source → Tasks 2, 3. ✓
- Rates as basis points (`pct_to_bps`/`format_bps`) → Task 1. ✓
- Tranches as disbursement entries; principal outstanding derived → Tasks 4, 5. ✓
- Derived reducing-balance simple interest + greedy monthly schedule (none ⇒ zero) → Task 5. ✓
- Direction wiring (taken/given) → Task 4. ✓
- API type dispatch (asset|loan) + loan endpoints, owner-scoped → Task 6. ✓
- Migration batch mode (`render_as_batch`) → Task 3. ✓

**Placeholder scan:** No TBD/TODO; complete code in every step; the only stub (`loan_state` in Task 4) is explicitly replaced in Task 5. ✓

**Type consistency:** `Loan` fields and `loan_state` keys (`principal_outstanding_minor`, `interest_accrued_minor`, `interest_paid_minor`, `interest_due_minor`, `total_minor`, `schedule[]{month_index,period_start,expected_minor,applied_minor,status}`, `next_due_month`, `months_behind`) are asserted in Task 5 and consumed in Task 6. Service signatures (`create_loan_plan`, `add_disbursement`, `log_loan_entry`, `loan_state`) match the API call sites. `pct_to_bps`/`format_bps` match Task 1. `_direction_for` mapping consistent with the direction-wiring tests. ✓

---

## Next plans (Phase 1 continued)
- **Plan 4** — Sharing & contributors: PlanMembership, per-payment attribution, auto ownership share, net-position dashboard (rolls up asset/loan/chit).
- **Plan 5** — Google OAuth + polished Features page; secured loans / collateral (with holdings).
