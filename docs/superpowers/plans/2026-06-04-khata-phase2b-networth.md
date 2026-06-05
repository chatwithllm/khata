# Khata Phase 2 · Plan 2B — Net-Worth Consolidation + Cross-Currency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate owned holdings (market value) + loans (given=asset, taken=liability) into one net-worth figure in a per-user base currency, converting other currencies via manual FX rates — valuing what's valuable and surfacing what isn't — plus a live `holdings.html` net-worth page.

**Architecture:** `User.base_currency` + a global `fx_rates` table (directed `rate_micro`, base-per-quote ×10⁶). A pure `services/fx.py` (set/get/convert) and `services/networth.py` (`net_worth`) read `holding_state`/`loan_state` and convert via fx. A new `networth` blueprint serves `GET /api/networth` + base-currency/fx-rate setters. The page wires to those three endpoints + the existing per-holding quote endpoint. No float; everything derived.

**Tech Stack:** Python 3.12, Flask 3.1, SQLAlchemy 2.0, Alembic, pytest.

---

## File Structure

```
src/khata/
├── models/
│   ├── user.py             # MODIFY: base_currency
│   ├── fx.py               # NEW: FxRate
│   └── __init__.py         # MODIFY: register FxRate
├── services/
│   ├── fx.py               # NEW: set_rate/get_rate/convert
│   └── networth.py         # NEW: net_worth consolidation
├── api/networth.py         # NEW: GET /api/networth, POST /api/base-currency, POST /api/fx-rates
├── __init__.py             # MODIFY: register networth blueprint
├── web.py                  # MODIFY: /holdings route
└── static/holdings.html    # NEW: net-worth page
alembic/versions/<rev>_networth.py   # NEW
tests/
├── test_user_model.py      # MODIFY: base_currency default
├── test_fx_models.py       # NEW
├── test_fx_service.py      # NEW
├── test_networth_service.py# NEW
├── test_networth_api.py    # NEW
└── test_web.py             # MODIFY: /holdings
build_status.json / docs/AGENT_LEARNINGS.md  # MODIFY
```

---

### Task 1: Models — `User.base_currency` + `FxRate`

**Files:** Modify `src/khata/models/user.py`, `src/khata/models/__init__.py`; Create `src/khata/models/fx.py`; Test `tests/test_user_model.py`, `tests/test_fx_models.py`

- [ ] **Step 1: Append failing test to `tests/test_user_model.py`**

```python
def test_user_base_currency_defaults_inr():
    from khata.db import Base, make_engine, make_session_factory
    from khata.models import User
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = make_session_factory(engine)()
    u = User(email="bc@b.com", display_name="BC", password_hash="x")
    s.add(u)
    s.commit()
    assert s.get(User, u.id).base_currency == "INR"
```

- [ ] **Step 2: Write failing test `tests/test_fx_models.py`**

```python
import pytest
from sqlalchemy.exc import IntegrityError

from khata.db import Base, make_engine, make_session_factory
from khata.models import FxRate


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_fx_rate_persists_and_pair_unique():
    s = _session()
    s.add(FxRate(base_currency="INR", quote_currency="USD", rate_micro=83_420_000))
    s.commit()
    assert s.query(FxRate).count() == 1
    s.add(FxRate(base_currency="INR", quote_currency="USD", rate_micro=84_000_000))
    with pytest.raises(IntegrityError):
        s.commit()
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_user_model.py::test_user_base_currency_defaults_inr tests/test_fx_models.py -q`
Expected: FAIL (`base_currency` attr missing; cannot import `FxRate`).

- [ ] **Step 4: Add `base_currency` to `src/khata/models/user.py`**

In the `User` class, immediately after the `google_sub` line, add:
```python
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="INR", server_default="INR")
```

- [ ] **Step 5: Create `src/khata/models/fx.py`**

```python
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("base_currency", "quote_currency", name="uq_fx_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_micro: Mapped[int] = mapped_column(BigInteger, nullable=False)  # base units per 1 quote unit, x1e6
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 6: Register it in `src/khata/models/__init__.py`**

Append:
```python
from .fx import FxRate  # noqa: F401
```

- [ ] **Step 7: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_user_model.py tests/test_fx_models.py -q` (expect all pass), then `.venv/bin/python -m pytest -q` (expect 99 passed — was 97, +2).

- [ ] **Step 8: Commit**

