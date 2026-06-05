# Khata Phase 2 · Plan 2A — Holdings Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `holding` plan type — one market position tracked by quantity + cost — with average-cost basis, a manual latest-quote valuation, and a fully derived holding state (qty held, cost of held, current value, realized + unrealized gain), reusing the plan/ledger spine. Backend only.

**Architecture:** Quantities are integer **micro-units** (×10⁶, no float), parsed by new `money.to_micro`. A `holdings` detail table + a nullable `ledger_entries.quantity_micro` carry positions; buys/sells are ledger rows (`kind='buy'/'sell'`). A pure `services/holdings.py` computes average-cost state; `api/plans.py` extends its `type`-dispatch (asset|loan|holding) and adds buy/sell/quote endpoints. The dashboard is untouched (that's Plan 2B).

**Tech Stack:** Python 3.12, Flask 3.1, SQLAlchemy 2.0, Alembic, pytest.

---

## File Structure

```
src/khata/
├── money.py                # MODIFY: to_micro / format_micro (integer micro-units)
├── models/
│   ├── holding.py          # NEW: Holding detail model
│   ├── ledger.py           # MODIFY: quantity_micro column
│   ├── plan.py             # MODIFY: Plan.holding relationship
│   └── __init__.py         # MODIFY: register Holding
├── services/holdings.py    # NEW: create/buy/sell/quote + holding_state (avg cost)
└── api/plans.py            # MODIFY: type dispatch + buy/sell/quote endpoints
alembic/versions/<rev>_holdings.py   # NEW
tests/
├── test_money.py           # MODIFY: to_micro/format_micro
├── test_holding_models.py  # NEW
├── test_holding_service.py # NEW
└── test_holdings_api.py     # NEW
build_status.json           # MODIFY
docs/AGENT_LEARNINGS.md     # MODIFY
```

---

### Task 1: Quantity helpers (`to_micro` / `format_micro`)

**Files:** Modify `src/khata/money.py`; Test `tests/test_money.py`

- [ ] **Step 1: Append failing tests to `tests/test_money.py`**

```python
def test_to_micro_round_trip():
    from khata.money import to_micro, format_micro
    assert to_micro("92.5") == 92_500_000
    assert to_micro(10) == 10_000_000
    assert to_micro("1,250.125") == 1_250_125_000
    assert format_micro(92_500_000) == "92.5"
    assert format_micro(10_000_000) == "10"
    assert format_micro(1_250_125_000) == "1250.125"


def test_to_micro_rejects_float():
    import pytest
    from khata.money import to_micro
    with pytest.raises(TypeError):
        to_micro(92.5)


def test_to_micro_rejects_garbage():
    import pytest
    from khata.money import to_micro
    with pytest.raises(ValueError):
        to_micro("")
    with pytest.raises(Exception):
        to_micro("abc")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_money.py -q`
Expected: FAIL (`ImportError: cannot import name 'to_micro'`).

- [ ] **Step 3: Add the helpers to `src/khata/money.py`**

After the `_EXP = 2` line, add:
```python
_MICRO_EXP = 6  # quantities: integer micro-units (x1_000_000)
```
At the end of the file, add:
```python
def to_micro(value: "str | int") -> int:
    """Parse a human quantity ("92.5", 10) into integer micro-units (x1e6). Rejects float."""
    if isinstance(value, float):
        raise TypeError("quantities must be str or int, not float (no float)")
    s = str(value).strip().replace(",", "").replace("_", "")
    if not s:
        raise ValueError("empty quantity")
    d = Decimal(s)
    if not d.is_finite():
        raise ValueError(f"non-finite quantity: {s!r}")
    return int((d * (10 ** _MICRO_EXP)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_micro(micro: int) -> str:
    """Integer micro-units -> quantity string (92_500_000 -> '92.5')."""
    sign = "-" if micro < 0 else ""
    whole, frac = divmod(abs(int(micro)), 10 ** _MICRO_EXP)
    body = f"{whole}.{frac:0{_MICRO_EXP}d}".rstrip("0").rstrip(".")
    return f"{sign}{body}"
```
(`Decimal`/`ROUND_HALF_UP` are already imported at the top of `money.py`.)

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_money.py -q` (expect all pass), then `.venv/bin/python -m pytest -q` (expect 82 passed — was 79, +3).

- [ ] **Step 5: Commit**

```bash
git add src/khata/money.py tests/test_money.py
git commit -m "feat(money): to_micro/format_micro — integer micro-unit quantities (no float)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Holding model + `quantity_micro` on ledger

**Files:** Create `src/khata/models/holding.py`; Modify `src/khata/models/ledger.py`, `src/khata/models/plan.py`, `src/khata/models/__init__.py`; Test `tests/test_holding_models.py`

- [ ] **Step 1: Write failing test `tests/test_holding_models.py`**

```python
import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, Holding, LedgerEntry


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_holding_persists_and_relationship():
    s = _session()
    u = User(email="a@b.com", display_name="A", password_hash="x")
    s.add(u)
    s.flush()
    plan = Plan(owner_user_id=u.id, type="holding", name="Gold 22K", currency="INR")
    s.add(plan)
    s.flush()
    s.add(Holding(plan_id=plan.id, asset_class="gold", unit="gram",
                  symbol=None, purity="22K"))
    s.commit()

    got = s.get(Plan, plan.id)
    assert got.holding.asset_class == "gold"
    assert got.holding.unit == "gram"
    assert got.holding.purity == "22K"
    assert got.holding.current_price_minor is None


def test_quantity_micro_on_ledger_and_cascade():
    s = _session()
    u = User(email="a@b.com", display_name="A", password_hash="x")
    s.add(u)
    s.flush()
    plan = Plan(owner_user_id=u.id, type="holding", name="Gold", currency="INR")
    s.add(plan)
    s.flush()
    s.add(Holding(plan_id=plan.id, asset_class="gold", unit="gram"))
    from datetime import datetime, timezone
    s.add(LedgerEntry(plan_id=plan.id, logged_by_user_id=u.id, kind="buy", direction="out",
                      amount_minor=50000000, currency="INR",
                      occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                      quantity_micro=92_500_000))
    s.commit()

    e = s.get(Plan, plan.id).ledger_entries[0]
    assert e.quantity_micro == 92_500_000

    # cascade: deleting the plan removes the holding
    pid = plan.id
    s.delete(s.get(Plan, pid))
    s.commit()
    assert s.get(Holding, pid) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_holding_models.py -q`
Expected: FAIL (cannot import `Holding`).

- [ ] **Step 3: Create `src/khata/models/holding.py`**

```python
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class Holding(Base):
    __tablename__ = "holdings"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(12), nullable=False)  # gold|silver|equity|mf|cash|other
    unit: Mapped[str] = mapped_column(String(16), nullable=False)         # gram|share|unit|...
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    purity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    current_price_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    price_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped["Plan"] = relationship(back_populates="holding")
```

- [ ] **Step 4: Add `quantity_micro` to `src/khata/models/ledger.py`**

In the `LedgerEntry` class, immediately after the `amount_minor` line, add:
```python
    quantity_micro: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
```
(`BigInteger` is already imported in this file.)

- [ ] **Step 5: Add the `holding` relationship to `src/khata/models/plan.py`**

In the `Plan` class, immediately after the `loan: Mapped["Loan | None"] = relationship(...)` block, add:
```python
    holding: Mapped["Holding | None"] = relationship(
        back_populates="plan", uselist=False, cascade="all, delete-orphan")
```

- [ ] **Step 6: Register it in `src/khata/models/__init__.py`**

Append:
```python
from .holding import Holding  # noqa: F401
```

- [ ] **Step 7: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_holding_models.py -q` (expect 2 PASS), then `.venv/bin/python -m pytest -q` (expect 84 passed — 82 + 2).

- [ ] **Step 8: Commit**

```bash
git add src/khata/models/holding.py src/khata/models/ledger.py src/khata/models/plan.py src/khata/models/__init__.py tests/test_holding_models.py
git commit -m "feat(models): Holding position + ledger_entries.quantity_micro

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Alembic migration for holdings

**Files:** Create `alembic/versions/<rev>_holdings.py`

- [ ] **Step 1: Reset scratch DB to the Plan-5 head**

```bash
cd /Users/assistant/dev/active/khata
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
(DB now at `82264a4ffa8f`.)

- [ ] **Step 2: Autogenerate**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic revision --autogenerate -m "holdings"
```
Expect output mentioning added table `holdings` and added column `ledger_entries.quantity_micro`.

- [ ] **Step 3: Sanity-check the file**

Open `alembic/versions/*_holdings.py`: confirm `down_revision = '82264a4ffa8f'`; `upgrade()` creates `holdings` (with `plan_id` PK/FK, `asset_class`, `unit`, `symbol`, `purity`, `current_price_minor`, `price_as_of`) and adds `quantity_micro` to `ledger_entries` (likely inside `with op.batch_alter_table('ledger_entries')` due to `render_as_batch=True`); `downgrade()` drops the column + table. If ANY table other than `holdings`/`ledger_entries` appears, STOP and report BLOCKED (trim to only these two and note it).

- [ ] **Step 4: Apply + verify + round-trip**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
.venv/bin/python -c "import sqlite3;db=sqlite3.connect('khata.db');print('holdings' in [r[0] for r in db.execute(\"select name from sqlite_master where type='table'\")]);print('quantity_micro' in [r[1] for r in db.execute('PRAGMA table_info(ledger_entries)')])"
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic downgrade -1 && KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
Expected: `True` then `True`; downgrade + re-upgrade both succeed.

- [ ] **Step 5: Full suite + commit**

```bash
.venv/bin/python -m pytest -q   # 84 passed
rm -f khata.db khata.db-wal khata.db-shm
git add alembic/versions/
git commit -m "feat(db): migration for holdings + ledger_entries.quantity_micro

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
(Do NOT commit the scratch `khata.db`.)

---

### Task 4: Holdings service (average-cost state)

**Files:** Create `src/khata/services/holdings.py`; Test `tests/test_holding_service.py`

- [ ] **Step 1: Write failing test `tests/test_holding_service.py`**

```python
from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.holdings import (
    create_holding_plan, add_buy, add_sell, set_quote, holding_state,
    HoldingError, ValidationError,
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


def _dt(day=1):
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def _gold(s, u):
    return create_holding_plan(s, owner_id=u.id, name="Gold 22K", currency="INR",
                               asset_class="gold", unit="gram", purity="22K")


def test_create_holding_plan(ctx):
    s, u = ctx
    plan = _gold(s, u)
    s.commit()
    assert plan.type == "holding"
    assert plan.holding.asset_class == "gold"
    st = holding_state(s, plan.holding)
    assert st["qty_held_micro"] == 0
    assert st["current_value_minor"] is None  # no quote yet


def test_buy_tranches_average_cost(ctx):
    s, u = ctx
    plan = _gold(s, u)
    # 10 g @ 50,000/g = 500,000 ; 5 g @ 56,000/g = 280,000
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=10_000_000, amount_minor=50000000,
            occurred_at=_dt(1))
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=5_000_000, amount_minor=28000000,
            occurred_at=_dt(2))
    s.commit()
    st = holding_state(s, plan.holding)
    assert st["qty_held_micro"] == 15_000_000           # 15 g
    # avg = (500000 + 280000) / 15 = 52000 minor/g
    assert st["avg_cost_per_unit_minor"] == 52000
    assert st["cost_of_held_minor"] == 78000000          # 780,000