```bash
git add src/khata/models/user.py src/khata/models/fx.py src/khata/models/__init__.py tests/test_user_model.py tests/test_fx_models.py
git commit -m "feat(models): User.base_currency + FxRate (directed rate_micro)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Alembic migration (base_currency + fx_rates)

**Files:** Create `alembic/versions/<rev>_networth.py`

- [ ] **Step 1: Reset scratch DB to the Plan-2A head**

```bash
cd /Users/assistant/dev/active/khata
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
(DB now at `acec7de9fbe6`.)

- [ ] **Step 2: Autogenerate**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic revision --autogenerate -m "networth base_currency and fx_rates"
```
Expect output mentioning added column `users.base_currency` and added table `fx_rates`.

- [ ] **Step 3: Sanity-check the file**

Open `alembic/versions/*_networth*.py`: confirm `down_revision = 'acec7de9fbe6'`; `upgrade()` adds `users.base_currency` (with `server_default='INR'`, NOT NULL — inside `batch_alter_table('users')` due to `render_as_batch=True`) and creates `fx_rates` (id PK, base_currency, quote_currency, rate_micro, as_of, unique `uq_fx_pair`); `downgrade()` drops `fx_rates` + the column. If ANY table other than `users`/`fx_rates` appears, STOP and report BLOCKED (trim to only these and note it).

- [ ] **Step 4: Apply + verify + round-trip**

```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
.venv/bin/python -c "import sqlite3;db=sqlite3.connect('khata.db');print('fx_rates' in [r[0] for r in db.execute(\"select name from sqlite_master where type='table'\")]);print('base_currency' in [r[1] for r in db.execute('PRAGMA table_info(users)')])"
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic downgrade -1 && KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
```
Expected: `True` then `True`; downgrade + re-upgrade both succeed.

- [ ] **Step 5: Full suite + commit**

```bash
.venv/bin/python -m pytest -q   # 99 passed
rm -f khata.db khata.db-wal khata.db-shm
git add alembic/versions/
git commit -m "feat(db): migration for users.base_currency + fx_rates

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
(Do NOT commit the scratch `khata.db`.)

---

### Task 3: FX service (set/get/convert)

**Files:** Create `src/khata/services/fx.py`; Test `tests/test_fx_service.py`

- [ ] **Step 1: Write failing test `tests/test_fx_service.py`**

```python
from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.services.fx import set_rate, get_rate, convert, FxError, ValidationError


@pytest.fixture
def s():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as sess:
        yield sess


def _now():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_convert_math():
    # 1 USD = ₹83.42 → rate_micro 83_420_000. $1.00 (100 USD-minor) → ₹83.42 (8342 INR-minor)
    assert convert(100, rate_micro=83_420_000) == 8342
    assert convert(0, rate_micro=83_420_000) == 0


def test_set_get_and_upsert(s):
    set_rate(s, base="INR", quote="USD", rate_micro=83_420_000, as_of=_now())
    s.commit()
    assert get_rate(s, "INR", "USD") == 83_420_000
    # upsert: same pair updates, does not duplicate
    set_rate(s, base="INR", quote="USD", rate_micro=84_000_000, as_of=_now())
    s.commit()
    assert get_rate(s, "INR", "USD") == 84_000_000
    from khata.models import FxRate
    assert s.query(FxRate).count() == 1


def test_get_rate_identity_and_miss(s):
    assert get_rate(s, "INR", "INR") == 1_000_000   # identity
    assert get_rate(s, "INR", "USD") is None         # unset


def test_set_rate_validation(s):
    with pytest.raises(ValidationError):
        set_rate(s, base="INR", quote="INR", rate_micro=1_000_000, as_of=_now())  # same
    with pytest.raises(ValidationError):
        set_rate(s, base="INR", quote="USD", rate_micro=0, as_of=_now())          # non-positive
    with pytest.raises(ValidationError):
        set_rate(s, base="EUR", quote="USD", rate_micro=1, as_of=_now())          # unsupported
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_fx_service.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Create `src/khata/services/fx.py`**

```python
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FxRate
from ..money import SUPPORTED_CURRENCIES

MICRO = 1_000_000


class FxError(Exception):
    pass


class ValidationError(FxError):
    pass


def convert(amount_minor: int, *, rate_micro: int) -> int:
    """Convert an integer minor amount by a base-per-quote rate (×1e6). Exact Decimal."""
    return int((Decimal(amount_minor) * rate_micro / MICRO).quantize(Decimal(1),
                                                                      rounding=ROUND_HALF_UP))


def get_rate(session: Session, base: str, quote: str) -> int | None:
    base = (base or "").upper()
    quote = (quote or "").upper()
    if base == quote:
        return MICRO
    row = session.scalar(select(FxRate).where(
        FxRate.base_currency == base, FxRate.quote_currency == quote))
    return row.rate_micro if row else None


def set_rate(session: Session, *, base: str, quote: str, rate_micro: int, as_of) -> FxRate:
    base = (base or "").upper()
    quote = (quote or "").upper()
    if base not in SUPPORTED_CURRENCIES or quote not in SUPPORTED_CURRENCIES:
        raise ValidationError(f"unsupported currency: {base!r}/{quote!r}")
    if base == quote:
        raise ValidationError("base and quote must differ")
    if rate_micro <= 0:
        raise ValidationError("rate must be > 0")
    row = session.scalar(select(FxRate).where(
        FxRate.base_currency == base, FxRate.quote_currency == quote))
    if row is None:
        row = FxRate(base_currency=base, quote_currency=quote, rate_micro=rate_micro, as_of=as_of)
        session.add(row)
    else:
        row.rate_micro = rate_micro
        row.as_of = as_of
    session.flush()
    return row
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_fx_service.py -q` (expect 4 PASS), then `.venv/bin/python -m pytest -q` (expect 103 passed — 99 + 4).

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/fx.py tests/test_fx_service.py
git commit -m "feat(fx): set_rate/get_rate/convert (directed rate, exact Decimal)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Net-worth consolidation service

**Files:** Create `src/khata/services/networth.py`; Test `tests/test_networth_service.py`

- [ ] **Step 1: Write failing test `tests/test_networth_service.py`**

```python
from datetime import date, datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.holdings import create_holding_plan, add_buy, set_quote
from khata.services.loans import create_loan_plan, add_disbursement
from khata.services.fx import set_rate
from khata.services.networth import net_worth


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="a@b.com", display_name="Arjun", password_hash="x")  # base INR default
        s.add(u)
        s.flush()
        yield s, u


def _dt(day=1):
    return datetime(2026, day, 1, tzinfo=timezone.utc)


def test_networth_holdings_and_loans_same_currency(ctx):
    s, u = ctx
    # holding: 10 g gold bought ₹5,00,000; quote ₹60,000/g → value ₹6,00,000 (60000000 minor)
    h = create_holding_plan(s, owner_id=u.id, name="Gold", currency="INR",
                            asset_class="gold", unit="gram")
    add_buy(s, plan=h, user_id=u.id, quantity_micro=10_000_000, amount_minor=50000000,
            occurred_at=_dt(1))
    set_quote(s, plan=h, price_minor=6000000, as_of=_dt(2))
    # loan given ₹1,00,000 (asset/receivable), loan taken ₹3,00,000 (liability)
    g = create_loan_plan(s, owner_id=u.id, name="Lent", currency="INR", direction="given",
                         interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=g, user_id=u.id, amount_minor=10000000, occurred_at=_dt(1))
    t = create_loan_plan(s, owner_id=u.id, name="Borrowed", currency="INR", direction="taken",
                         interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    add_disbursement(s, plan=t, user_id=u.id, amount_minor=30000000, occurred_at=_dt(1))
    s.commit()

    nw = net_worth(s, u.id)
    assert nw["base_currency"] == "INR"
    assert nw["assets_minor"] == 60000000 + 10000000     # holding value + receivable
    assert nw["liabilities_minor"] == 30000000
    assert nw["net_worth_minor"] == 60000000 + 10000000 - 30000000
    assert nw["unpriced"] == []
    assert nw["unconverted"] == {}


def test_networth_unpriced_holding_excluded_and_listed(ctx):
    s, u = ctx
    h = create_holding_plan(s, owner_id=u.id, name="Silver", currency="INR",
                            asset_class="silver", unit="gram")
    add_buy(s, plan=h, user_id=u.id, quantity_micro=1_000_000, amount_minor=8000000,
            occurred_at=_dt(1))  # no quote
    s.commit()
    nw = net_worth(s, u.id)
    assert nw["assets_minor"] == 0
    assert len(nw["unpriced"]) == 1 and nw["unpriced"][0]["name"] == "Silver"
    row = next(r for r in nw["holdings"] if r["name"] == "Silver")
    assert row["priced"] is False and row["value_in_base_minor"] is None


def test_networth_cross_currency_conversion(ctx):
    s, u = ctx
    # base INR; a USD holding worth $1,000.00 (100000 USD-minor); rate 1 USD = ₹83.42
    h = create_holding_plan(s, owner_id=u.id, name="US Equity", currency="USD",
                            asset_class="equity", unit="share")
    add_buy(s, plan=h, user_id=u.id, quantity_micro=10_000_000, amount_minor=80000,
            occurred_at=_dt(1))
    set_quote(s, plan=h, price_minor=10, as_of=_dt(2))   # $0.10/share × 10 shares = $1.00? see note
    set_rate(s, base="INR", quote="USD", rate_micro=83_420_000, as_of=_dt(2))
    s.commit()
    nw = net_worth(s, u.id)
    # value in USD = round(10 * 10_000_000 / 1e6) = 100 USD-minor ($1.00); ×83.42 = 8342 INR-minor
    assert nw["assets_minor"] == 8342
    assert nw["unconverted"] == {}


def test_networth_missing_rate_goes_to_unconverted(ctx):
    s, u = ctx
    h = create_holding_plan(s, owner_id=u.id, name="US Equity", currency="USD",
                            asset_class="equity", unit="share")
    add_buy(s, plan=h, user_id=u.id, quantity_micro=10_000_000, amount_minor=80000,
            occurred_at=_dt(1))
    set_quote(s, plan=h, price_minor=10, as_of=_dt(2))   # value 100 USD-minor
    s.commit()  # NO rate set
    nw = net_worth(s, u.id)
    assert nw["assets_minor"] == 0                         # not converted into base
    assert nw["unconverted"]["USD"]["assets_minor"] == 100
    row = next(r for r in nw["holdings"] if r["name"] == "US Equity")
    assert row["priced"] is True and row["value_in_base_minor"] is None  # priced, but no rate
```

NOTE: the cross-currency tests use `price_minor=10` (₹/$ 0.10 per share) × 10 shares = `100` minor of value, deliberately small so the converted integer is easy to assert. The implementation must produce `value_in_base = convert(100, rate)`.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_networth_service.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Create `src/khata/services/networth.py`**

```python
from datetime import date

from sqlalchemy.orm import Session

from ..models import User
from . import sharing, loans, holdings, fx


def net_worth(session: Session, user_id: int) -> dict:
    user = session.get(User, user_id)
    base = user.base_currency
    owned, _member = sharing.user_plans(session, user_id)

    assets = 0
    liabilities = 0
    holdings_rows = []
    unpriced = []
    unconverted: dict[str, dict] = {}

    def _apply(side: str, ccy: str, amount_minor: int):
        """Add amount to base totals if convertible, else to the unconverted bucket.
        Returns the base-converted amount, or None if no rate."""
        nonlocal assets, liabilities
        rate = fx.get_rate(session, base, ccy)
        if rate is not None:
            converted = fx.convert(amount_minor, rate_micro=rate)
            if side == "assets":
                assets += converted
            else:
                liabilities += converted
            return converted
        bucket = unconverted.setdefault(ccy, {"assets_minor": 0, "liabilities_minor": 0})
        bucket[side + "_minor"] += amount_minor
        return None

    for p in owned:
        if p.type == "holding":
            st = holdings.holding_state(session, p.holding)
            priced = st["current_value_minor"] is not None
            value_in_base = None
            if priced:
                value_in_base = _apply("assets", p.currency, st["current_value_minor"])
            else:
                unpriced.append({"id": p.id, "name": p.name, "asset_class": st["asset_class"]})
            holdings_rows.append({
                "id": p.id, "name": p.name, "asset_class": st["asset_class"],
                "currency": p.currency, "qty_held_micro": st["qty_held_micro"],
                "current_value_minor": st["current_value_minor"],
                "value_in_base_minor": value_in_base,
                "unrealized_gain_minor": st["unrealized_gain_minor"],
                "priced": priced,
            })
        elif p.type == "loan":
            st = loans.loan_state(session, p.loan, as_of=date.today())
            side = "assets" if p.loan.direction == "given" else "liabilities"
            _apply(side, p.currency, st["total_minor"])
        # asset-purchase plans are excluded from net worth (acquisition goals)

    return {
        "base_currency": base,
        "assets_minor": assets,
        "liabilities_minor": liabilities,
        "net_worth_minor": assets - liabilities,
        "holdings": holdings_rows,
        "unpriced": unpriced,
        "unconverted": unconverted,
    }
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_networth_service.py -q` (expect 4 PASS), then `.venv/bin/python -m pytest -q` (expect 107 passed — 103 + 4).

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/networth.py tests/test_networth_service.py
git commit -m "feat(networth): net_worth consolidation (holdings+loans, base ccy, value-what-you-can)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: API — networth blueprint

**Files:** Create `src/khata/api/networth.py`; Modify `src/khata/__init__.py`; Test `tests/test_networth_api.py`

- [ ] **Step 1: Write failing test `tests/test_networth_api.py`**

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


def test_networth_requires_auth(client):
    assert client.get("/api/networth").status_code == 401


def test_networth_empty_shape(client):
    _register(client)
    r = client.get("/api/networth")
    assert r.status_code == 200
    d = r.get_json()
    assert d["base_currency"] == "INR"
    assert d["assets_minor"] == 0 and d["liabilities_minor"] == 0
    assert d["net_worth_minor"] == 0
    assert d["holdings"] == [] and d["unpriced"] == [] and d["unconverted"] == {}


def test_set_base_currency(client):
    _register(client)
    assert client.post("/api/base-currency", json={"currency": "USD"}).status_code == 200
    assert client.get("/api/networth").get_json()["base_currency"] == "USD"
    assert client.post("/api/base-currency", json={"currency": "EUR"}).status_code == 400


def test_set_fx_rate_and_convert(client):
    _register(client)
    # base INR (default); set USD rate
    r = client.post("/api/fx-rates", json={"quote": "USD", "rate": "83.42"})
    assert r.status_code == 201
    assert r.get_json()["rate_micro"] == 83_420_000
    # bad rate (float) → 400
    assert client.post("/api/fx-rates", json={"quote": "USD", "rate": 83.42}).status_code == 400
    # create a USD holding worth $1.00 and confirm it converts into assets
    pid = client.post("/api/plans", json={
        "type": "holding", "name": "USX", "currency": "USD",
        "asset_class": "equity", "unit": "share"}).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/holding/buys", json={"quantity": "10", "amount": "8"})
    client.post(f"/api/plans/{pid}/holding/quote", json={"price": "0.10"})  # $0.10/share ×10 = $1.00
    d = client.get("/api/networth").get_json()
    assert d["assets_minor"] == 8342    # $1.00 → 100 USD-minor → ×83.42 = 8342 INR-minor
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_networth_api.py -q`
Expected: FAIL (404 on the new routes).

- [ ] **Step 3: Create `src/khata/api/networth.py`**

```python
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from ..money import SUPPORTED_CURRENCIES, to_micro
from ..services import fx, networth
from .auth import current_user

bp = Blueprint("networth", __name__)


def _as_of(v):
    if not v:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@bp.get("/api/networth")
def get_networth():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    return jsonify(networth.net_worth(g.db, user.id)), 200


@bp.post("/api/base-currency")
def set_base_currency():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    ccy = (data.get("currency") or "").upper()
    if ccy not in SUPPORTED_CURRENCIES:
        return jsonify(error="invalid", detail="unsupported currency"), 400
    user.base_currency = ccy
    g.db.commit()
    return jsonify(base_currency=user.base_currency), 200


@bp.post("/api/fx-rates")
def set_fx_rate():
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    data = request.get_json(silent=True) or {}
    try:
        row = fx.set_rate(g.db, base=user.base_currency, quote=(data.get("quote") or ""),
                          rate_micro=to_micro(data.get("rate", "")), as_of=_as_of(data.get("as_of")))
        g.db.commit()
    except (fx.FxError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(base=row.base_currency, quote=row.quote_currency, rate_micro=row.rate_micro), 201
```

- [ ] **Step 4: Register the blueprint in `src/khata/__init__.py`**

After the dashboard blueprint registration (just before `return app`), add:
```python
    from .api.networth import bp as networth_bp
    app.register_blueprint(networth_bp)
```

- [ ] **Step 5: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_networth_api.py -q` (expect 4 PASS), then `.venv/bin/python -m pytest -q` (expect 111 passed — 107 + 4).

- [ ] **Step 6: Commit**

```bash
git add src/khata/api/networth.py src/khata/__init__.py tests/test_networth_api.py
git commit -m "feat(api): GET /api/networth + POST /api/base-currency + /api/fx-rates

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Holdings net-worth page

**Files:** Create `src/khata/static/holdings.html`; Modify `src/khata/web.py`; Test `tests/test_web.py`

- [ ] **Step 1: Append failing test to `tests/test_web.py`**

```python
def test_holdings_page_served(client):
    r = client.get("/holdings")
    assert r.status_code == 200
    body = r.data.decode()
    for needle in ["Net worth", "/api/networth", "/api/fx-rates", "ledger.css"]:
        assert needle in body
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_web.py::test_holdings_page_served -q`
Expected: FAIL (404 — no `/holdings` route / file).

- [ ] **Step 3: Add the `/holdings` route to `src/khata/web.py`**

After the `features()` view, add:
```python
@bp.get("/holdings")
def holdings():
    return send_from_directory(_static_dir(), "holdings.html")
```

- [ ] **Step 4: Create `src/khata/static/holdings.html`**

```html
<!DOCTYPE html>
<html lang="en" data-cur="inr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Khata — Holdings &amp; Net Worth</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Hanken+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/assets/ledger.css">
<style>
  .nw{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:18px 0}
  .nw .card .k{font-size:12px;color:var(--ink-faint);text-transform:uppercase;letter-spacing:.1em;font-weight:700}
  .nw .card .v{font-family:"Fraunces",serif;font-size:28px;margin-top:6px}
  table.hold{width:100%;border-collapse:collapse;margin-top:8px}
  table.hold th,table.hold td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line)}
  table.hold th{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-faint)}
  .flag{display:inline-block;font-size:11px;font-family:"JetBrains Mono";color:var(--accent);font-weight:700}
  .ctl{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:8px 0 20px}
  .ctl input,.ctl select{font-family:inherit;font-size:14px;padding:8px 11px;border:1px solid var(--line);border-radius:9px;background:var(--card);color:var(--ink)}
  .warn{color:var(--neg);font-size:13px;min-height:18px}
</style>
</head>
<body>
<div class="wrap">
  <nav class="nav">
    <a class="brand" href="/"><span class="glyph"></span> Khata</a>
    <div><a class="link" href="/features">Features</a><a class="link" href="/app">Open app</a></div>
  </nav>

  <header class="hero" style="padding:32px 0 8px">
    <h1>Holdings &amp; net worth</h1>
    <p>Your positions and loans, consolidated into one figure in your base currency.</p>
  </header>

  <section class="nw" id="nw">
    <div class="card"><div class="k">Assets</div><div class="v mono" id="assets">—</div></div>
    <div class="card"><div class="k">Liabilities</div><div class="v mono" id="liabilities">—</div></div>
    <div class="card"><div class="k">Net worth</div><div class="v mono" id="net">—</div></div>
  </section>

  <div class="warn" id="callout"></div>

  <div class="ctl">
    <label class="muted">Base
      <select id="base"><option value="INR">INR ₹</option><option value="USD">USD $</option></select>
    </label>
    <label class="muted">FX 1
      <select id="fxq"><option value="USD">USD</option><option value="INR">INR</option></select>
      =
      <input id="fxr" placeholder="83.42" style="width:90px">
      <span id="fxbase">base</span>
    </label>
    <button class="btn" id="setfx">Set rate</button>
    <span class="warn" id="err"></span>
  </div>

  <table class="hold">
    <thead><tr><th>Holding</th><th>Qty</th><th>Value</th><th>Gain</th><th>In base</th><th>Quote</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</div>

<script>
  const $ = (id) => document.getElementById(id);
  const SYM = { INR: "₹", USD: "$" };

  function fmtMinor(m, ccy) {
    if (m === null || m === undefined) return "—";
    const neg = m < 0; const v = Math.abs(m) / 100;
    return (neg ? "-" : "") + (SYM[ccy] || "") + v.toLocaleString("en-IN", { minimumFractionDigits: 2 });
  }
  function fmtMicro(q) { return (q / 1e6).toLocaleString("en-IN"); }

  async function load() {
    const r = await fetch("/api/networth");
    if (r.status === 401) { window.location.href = "/"; return; }
    const d = await r.json();
    const base = d.base_currency;
    $("base").value = base;
    $("fxbase").textContent = base;
    $("assets").textContent = fmtMinor(d.assets_minor, base);
    $("liabilities").textContent = fmtMinor(d.liabilities_minor, base);
    $("net").textContent = fmtMinor(d.net_worth_minor, base);

    const bits = [];
    if (d.unpriced.length) bits.push(d.unpriced.length + " unpriced holding(s)");
    for (const [ccy, b] of Object.entries(d.unconverted)) {
      bits.push("unconverted " + ccy + ": " + fmtMinor(b.assets_minor, ccy) + " assets / " + fmtMinor(b.liabilities_minor, ccy) + " liab (set an FX rate)");
    }
    $("callout").textContent = bits.join(" · ");

    $("rows").innerHTML = "";
    for (const h of d.holdings) {
      const tr = document.createElement("tr");
      const inbase = h.value_in_base_minor === null
        ? (h.priced ? '<span class="flag">no rate</span>' : '<span class="flag">unpriced</span>')
        : fmtMinor(h.value_in_base_minor, base);
      tr.innerHTML =
        "<td>" + h.name + " <span class='muted'>" + h.asset_class + "</span></td>" +
        "<td class='mono'>" + fmtMicro(h.qty_held_micro) + "</td>" +
        "<td class='mono'>" + fmtMinor(h.current_value_minor, h.currency) + "</td>" +
        "<td class='mono'>" + fmtMinor(h.unrealized_gain_minor, h.currency) + "</td>" +
        "<td class='mono'>" + inbase + "</td>" +
        "<td><input data-id='" + h.id + "' class='q' placeholder='price/unit' style='width:96px'></td>";
      $("rows").appendChild(tr);
    }
    document.querySelectorAll("input.q").forEach((el) => {
      el.addEventListener("keydown", async (e) => {
        if (e.key !== "Enter") return;
        await post("/api/plans/" + el.dataset.id + "/holding/quote", { price: el.value });
        load();
      });
    });
  }

  async function post(path, body) {
    $("err").textContent = "";
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify(body) });
    if (!r.ok) { const e = await r.json().catch(() => ({})); $("err").textContent = e.detail || e.error || "Failed"; }
    return r.ok;
  }

  $("base").addEventListener("change", async () => {
    if (await post("/api/base-currency", { currency: $("base").value })) load();
  });
  $("setfx").addEventListener("click", async () => {
    if (await post("/api/fx-rates", { quote: $("fxq").value, rate: $("fxr").value })) { $("fxr").value = ""; load(); }
  });

  load();
</script>
</body>
</html>
```

- [ ] **Step 5: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/test_web.py -q` (expect all pass), then `.venv/bin/python -m pytest -q` (expect 112 passed — 111 + 1).

- [ ] **Step 6: Commit**

```bash
git add src/khata/static/holdings.html src/khata/web.py tests/test_web.py
git commit -m "feat(web): holdings net-worth page (live consolidation + base/FX/quote controls)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Smoke test + process docs

**Files:** Modify `build_status.json`, `docs/AGENT_LEARNINGS.md`

- [ ] **Step 1: Smoke-test the consolidation**

```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db PYTHONPATH=src .venv/bin/python wsgi.py > /tmp/khata_p2b.log 2>&1 &
sleep 2.5
curl -s -c /tmp/cjn -X POST localhost:5050/api/auth/register -H 'Content-Type: application/json' -d '{"email":"arjun@b.com","display_name":"Arjun","password":"pw12345"}' >/dev/null
# INR gold holding worth ₹6,00,000
curl -s -b /tmp/cjn -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"type":"holding","name":"Gold","currency":"INR","asset_class":"gold","unit":"gram"}' >/dev/null
curl -s -b /tmp/cjn -X POST localhost:5050/api/plans/1/holding/buys -H 'Content-Type: application/json' -d '{"quantity":"10","amount":"5,00,000"}' >/dev/null
curl -s -b /tmp/cjn -X POST localhost:5050/api/plans/1/holding/quote -H 'Content-Type: application/json' -d '{"price":"60,000"}' >/dev/null
# a USD holding + an FX rate
curl -s -b /tmp/cjn -X POST localhost:5050/api/plans -H 'Content-Type: application/json' -d '{"type":"holding","name":"USX","currency":"USD","asset_class":"equity","unit":"share"}' >/dev/null
curl -s -b /tmp/cjn -X POST localhost:5050/api/plans/2/holding/buys -H 'Content-Type: application/json' -d '{"quantity":"10","amount":"8"}' >/dev/null
curl -s -b /tmp/cjn -X POST localhost:5050/api/plans/2/holding/quote -H 'Content-Type: application/json' -d '{"price":"0.10"}' >/dev/null
curl -s -b /tmp/cjn -X POST localhost:5050/api/fx-rates -H 'Content-Type: application/json' -d '{"quote":"USD","rate":"83.42"}' >/dev/null
curl -s -b /tmp/cjn localhost:5050/api/networth | .venv/bin/python -c "import sys,json;d=json.load(sys.stdin);print('base',d['base_currency'],'assets',d['assets_minor'],'net',d['net_worth_minor'],'unconv',d['unconverted'])"
kill %1 2>/dev/null
rm -f /tmp/cjn /tmp/khata_p2b.log khata.db khata.db-wal khata.db-shm
```
Expected: `base INR assets 60008342 net 60008342 unconv {}` — ₹6,00,000 gold (60000000) + $1.00 USD converted at 83.42 (8342) = 60008342; no liabilities; nothing unconverted (rate set). CAPTURE actual output; if the port is busy, free it first (`lsof -ti tcp:5050 | xargs kill 2>/dev/null`).

- [ ] **Step 2: Replace `build_status.json`** with exactly:

```json
{
  "project": "khata",
  "phase": 2,
  "plan": "2B-networth",
  "tasks_total": 7,
  "tasks_done": 7,
  "last_updated": "2026-06-04",
  "tests": "112 passed",
  "python": "3.12",
  "notes": "Plan 2B complete: net-worth consolidation (owned holdings at market value + loans given=asset/taken=liability) in a per-user base_currency, cross-currency via a manual fx_rates table (directed rate_micro, exact Decimal). Value-what-you-can: unpriced holdings + no-rate currencies surfaced separately, never guessed. New networth blueprint (GET /api/networth, POST /api/base-currency, POST /api/fx-rates) + live holdings.html page at /holdings. Existing /api/dashboard untouched. Holdings & net-worth milestone complete."
}
```

- [ ] **Step 3: Append to `docs/AGENT_LEARNINGS.md`** exactly this block:

```markdown

## 2026-06-04 — Plan 2B (Net-worth consolidation + cross-currency)
- `User.base_currency` (default INR) + a global `fx_rates` table (directed `(base,quote)` →
  `rate_micro`, base units per 1 quote unit ×10⁶). `services/fx.py`: `convert` (exact Decimal),
  `get_rate` (identity for base==quote, None on miss), `set_rate` (upsert, validates pair + positivity).
- `services/networth.net_worth` consolidates OWNED plans only: holdings at market `current_value`
  (asset), loan given = asset, loan taken = liability; asset-purchase plans excluded. Each valued
  amount is converted to base if a rate exists, else added to an `unconverted[ccy]` bucket. Unquoted
  holdings → `unpriced[]`. Nothing guessed (the "value-what-you-can" rule).
- New `networth` blueprint hosts `/api/networth` + `/api/base-currency` + `/api/fx-rates` (the FX rate
  is set from the caller's current base to a quote; parsed via `to_micro`, so float is rejected).
- `holdings.html` at `/holdings` renders the live consolidation (assets/liabilities/net, unpriced +
  unconverted callouts, per-holding inline quote). Error text via textContent (XSS-safe).
- The existing `/api/dashboard` (`net_position`) was deliberately left untouched — net worth is a
  separate, holdings-aware endpoint.

### Deferred follow-ups
- Gold-loan-vs-selling analysis; live spot/FX feeds; holdings in shared plans; asset-purchase net-worth
  treatment; fold net worth into the main dashboard. Carry the 2A follow-ups too (None-qty guard, edge
  tests, the shared unused-`session` arg across `*_state`/now also `net_worth`).
```

- [ ] **Step 4: Commit**

```bash
git add build_status.json docs/AGENT_LEARNINGS.md
git commit -m "chore(process): Plan 2B complete — build status + learnings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- `User.base_currency` + `fx_rates` table → Task 1 + migration Task 2. ✓
- FX service (set/get/convert, identity, validation) → Task 3. ✓
- `net_worth` consolidation (holdings market value + loan given/taken; unpriced; unconverted; base ccy) → Task 4. ✓
- API (`GET /api/networth`, `POST /api/base-currency`, `POST /api/fx-rates`) → Task 5. ✓
- `holdings.html` at `/holdings` (summary, list, base/FX/quote controls, callouts) → Task 6. ✓
- Asset-purchase plans excluded; owned-only; `/api/dashboard` untouched → enforced in Task 4 service + no dashboard edits anywhere. ✓
- Tests for fx/networth/api/web → Tasks 1,3,4,5,6. ✓

**Placeholder scan:** No TBD/TODO; complete code/HTML/CSS in every step. The cross-currency test uses deliberately small `price_minor` values with the derivation shown inline. ✓

**Type consistency:** `rate_micro` (×10⁶ base-per-quote); `convert(amount_minor, *, rate_micro)`, `get_rate(session, base, quote)`, `set_rate(session, *, base, quote, rate_micro, as_of)`, `FxError`/`ValidationError`; `net_worth` keys (`base_currency`, `assets_minor`, `liabilities_minor`, `net_worth_minor`, `holdings[]` with `value_in_base_minor`/`priced`, `unpriced[]`, `unconverted{}`); endpoint paths (`/api/networth`, `/api/base-currency`, `/api/fx-rates`); `FxRate` fields. Consistent across service, API, page, and tests. Test counts chain: 97 → 99 (T1) → 99 (T2) → 103 (T3) → 107 (T4) → 111 (T5) → 112 (T6). ✓

---

## Next (later)
Gold-loan-vs-selling analysis · live spot/FX feeds · holdings in shared plans · asset-purchase net-worth
treatment · fold net worth into the main `/api/dashboard`.