def test_quote_sets_value_and_unrealized(ctx):
    s, u = ctx
    plan = _gold(s, u)
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=10_000_000, amount_minor=50000000,
            occurred_at=_dt(1))
    set_quote(s, plan=plan, price_minor=60000, as_of=_dt(3))   # 600/g spot
    s.commit()
    st = holding_state(s, plan.holding)
    assert st["current_value_minor"] == 60000 * 10        # 600,000
    assert st["unrealized_gain_minor"] == 60000 * 10 - 50000000  # 100,000


def test_sell_reduces_qty_and_realized_gain(ctx):
    s, u = ctx
    plan = _gold(s, u)
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=10_000_000, amount_minor=50000000,
            occurred_at=_dt(1))   # avg 50,000/g
    add_sell(s, plan=plan, user_id=u.id, quantity_micro=4_000_000, amount_minor=24000000,
             occurred_at=_dt(5))  # sold 4 g for 240,000
    s.commit()
    st = holding_state(s, plan.holding)
    assert st["qty_held_micro"] == 6_000_000
    # realized = 240,000 - avg(50,000)*4 = 240,000 - 200,000 = 40,000
    assert st["realized_gain_minor"] == 4000000


def test_oversell_rejected(ctx):
    s, u = ctx
    plan = _gold(s, u)
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=2_000_000, amount_minor=10000000,
            occurred_at=_dt(1))
    with pytest.raises(ValidationError):
        add_sell(s, plan=plan, user_id=u.id, quantity_micro=3_000_000, amount_minor=18000000,
                 occurred_at=_dt(2))


def test_unvalued_has_null_value(ctx):
    s, u = ctx
    plan = _gold(s, u)
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=1_000_000, amount_minor=5000000,
            occurred_at=_dt(1))
    s.commit()
    st = holding_state(s, plan.holding)
    assert st["current_value_minor"] is None
    assert st["unrealized_gain_minor"] is None


def test_invalid_asset_class_rejected(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_holding_plan(s, owner_id=u.id, name="X", currency="INR",
                            asset_class="crypto", unit="coin")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_holding_service.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Create `src/khata/services/holdings.py`**

```python
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from ..models import Plan, Holding, LedgerEntry
from ..money import SUPPORTED_CURRENCIES

MICRO = 1_000_000
ASSET_CLASSES = {"gold", "silver", "equity", "mf", "cash", "other"}


class HoldingError(Exception):
    pass


class ValidationError(HoldingError):
    pass


def create_holding_plan(session: Session, *, owner_id, name, currency, asset_class, unit,
                        symbol=None, purity=None) -> Plan:
    if asset_class not in ASSET_CLASSES:
        raise ValidationError(f"unknown asset_class: {asset_class}")
    if not (unit or "").strip():
        raise ValidationError("unit is required")
    if (currency or "").upper() not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {currency!r}")
    plan = Plan(owner_user_id=owner_id, type="holding",
                name=(name or "").strip() or "Untitled holding",
                currency=currency.upper(), status="active")
    session.add(plan)
    session.flush()
    session.add(Holding(plan_id=plan.id, asset_class=asset_class, unit=unit.strip(),
                        symbol=symbol, purity=purity))
    session.flush()
    return plan


def _qty_held_micro(plan: Plan) -> int:
    bought = sum(e.quantity_micro or 0 for e in plan.ledger_entries if e.kind == "buy")
    sold = sum(e.quantity_micro or 0 for e in plan.ledger_entries if e.kind == "sell")
    return bought - sold


def _add_entry(session, plan, *, user_id, kind, direction, quantity_micro, amount_minor,
               occurred_at, note) -> LedgerEntry:
    if quantity_micro <= 0:
        raise ValidationError("quantity must be > 0")
    if amount_minor <= 0:
        raise ValidationError("amount must be > 0")
    entry = LedgerEntry(plan_id=plan.id, logged_by_user_id=user_id, kind=kind, direction=direction,
                        amount_minor=amount_minor, currency=plan.currency, occurred_at=occurred_at,
                        quantity_micro=quantity_micro, note=note)
    # append through the relationship so a freshly-loaded collection stays consistent
    # when holding_state is read between mutations (avoids stale-collection reads).
    plan.ledger_entries.append(entry)
    session.flush()
    return entry


def add_buy(session: Session, *, plan: Plan, user_id, quantity_micro, amount_minor, occurred_at,
            note=None) -> LedgerEntry:
    return _add_entry(session, plan, user_id=user_id, kind="buy", direction="out",
                      quantity_micro=quantity_micro, amount_minor=amount_minor,
                      occurred_at=occurred_at, note=note)


def add_sell(session: Session, *, plan: Plan, user_id, quantity_micro, amount_minor, occurred_at,
             note=None) -> LedgerEntry:
    if quantity_micro is not None and quantity_micro > 0 and quantity_micro > _qty_held_micro(plan):
        raise ValidationError("cannot sell more than currently held")
    return _add_entry(session, plan, user_id=user_id, kind="sell", direction="in",
                      quantity_micro=quantity_micro, amount_minor=amount_minor,
                      occurred_at=occurred_at, note=note)


def set_quote(session: Session, *, plan: Plan, price_minor, as_of) -> Holding:
    if price_minor < 0:
        raise ValidationError("price must be >= 0")
    holding = plan.holding
    holding.current_price_minor = price_minor
    holding.price_as_of = as_of
    session.flush()
    return holding


def _round(d: Decimal) -> int:
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def holding_state(session: Session, holding: Holding) -> dict:
    plan = holding.plan
    buys = [e for e in plan.ledger_entries if e.kind == "buy"]
    sells = [e for e in plan.ledger_entries if e.kind == "sell"]
    qty_bought = sum(e.quantity_micro or 0 for e in buys)
    qty_sold = sum(e.quantity_micro or 0 for e in sells)
    qty_held = qty_bought - qty_sold
    cost_bought = sum(e.amount_minor for e in buys)
    avg = (Decimal(cost_bought) * MICRO / qty_bought) if qty_bought else Decimal(0)
    cost_of_held = _round(avg * qty_held / MICRO)
    proceeds = sum(e.amount_minor for e in sells)
    realized = proceeds - _round(avg * qty_sold / MICRO)

    price = holding.current_price_minor
    if price is not None:
        current_value = _round(Decimal(price) * qty_held / MICRO)
        unrealized = current_value - cost_of_held
    else:
        current_value = None
        unrealized = None

    return {
        "asset_class": holding.asset_class, "unit": holding.unit, "symbol": holding.symbol,
        "purity": holding.purity, "currency": plan.currency,
        "qty_held_micro": qty_held,
        "avg_cost_per_unit_minor": _round(avg),
        "cost_of_held_minor": cost_of_held,
        "current_price_minor": price,
        "price_as_of": holding.price_as_of.isoformat() if holding.price_as_of else None,
        "current_value_minor": current_value,
        "unrealized_gain_minor": unrealized,
        "realized_gain_minor": realized,
        "proceeds_minor": proceeds,
    }
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_holding_service.py -q` (expect 7 PASS), then `.venv/bin/python -m pytest -q` (expect 91 passed — 84 + 7).

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/holdings.py tests/test_holding_service.py
git commit -m "feat(holdings): create/buy/sell/quote + derived average-cost holding_state

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: API — holding create dispatch + buy/sell/quote endpoints

**Files:** Modify `src/khata/api/plans.py`; Test `tests/test_holdings_api.py`

- [ ] **Step 1: Write failing test `tests/test_holdings_api.py`**

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
    Base.metadata.create_all(app.config["ENGINE"])
    return app.test_client()


def _register(client, email="a@b.com"):
    return client.post("/api/auth/register", json={
        "email": email, "display_name": "A", "password": "pw12345"})


def _make_gold(client):
    return client.post("/api/plans", json={
        "type": "holding", "name": "Gold 22K", "currency": "INR",
        "asset_class": "gold", "unit": "gram", "purity": "22K"})


def test_create_holding_and_state(client):
    _register(client)
    r = _make_gold(client)
    assert r.status_code == 201
    body = r.get_json()
    assert body["plan"]["type"] == "holding"
    assert body["plan"]["asset_class"] == "gold"
    assert body["state"]["qty_held_micro"] == 0
    assert body["state"]["current_value_minor"] is None


def test_buy_then_quote_state(client):
    _register(client)
    pid = _make_gold(client).get_json()["plan"]["id"]
    r = client.post(f"/api/plans/{pid}/holding/buys", json={
        "quantity": "10", "amount": "5,00,000"})
    assert r.status_code == 201
    assert r.get_json()["state"]["qty_held_micro"] == 10_000_000
    r = client.post(f"/api/plans/{pid}/holding/quote", json={"price": "600"})
    assert r.status_code == 200
    st = r.get_json()["state"]
    assert st["current_value_minor"] == 6000000     # 600 * 10 g = 6,000 (minor=600000? see note)


def test_sell_endpoint(client):
    _register(client)
    pid = _make_gold(client).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/holding/buys", json={"quantity": "10", "amount": "5,00,000"})
    r = client.post(f"/api/plans/{pid}/holding/sells", json={"quantity": "4", "amount": "2,40,000"})
    assert r.status_code == 201
    assert r.get_json()["state"]["qty_held_micro"] == 6_000_000


def test_oversell_400(client):
    _register(client)
    pid = _make_gold(client).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/holding/buys", json={"quantity": "2", "amount": "1,00,000"})
    r = client.post(f"/api/plans/{pid}/holding/sells", json={"quantity": "3", "amount": "1,80,000"})
    assert r.status_code == 400


def test_float_quantity_400(client):
    _register(client)
    pid = _make_gold(client).get_json()["plan"]["id"]
    r = client.post(f"/api/plans/{pid}/holding/buys", json={"quantity": 10.5, "amount": "5,00,000"})
    assert r.status_code == 400


def test_holding_auth_and_ownership(client):
    # 401 unauth
    assert client.post("/api/plans/1/holding/buys", json={}).status_code == 401
    # 403 non-owner
    _register(client, "a@b.com")
    pid = _make_gold(client).get_json()["plan"]["id"]
    client.post("/api/auth/logout")
    _register(client, "b@b.com")
    assert client.post(f"/api/plans/{pid}/holding/buys",
                       json={"quantity": "1", "amount": "50000"}).status_code == 403
```

NOTE on the amount in `test_buy_then_quote_state`: `"price": "600"` → `to_minor("600","INR")` = `60000` minor (₹600.00). `quantity "10"` → `10_000_000` micro (10 g). `current_value = 60000 * 10_000_000 / 1_000_000 = 600000` minor = ₹6,000. So the assertion must be `== 600000`. Fix the test value to `600000` before running (the inline comment above is the derivation).

- [ ] **Step 2: Fix the one derived constant, then run to verify failure**

Edit `test_buy_then_quote_state`: change `assert st["current_value_minor"] == 6000000` to `assert st["current_value_minor"] == 600000`.
Run: `.venv/bin/python -m pytest tests/test_holdings_api.py -q`
Expected: FAIL (404/400 — holding endpoints + dispatch absent).

- [ ] **Step 3: Wire the holdings service into `src/khata/api/plans.py` imports + helpers**

Change the money import line to add `to_micro`:
```python
from ..money import format_minor, pct_to_bps, to_micro, to_minor
```
Change the services import line to add `holdings`:
```python
from ..services import assets, holdings, loans, sharing
```
After `from ..services.loans import LoanError`, add:
```python
from ..services.holdings import HoldingError
```

In `_summary`, change the `else` branch so holdings get their own summary. Replace:
```python
    if plan.type == "loan" and plan.loan is not None:
        base.update({"direction": plan.loan.direction, "interest_type": plan.loan.interest_type,
                     "rate_bps": plan.loan.rate_bps, "counterparty": plan.loan.counterparty})
    else:
        base["total_price_minor"] = plan.asset.total_price_minor if plan.asset else None
    return base
```
with:
```python
    if plan.type == "loan" and plan.loan is not None:
        base.update({"direction": plan.loan.direction, "interest_type": plan.loan.interest_type,
                     "rate_bps": plan.loan.rate_bps, "counterparty": plan.loan.counterparty})
    elif plan.type == "holding" and plan.holding is not None:
        base.update({"asset_class": plan.holding.asset_class, "unit": plan.holding.unit,
                     "symbol": plan.holding.symbol,
                     "current_price_minor": plan.holding.current_price_minor})
    else:
        base["total_price_minor"] = plan.asset.total_price_minor if plan.asset else None
    return base
```

In `_detail`, add the holding branch. Replace:
```python
def _detail(plan: Plan) -> dict:
    if plan.type == "loan":
        state = loans.loan_state(g.db, plan.loan, as_of=date.today())
    else:
        state = assets.asset_state(g.db, plan)
    return {"plan": _summary(plan), "state": state}
```
with:
```python
def _detail(plan: Plan) -> dict:
    if plan.type == "loan":
        state = loans.loan_state(g.db, plan.loan, as_of=date.today())
    elif plan.type == "holding":
        state = holdings.holding_state(g.db, plan.holding)
    else:
        state = assets.asset_state(g.db, plan)
    return {"plan": _summary(plan), "state": state}
```

In `_entry_json`, add `quantity_micro` to the returned dict (after `amount_display`):
```python
            "quantity_micro": entry.quantity_micro,
```

- [ ] **Step 4: Add the holding create branch in `create()`**

In `create()`, the `try:` currently branches `if ptype == "loan": ... else: <asset>`. Insert a `holding` branch before the `else`. Find:
```python
        else:
            total = to_minor(data.get("total_price", ""), currency)
            plan = assets.create_asset_plan(g.db, owner_id=user.id, name=data.get("name", ""),
                                            currency=currency, total_price_minor=total)
            items = data.get("installments") or []
            if items:
                assets.set_installments(g.db, plan=plan, items=_parse_items(items, currency))
```
and insert directly above it:
```python
        elif ptype == "holding":
            plan = holdings.create_holding_plan(
                g.db, owner_id=user.id, name=data.get("name", ""), currency=currency,
                asset_class=data.get("asset_class", ""), unit=data.get("unit", ""),
                symbol=data.get("symbol"), purity=data.get("purity"))
```
Then change the `except` tuple in `create()` to include `HoldingError`:
```python
    except (PlanError, LoanError, HoldingError, ValueError, TypeError) as e:
```

- [ ] **Step 5: Append the three holding endpoints to `src/khata/api/plans.py`**

```python
@bp.post("/<int:plan_id>/holding/buys")
def holding_buy(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "holding":
        return jsonify(error="not_a_holding"), 400
    data = request.get_json(silent=True) or {}
    try:
        entry = holdings.add_buy(
            g.db, plan=plan, user_id=user.id,
            quantity_micro=to_micro(data.get("quantity", "")),
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"))
        g.db.commit()
    except (HoldingError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=holdings.holding_state(g.db, plan.holding)), 201


@bp.post("/<int:plan_id>/holding/sells")
def holding_sell(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "holding":
        return jsonify(error="not_a_holding"), 400
    data = request.get_json(silent=True) or {}
    try:
        entry = holdings.add_sell(
            g.db, plan=plan, user_id=user.id,
            quantity_micro=to_micro(data.get("quantity", "")),
            amount_minor=to_minor(data.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(data.get("occurred_at")), note=data.get("note"))
        g.db.commit()
    except (HoldingError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(entry=_entry_json(entry, plan),
                   state=holdings.holding_state(g.db, plan.holding)), 201


@bp.post("/<int:plan_id>/holding/quote")
def holding_quote(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "holding":
        return jsonify(error="not_a_holding"), 400
    data = request.get_json(silent=True) or {}
    try:
        holdings.set_quote(g.db, plan=plan,
                           price_minor=to_minor(data.get("price", ""), plan.currency),
                           as_of=_parse_dt(data.get("as_of")))
        g.db.commit()
    except (HoldingError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(state=holdings.holding_state(g.db, plan.holding)), 200
```

- [ ] **Step 6: Run the API tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_holdings_api.py -q` (expect 6 PASS), then `.venv/bin/python -m pytest -q` (expect 97 passed — 91 + 6).

- [ ] **Step 7: Commit**

```bash
git add src/khata/api/plans.py tests/test_holdings_api.py
git commit -m "feat(api): holding create dispatch + buy/sell/quote endpoints

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Smoke test + process docs

**Files:** Modify `build_status.json`, `docs/AGENT_LEARNINGS.md`

- [ ] **Step 1: Smoke-test the holding flow**

```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db PYTHONPATH=src .venv/bin/python wsgi.py > /tmp/khata_p2a.log 2>&1 &
sleep 2.5
curl -s -c /tmp/cjh -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' -d '{"email":"arjun@b.com","display_name":"Arjun","password":"pw12345"}' >/dev/null
curl -s -b /tmp/cjh -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"type":"holding","name":"Gold 22K","currency":"INR","asset_class":"gold","unit":"gram","purity":"22K"}' >/dev/null
curl -s -b /tmp/cjh -X POST localhost:5050/api/plans/1/holding/buys -H 'Content-Type: application/json' -d '{"quantity":"92.5","amount":"48,10,000"}' >/dev/null
curl -s -b /tmp/cjh -X POST localhost:5050/api/plans/1/holding/quote -H 'Content-Type: application/json' -d '{"price":"6,200"}' | .venv/bin/python -c "import sys,json;st=json.load(sys.stdin)['state'];print('qty',st['qty_held_micro'],'value',st['current_value_minor'],'unrealized',st['unrealized_gain_minor'])"
kill %1 2>/dev/null
rm -f /tmp/cjh /tmp/khata_p2a.log khata.db khata.db-wal khata.db-shm
```
Expected: `qty 92500000 value 57350000 unrealized 9250000` — 92.5 g held; value = 6,200/g × 92.5 = ₹5,73,500 (57350000 minor); unrealized = 57350000 − 48100000 = ₹92,500.

- [ ] **Step 2: Replace `build_status.json`**

```json
{
  "project": "khata",
  "phase": 2,
  "plan": "2A-holdings",
  "tasks_total": 6,
  "tasks_done": 6,
  "last_updated": "2026-06-04",
  "tests": "97 passed",
  "python": "3.12",
  "notes": "Plan 2A complete: holding plan type (generic position: asset_class+unit+symbol/purity), integer micro-unit quantities (no float), buy/sell as ledger rows (quantity_micro), manual latest-quote valuation, derived average-cost holding_state (qty held, cost of held, current value, realized+unrealized gain). API: create dispatch + /holding/buys, /sells, /quote (owner-only). Dashboard untouched. Next: Plan 2B (net-worth consolidation + cross-currency FX + holdings.html UI)."
}
```

- [ ] **Step 3: Append to `docs/AGENT_LEARNINGS.md`**

```markdown

## 2026-06-04 — Plan 2A (Holdings foundation)
- New `holding` plan type via the generic-position model: one `holdings` detail row
  (asset_class/unit/symbol/purity + manual `current_price_minor`/`price_as_of`) per plan; buys/sells
  are `ledger_entries` rows (`kind='buy'/'sell'`) carrying the new nullable `quantity_micro`.
- **Quantities are integer micro-units (×10⁶)** — `money.to_micro`/`format_micro`, rejecting float the
  same way `to_minor` does. Valuation uses `Decimal` over integer minor/micro units; no float anywhere.
- `holding_state` derives everything (average-cost basis): qty held, avg cost/unit, cost of held,
  realized gain (proceeds − avg×sold), and — only when a quote is set — current value + unrealized gain
  (else both null). Oversell (selling more than held) is rejected in `add_sell`.
- Holding buy/sell append through `plan.ledger_entries` (not bare `session.add`) so a freshly-loaded
  collection stays consistent when `holding_state` is read between mutations — avoids the stale-
  collection class of bug seen in Plan 2's `set_installments`.
- API extends the existing `type`-dispatch (asset|loan|holding) for create + detail; the three holding
  mutations are owner-only. Dashboard/net_position deliberately untouched — that's Plan 2B.

### Deferred follow-ups (Plan 2B / later)
- Roll holdings' `current_value_minor` into `dashboard.net_position` gross assets; cross-currency FX.
- Build the rich `holdings.html` net-worth UI. Price history + live spot feeds. Dividends/401(k).
- `holding_state`/`asset_state`/`loan_state` all take an unused `session` arg — reconcile together.
```

- [ ] **Step 4: Commit**

```bash
git add build_status.json docs/AGENT_LEARNINGS.md
git commit -m "chore(process): Plan 2A complete — build status + learnings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- `holdings` table + generic position model → Task 2. ✓
- `ledger_entries.quantity_micro` + `kind` buy/sell → Task 2. ✓
- Integer-micro quantity helpers (no float) → Task 1. ✓
- `Plan.holding` relationship → Task 2. ✓
- Migration → Task 3. ✓
- Services create/buy/sell(quote)/oversell + average-cost `holding_state` → Task 4. ✓
- API type-dispatch (create + detail) + buy/sell/quote, owner-only mutations, `_summary` holding fields → Task 5. ✓
- Dashboard untouched (2A boundary) → no task modifies dashboard. ✓
- Tests for money/models/service/api → Tasks 1,2,4,5. ✓

**Placeholder scan:** No TBD/TODO. The one derived test constant (`current_value_minor`) is explicitly corrected in Task 5 Step 2 with its derivation shown. ✓

**Type consistency:** `to_micro`/`format_micro`; `holding_state` keys (`qty_held_micro`, `avg_cost_per_unit_minor`, `cost_of_held_minor`, `current_value_minor`, `unrealized_gain_minor`, `realized_gain_minor`, `proceeds_minor`, `current_price_minor`, `price_as_of`); service signatures (`create_holding_plan`/`add_buy`/`add_sell`/`set_quote`/`holding_state`); errors `HoldingError`/`ValidationError`; `ASSET_CLASSES`; the `MICRO` scale (1e6); ledger `kind` `buy`/`sell` + `direction` `out`/`in` — all consistent across service, API, and tests. Test counts chain: 79 → 82 (T1) → 84 (T2) → 84 (T3) → 91 (T4) → 97 (T5). ✓

---

## Next (Plan 2B)
Net-worth consolidation: gross assets (asset plans + holdings' current value) − liabilities (loans
owed) = net worth, cross-currency FX; the rich `holdings.html` net-worth UI.
