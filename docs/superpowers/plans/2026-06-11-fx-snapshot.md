# Per-Entry FX Rate Snapshots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every ledger entry stores the USD↔INR rate as of the day it happened (editable afterward), so the exact counter-currency value of every transaction is known forever; live rates come from frankfurter.app and the current rate refreshes daily.

**Architecture:** Two nullable columns on `ledger_entries` (`fx_rate_micro` = counter-per-entry ×1e6, `fx_counter_currency`), stamped at creation via a fallback chain (explicit client rate → frankfurter at `occurred_at` date → stored manual rate → NULL). A new stdlib-only `services/fx_live.py` talks to frankfurter; `services/fx.py` stays pure DB/math plus the snapshot helper. Dashboard "paid" sums convert per-entry; spot values keep the current rate. Daily scheduler refresh + admin backfill endpoint round it out.

**Tech Stack:** Flask + SQLAlchemy 2.0 typed mappings, alembic, stdlib `urllib.request`, pytest, vanilla-JS static pages.

**Spec:** `docs/specs/2026-06-11-fx-snapshot-design.md` (approved). Branch: `feat/fx-snapshot` (already created, spec committed).

**Run tests with:** `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest` from `/private/tmp/khata-landing`. Full suite must stay green (288 passing today).

---

## CRITICAL: rate-direction conventions (read before any task)

Three conventions coexist. Mixing them up is THE bug to avoid:

1. **`FxRate` table / `fx.get_rate(session, X, Y)`** → returns **X-per-Y ×1e6** (base-per-quote). The canonical stored row is `base='INR', quote='USD', rate_micro≈88_000_000` (₹88 per $1) — that's what Settings saves.
2. **frankfurter / `fx_live.fetch_*(base, quote)`** → returns **quote-per-base ×1e6** (frankfurter's own convention: `GET ?base=USD&symbols=INR` → `rates.INR` ≈ 88 = INR per USD).
3. **Snapshot columns on the entry** → `fx_rate_micro` is **counter-per-entry-currency ×1e6** (always "multiply forward"): INR entry → USD-per-INR ≈ `11_364`; USD entry → INR-per-USD ≈ `88_000_000`. `convert(amount_minor, rate_micro=fx_rate_micro)` yields counter minor units directly.

So the snapshot helper uses `fx_live.fetch_rate(d, base=entry.currency, quote=counter)` (convention 2 → counter-per-entry ✓) and falls back to `fx.get_rate(session, counter, entry.currency)` (convention 1 → counter-per-entry ✓).

**Spec §6 deviation (deliberate, direction fix):** spec says "upsert via `fx.set_rate(base=USD, quote=INR, ...)`" — that wording conflates frankfurter's base param with FxRate's. `fetch_latest("USD", "INR")` returns INR-per-USD, and the canonical stored pair (matching Settings, `settings.html:311`) is `base="INR", quote="USD"`. The scheduler task below stores it that way.

## File structure

```
src/khata/
  models/ledger.py          # +fx_rate_micro, +fx_counter_currency
  models/fx.py              # +FxRefreshState (single-row daily-refresh claim)
  models/__init__.py        # export FxRefreshState
  services/fx_live.py       # NEW — frankfurter client (urllib, never raises)
  services/fx.py            # +counter_currency_for, +snapshot_entry_rate, +refresh claim fns
  services/assets.py        # log_payment + update_ledger_entry + asset_state ledger
  services/holdings.py      # _add_entry hook
  services/loans.py         # add_disbursement + log_loan_entry hooks + loan_state ledger
  services/chits.py         # log_chit_entry hook + chit_state ledger
  services/dashboard.py     # per-entry "paid" conversion
  scheduler.py              # +_fx_tick + job
  api/plans.py              # fx_rate_micro on create/PATCH (422 invalid)
  api/admin.py              # POST /api/admin/fx-backfill
  static/assets/fx.js       # NEW — fxLine + natural-rate edit helpers
  static/asset-detail.html  # ledger fx line + edit-form rate field
  static/loan-detail.html   # ledger fx line + edit-form rate field
  static/chit-detail.html   # ledger fx line + edit-form rate field
  static/settings.html      # daily-refresh hint
alembic/versions/fxsnapshot01_fx_entry_snapshot.py  # NEW migration
tests/
  conftest.py               # +autouse no-live-fx fixture
  test_fx_live.py           # NEW
  test_fx_snapshot.py       # NEW (snapshot chain + creation hooks + PATCH service)
  test_fx_backfill_api.py   # NEW
  test_fx_scheduler.py      # NEW
  + edits to test_plans_api.py, test_dashboard_service.py
```

Notes locked during planning:
- Loan outstanding (`loan_state total_minor`) includes **computed accrued interest** → not a pure entry sum → stays at the current rate (spec §5's own wording). Dashboard's asset "paid" loop IS per-entry → gets snapshot rates. Net worth holdings/loans already use spot/current — unchanged.
- holding-detail/retirement-detail render no ledger rows today (no `ledger` array in their states) → no UI line there. Serialization additions go to the three states that expose `ledger`: asset, loan, chit.
- Tests must NEVER hit the network: Task 3 adds an autouse conftest fixture stubbing `fx.fx_live`.

---

### Task 1: Schema — entry snapshot columns + FxRefreshState + migration

**Files:**
- Modify: `src/khata/models/ledger.py` (after `counter_amount_minor`, ~line 40)
- Modify: `src/khata/models/fx.py`
- Modify: `src/khata/models/__init__.py`
- Create: `alembic/versions/fxsnapshot01_fx_entry_snapshot.py`
- Test: `tests/test_fx_snapshot.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_fx_snapshot.py`:

```python
from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import FxRefreshState, LedgerEntry, User
from khata.services.assets import create_asset_plan


@pytest.fixture
def s():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as sess:
        yield sess


@pytest.fixture
def ctx(s):
    u = User(email="a@b.com", display_name="Arjun", password_hash="x")
    s.add(u)
    s.flush()
    plan = create_asset_plan(s, owner_id=u.id, name="Plot", currency="INR",
                             total_price_minor=50_000_000)
    return s, u, plan


def _dt():
    return datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)


def test_ledger_entry_snapshot_columns_roundtrip(ctx):
    s, u, plan = ctx
    e = LedgerEntry(plan_id=plan.id, logged_by_user_id=u.id, direction="out",
                    amount_minor=100, currency="INR", occurred_at=_dt(),
                    fx_rate_micro=11_364, fx_counter_currency="USD")
    s.add(e)
    s.flush()
    got = s.get(LedgerEntry, e.id)
    assert got.fx_rate_micro == 11_364
    assert got.fx_counter_currency == "USD"


def test_snapshot_columns_default_null(ctx):
    s, u, plan = ctx
    e = LedgerEntry(plan_id=plan.id, logged_by_user_id=u.id, direction="out",
                    amount_minor=100, currency="INR", occurred_at=_dt())
    s.add(e)
    s.flush()
    assert e.fx_rate_micro is None
    assert e.fx_counter_currency is None


def test_fx_refresh_state_roundtrip(s):
    s.add(FxRefreshState(id=1))
    s.flush()
    row = s.get(FxRefreshState, 1)
    assert row.last_run_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_snapshot.py -v`
Expected: FAIL — `ImportError: cannot import name 'FxRefreshState'` (and/or `TypeError: 'fx_rate_micro' is an invalid keyword argument`).

- [ ] **Step 3: Add model columns**

In `src/khata/models/ledger.py`, directly after the `counter_amount_minor` column definition, add:

```python
    # FX snapshot: counter-currency units per 1 entry-currency unit, ×1e6, captured at
    # log time (editable later). NULL = no rate known. The counter value is always
    # DERIVED (services/fx.convert) — never stored. See docs/specs/2026-06-11-fx-snapshot-design.md.
    fx_rate_micro: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fx_counter_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
```

In `src/khata/models/fx.py`, append:

```python
class FxRefreshState(Base):
    """Single-row (id=1) claim record for the daily live-FX refresh. Mirrors
    BackupConfig.last_run_at: an atomic UPDATE flips last_run_at so exactly one
    gunicorn worker performs a given day's fetch."""
    __tablename__ = "fx_refresh_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

(`datetime`, `DateTime`, `Mapped`, `mapped_column`, `Base` are already imported in that file.)

In `src/khata/models/__init__.py`, change the fx import line to:

```python
from .fx import FxRate, FxRefreshState  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_snapshot.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Write the migration**

Create `alembic/versions/fxsnapshot01_fx_entry_snapshot.py` (template mirrors `df9backup01_backup_config.py`):

```python
"""ledger-entry FX snapshots + daily-refresh claim row

Revision ID: fxsnapshot01
Revises: df9backup01
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "fxsnapshot01"
down_revision = "df9backup01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # counter-currency units per 1 entry-currency unit, x1e6; NULL = no rate known
    op.add_column("ledger_entries", sa.Column("fx_rate_micro", sa.BigInteger(), nullable=True))
    op.add_column("ledger_entries", sa.Column("fx_counter_currency", sa.String(3), nullable=True))
    op.create_table(
        "fx_refresh_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
    )
    op.execute("INSERT INTO fx_refresh_state (id, last_run_at) VALUES (1, NULL)")


def downgrade() -> None:
    op.drop_table("fx_refresh_state")
    op.drop_column("ledger_entries", "fx_counter_currency")
    op.drop_column("ledger_entries", "fx_rate_micro")
```

- [ ] **Step 6: Verify the migration runs**

Run: `cd /private/tmp/khata-landing && KHATA_DATABASE_URL="sqlite:////tmp/fxmig-test.db" /Users/assistant/dev/active/khata/.venv/bin/python -m alembic upgrade head && rm -f /tmp/fxmig-test.db`
Expected: upgrades through `fxsnapshot01` with no error. (If alembic env doesn't read `KHATA_DATABASE_URL`, check `alembic/env.py` for the env var it uses and match it; do NOT run against `khata_app.db`.)

- [ ] **Step 7: Run full suite, then commit**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q`
Expected: all pass.

```bash
git add src/khata/models/ledger.py src/khata/models/fx.py src/khata/models/__init__.py alembic/versions/fxsnapshot01_fx_entry_snapshot.py tests/test_fx_snapshot.py
git commit -m "feat(fx): ledger-entry FX snapshot columns + refresh-claim table"
```

---

### Task 2: `services/fx_live.py` — frankfurter client

**Files:**
- Create: `src/khata/services/fx_live.py`
- Test: `tests/test_fx_live.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fx_live.py`:

```python
import io
import json
import urllib.error
from datetime import date

from khata.services import fx_live


class _FakeResp(io.BytesIO):
    """Minimal urlopen context-manager response."""
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode() if not isinstance(payload, bytes) else payload)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, payload=None, status=200, exc=None, capture=None):
    def fake_urlopen(url, timeout=None):
        if capture is not None:
            capture.append((url, timeout))
        if exc is not None:
            raise exc
        return _FakeResp(payload, status=status)
    monkeypatch.setattr(fx_live.urllib.request, "urlopen", fake_urlopen)


def test_fetch_rate_success(monkeypatch):
    calls = []
    _patch(monkeypatch, {"base": "INR", "rates": {"USD": 0.011364}}, capture=calls)
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") == 11_364
    url, timeout = calls[0]
    assert url == "https://api.frankfurter.dev/v1/2026-06-10?base=INR&symbols=USD"
    assert timeout == 4


def test_fetch_latest_success(monkeypatch):
    calls = []
    _patch(monkeypatch, {"base": "USD", "rates": {"INR": 88.0}}, capture=calls)
    assert fx_live.fetch_latest("USD", "INR") == 88_000_000
    assert calls[0][0] == "https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR"


def test_fetch_rate_timeout_returns_none(monkeypatch):
    _patch(monkeypatch, exc=TimeoutError("timed out"))
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") is None


def test_fetch_rate_http_error_returns_none(monkeypatch):
    _patch(monkeypatch, exc=urllib.error.HTTPError("u", 500, "boom", {}, None))
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") is None


def test_fetch_rate_non_200_returns_none(monkeypatch):
    _patch(monkeypatch, {"rates": {"USD": 0.011}}, status=404)
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") is None


def test_fetch_rate_malformed_json_returns_none(monkeypatch):
    _patch(monkeypatch, b"not json {{")
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") is None


def test_fetch_rate_missing_symbol_returns_none(monkeypatch):
    _patch(monkeypatch, {"rates": {}})
    assert fx_live.fetch_rate(date(2026, 6, 10), "INR", "USD") is None


def test_fetch_range_with_weekend_gaps(monkeypatch):
    # Fri 2026-06-05 and Mon 2026-06-08 present; weekend absent (frankfurter omits it)
    _patch(monkeypatch, {"rates": {"2026-06-05": {"INR": 88.0},
                                   "2026-06-08": {"INR": 88.5}}})
    rates = fx_live.fetch_range(date(2026, 6, 5), date(2026, 6, 8), "USD", "INR")
    assert rates == {date(2026, 6, 5): 88_000_000, date(2026, 6, 8): 88_500_000}


def test_fetch_range_failure_returns_empty(monkeypatch):
    _patch(monkeypatch, exc=OSError("no network"))
    assert fx_live.fetch_range(date(2026, 6, 5), date(2026, 6, 8), "USD", "INR") == {}


def test_rate_for_date_prior_business_day():
    rates = {date(2026, 6, 5): 88_000_000}  # Friday only
    assert fx_live.rate_for_date(rates, date(2026, 6, 7)) == 88_000_000  # Sunday → Friday
    assert fx_live.rate_for_date(rates, date(2026, 6, 5)) == 88_000_000  # exact hit
    assert fx_live.rate_for_date(rates, date(2026, 6, 20)) is None       # beyond max_back
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_live.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'khata.services.fx_live'`.

- [ ] **Step 3: Implement `src/khata/services/fx_live.py`**

```python
"""Live FX rates from frankfurter.app (free, no key, ECB daily fixes).

Stdlib-only (`urllib.request`) — no new dependency. Every function swallows
EVERY failure (network, non-200, parse, missing key) and returns None / {} so
nothing here can ever raise into a request flow. Rates return as int micro
(×1e6) in frankfurter's own direction: quote-per-base (?base=USD&symbols=INR
→ INR per USD). NOTE: that is the OPPOSITE of fx.get_rate's base-per-quote.
"""
import json
import urllib.request
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

BASE_URL = "https://api.frankfurter.dev/v1"
TIMEOUT_S = 4
MICRO = 1_000_000


def _get_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _to_micro(val) -> int | None:
    """JSON number → int ×1e6 (Decimal, ROUND_HALF_UP — rates never float onward)."""
    if val is None:
        return None
    try:
        micro = int((Decimal(str(val)) * MICRO).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except Exception:
        return None
    return micro if micro > 0 else None


def fetch_rate(d: date, base: str, quote: str) -> int | None:
    """quote-per-base ×1e6 as of `d`. frankfurter auto-returns the last business
    day's fix for weekends/holidays on single-date lookups."""
    data = _get_json(f"{BASE_URL}/{d.isoformat()}?base={base}&symbols={quote}")
    if not isinstance(data, dict):
        return None
    return _to_micro((data.get("rates") or {}).get(quote))


def fetch_latest(base: str, quote: str) -> int | None:
    """Today's quote-per-base ×1e6."""
    data = _get_json(f"{BASE_URL}/latest?base={base}&symbols={quote}")
    if not isinstance(data, dict):
        return None
    return _to_micro((data.get("rates") or {}).get(quote))


def fetch_range(start: date, end: date, base: str, quote: str) -> dict[date, int]:
    """All business-day rates in [start, end] in one call (for backfill).
    Weekends/holidays are simply absent — use rate_for_date to bridge them."""
    data = _get_json(f"{BASE_URL}/{start.isoformat()}..{end.isoformat()}?base={base}&symbols={quote}")
    if not isinstance(data, dict):
        return {}
    out: dict[date, int] = {}
    for day_str, day_rates in (data.get("rates") or {}).items():
        micro = _to_micro((day_rates or {}).get(quote))
        if micro is None:
            continue
        try:
            out[date.fromisoformat(day_str)] = micro
        except ValueError:
            continue
    return out


def rate_for_date(rates: dict[date, int], d: date, *, max_back: int = 7) -> int | None:
    """Rate for `d`, walking back to the nearest prior business day (≤ max_back days)."""
    for i in range(max_back + 1):
        r = rates.get(d - timedelta(days=i))
        if r:
            return r
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_live.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/fx_live.py tests/test_fx_live.py
git commit -m "feat(fx): frankfurter live-rate client (stdlib, never raises)"
```

---

### Task 3: snapshot helper in `services/fx.py` + offline-tests guard

**Files:**
- Modify: `src/khata/services/fx.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_fx_snapshot.py` (extend)

- [ ] **Step 1: Add the autouse no-network fixture FIRST**

Append to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _no_live_fx(monkeypatch):
    """Tests never hit frankfurter. Patch the fx module's reference (not fx_live
    itself) so the snapshot hot path gets None while test_fx_live.py still
    exercises the real client. Tests that want live behavior monkeypatch
    khata.services.fx.fx_live themselves (test-body patches win)."""
    import khata.services.fx as _fx

    class _Stub:
        @staticmethod
        def fetch_rate(*a, **k):
            return None

        @staticmethod
        def fetch_latest(*a, **k):
            return None

        @staticmethod
        def fetch_range(*a, **k):
            return {}

    monkeypatch.setattr(_fx, "fx_live", _Stub())
```

(This references `fx.fx_live`, added in Step 3 — fine, the fixture lands in the same task.)

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_fx_snapshot.py`:

```python
from khata.models import LedgerEntry as LE
from khata.services import fx
from khata.services.fx import counter_currency_for, set_rate, snapshot_entry_rate


def _entry(s, u, plan, currency="INR"):
    e = LE(plan_id=plan.id, logged_by_user_id=u.id, direction="out",
           amount_minor=5_000_000, currency=currency, occurred_at=_dt())
    s.add(e)
    s.flush()
    return e


def test_counter_currency_for():
    assert counter_currency_for("INR") == "USD"
    assert counter_currency_for("USD") == "INR"


def test_snapshot_explicit_rate_wins(ctx, monkeypatch):
    s, u, plan = ctx
    monkeypatch.setattr(fx.fx_live, "fetch_rate", lambda *a, **k: 99_999)  # must be ignored
    e = _entry(s, u, plan)
    snapshot_entry_rate(s, e, explicit_rate_micro=11_364)
    assert e.fx_rate_micro == 11_364
    assert e.fx_counter_currency == "USD"


def test_snapshot_live_wins_over_stored(ctx, monkeypatch):
    s, u, plan = ctx
    seen = {}

    def fake_fetch(d, base, quote):
        seen["args"] = (d, base, quote)
        return 11_364

    monkeypatch.setattr(fx.fx_live, "fetch_rate", fake_fetch)
    set_rate(s, base="INR", quote="USD", rate_micro=90_000_000, as_of=_dt())  # stored manual
    e = _entry(s, u, plan)  # INR entry
    snapshot_entry_rate(s, e)
    assert e.fx_rate_micro == 11_364                      # live, not derived-from-stored
    assert e.fx_counter_currency == "USD"
    # frankfurter direction: base=entry currency, quote=counter, at occurred_at date
    assert seen["args"] == (_dt().date(), "INR", "USD")


def test_snapshot_stored_fallback_inverts_to_counter_per_entry(ctx):
    s, u, plan = ctx
    # autouse fixture: live returns None. Stored canonical row: ₹80 per $1.
    set_rate(s, base="INR", quote="USD", rate_micro=80_000_000, as_of=_dt())
    e = _entry(s, u, plan)  # INR entry, counter USD → USD-per-INR = 1e12/80e6 = 12_500
    snapshot_entry_rate(s, e)
    assert e.fx_rate_micro == 12_500
    assert e.fx_counter_currency == "USD"


def test_snapshot_all_fail_leaves_null(ctx):
    s, u, plan = ctx
    e = _entry(s, u, plan)  # no live (autouse), no stored rate
    snapshot_entry_rate(s, e)
    assert e.fx_rate_micro is None
    assert e.fx_counter_currency is None


def test_snapshot_usd_entry_gets_inr_counter(ctx):
    s, u, plan = ctx
    set_rate(s, base="INR", quote="USD", rate_micro=88_000_000, as_of=_dt())
    e = _entry(s, u, plan, currency="USD")  # counter INR → INR-per-USD = stored row direct
    snapshot_entry_rate(s, e)
    assert e.fx_rate_micro == 88_000_000
    assert e.fx_counter_currency == "INR"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_snapshot.py -v`
Expected: new tests FAIL — `ImportError: cannot import name 'counter_currency_for'`.

- [ ] **Step 4: Implement in `src/khata/services/fx.py`**

Add `from . import fx_live` to the imports (after `from ..money import SUPPORTED_CURRENCIES`), then append:

```python
def counter_currency_for(currency: str) -> str:
    """The other member of SUPPORTED_CURRENCIES. Two-currency assumption lives
    HERE only (spec §3): if support grows, this becomes the user's base currency."""
    others = SUPPORTED_CURRENCIES - {(currency or "").upper()}
    return next(iter(others))


def snapshot_entry_rate(session: Session, entry, explicit_rate_micro: int | None = None) -> None:
    """Stamp entry.fx_rate_micro / fx_counter_currency (counter-per-entry ×1e6).
    Fallback chain: explicit client rate > frankfurter at occurred_at date >
    stored manual rate (inverted to entry→counter) > None. Never raises —
    entry creation must not block on FX (spec §3, §9)."""
    counter = counter_currency_for(entry.currency)
    rate = int(explicit_rate_micro) if explicit_rate_micro else None
    if rate is None:
        try:
            rate = fx_live.fetch_rate(entry.occurred_at.date(),
                                      base=entry.currency, quote=counter)
        except Exception:
            rate = None
    if rate is None:
        # get_rate(X, Y) = X-per-Y; counter-per-entry = get_rate(counter, entry ccy).
        # Handles inversion of the canonical INR/USD row internally.
        rate = get_rate(session, counter, entry.currency)
    if rate:
        entry.fx_rate_micro = rate
        entry.fx_counter_currency = counter
```

- [ ] **Step 5: Run tests, then full suite**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_snapshot.py tests/test_fx_live.py -v` → all PASS.
Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q` → all pass (autouse fixture must not break anything).

- [ ] **Step 6: Commit**

```bash
git add src/khata/services/fx.py tests/conftest.py tests/test_fx_snapshot.py
git commit -m "feat(fx): snapshot_entry_rate fallback chain + offline-test guard"
```

---

### Task 4: hook snapshot into all five entry-creation paths

**Files:**
- Modify: `src/khata/services/assets.py` (`log_payment`, ~line 60)
- Modify: `src/khata/services/holdings.py` (`_add_entry` + `add_buy`/`add_sell`, ~lines 45–78)
- Modify: `src/khata/services/loans.py` (`add_disbursement` ~line 137, `log_loan_entry` ~line 152)
- Modify: `src/khata/services/chits.py` (`log_chit_entry`, ~line 52)
- Test: `tests/test_fx_snapshot.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fx_snapshot.py`:

```python
from datetime import date

from khata.services.assets import log_payment
from khata.services.chits import create_chit_plan, log_chit_entry
from khata.services.holdings import add_buy, create_holding_plan
from khata.services.loans import add_disbursement, create_loan_plan, log_loan_entry


def test_log_payment_snapshots(ctx):
    s, u, plan = ctx
    set_rate(s, base="INR", quote="USD", rate_micro=80_000_000, as_of=_dt())
    e = log_payment(s, plan=plan, user_id=u.id, amount_minor=100, occurred_at=_dt(),
                    method="upi", funding_source="savings")
    assert e.fx_rate_micro == 12_500          # stored-rate fallback, USD-per-INR
    assert e.fx_counter_currency == "USD"


def test_log_payment_explicit_rate(ctx):
    s, u, plan = ctx
    e = log_payment(s, plan=plan, user_id=u.id, amount_minor=100, occurred_at=_dt(),
                    method="upi", funding_source="savings", fx_rate_micro=11_111)
    assert e.fx_rate_micro == 11_111


def test_holding_buy_snapshots(ctx):
    s, u, _ = ctx
    set_rate(s, base="INR", quote="USD", rate_micro=80_000_000, as_of=_dt())
    hp = create_holding_plan(s, owner_id=u.id, name="Gold", currency="INR",
                             asset_class="gold", unit="gram")
    e = add_buy(s, plan=hp, user_id=u.id, quantity_micro=1_000_000,
                amount_minor=700_000, occurred_at=_dt())
    assert e.fx_rate_micro == 12_500
    assert e.fx_counter_currency == "USD"


def test_loan_entries_snapshot(ctx):
    s, u, _ = ctx
    set_rate(s, base="INR", quote="USD", rate_micro=80_000_000, as_of=_dt())
    lp = create_loan_plan(s, owner_id=u.id, name="GL", currency="INR", direction="taken",
                          interest_type="none", rate_bps=0, start_date=date(2026, 1, 1))
    d = add_disbursement(s, plan=lp, user_id=u.id, amount_minor=10_000_000, occurred_at=_dt())
    r = log_loan_entry(s, plan=lp, user_id=u.id, kind="principal_repayment",
                       amount_minor=1_000_000, occurred_at=_dt())
    assert d.fx_rate_micro == 12_500 and d.fx_counter_currency == "USD"
    assert r.fx_rate_micro == 12_500 and r.fx_counter_currency == "USD"


def test_chit_entry_snapshots(ctx):
    s, u, _ = ctx
    set_rate(s, base="INR", quote="USD", rate_micro=80_000_000, as_of=_dt())
    cp = create_chit_plan(s, owner_id=u.id, name="Chit", currency="INR",
                          chit_value_minor=100_000_000, n_members=20,
                          commission_bps=500, start_date=date(2026, 1, 1))
    e = log_chit_entry(s, plan=cp, user_id=u.id, kind="chit_contribution",
                       amount_minor=500_000, occurred_at=_dt())
    assert e.fx_rate_micro == 12_500
    assert e.fx_counter_currency == "USD"
```

NOTE for implementer: check the real signatures of `create_holding_plan` / `create_chit_plan` / `create_loan_plan` in their service modules before running — match required kwargs exactly (e.g. holding may need `symbol`/`purity`, chit takes those five kwargs per `chits.py:45-50`). Adjust the test setup lines (NOT the assertions) to the real signatures.

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_snapshot.py -v`
Expected: new tests FAIL — entries have `fx_rate_micro is None` (no hook yet) and `log_payment` rejects `fx_rate_micro=` kwarg.

- [ ] **Step 3: Add hooks (each: accept `fx_rate_micro=None`, call snapshot after construction, before return)**

`src/khata/services/assets.py` — `log_payment`: add `fx_rate_micro=None` to the signature (after `funding_plan_id=None`), and between `session.add(entry)` and `session.flush()` insert nothing; after `session.flush()` and before `return entry` add:

```python
    fx.snapshot_entry_rate(session, entry, explicit_rate_micro=fx_rate_micro)
```

Add `from . import fx` to assets.py imports if not already present.

`src/khata/services/holdings.py` — `_add_entry`: add `fx_rate_micro=None` to its keyword params; after `session.flush()` and before `return entry`:

```python
    fx.snapshot_entry_rate(session, entry, explicit_rate_micro=fx_rate_micro)
```

`add_buy` and `add_sell`: add `fx_rate_micro=None` param and pass `fx_rate_micro=fx_rate_micro` through to `_add_entry`. Add `from . import fx` to holdings.py imports.

`src/khata/services/loans.py` — `add_disbursement` and `log_loan_entry`: add `fx_rate_micro=None` param to each; after each `session.flush()`, before `return entry`:

```python
    fx.snapshot_entry_rate(session, entry, explicit_rate_micro=fx_rate_micro)
```

Add `from . import fx` to loans.py imports.

`src/khata/services/chits.py` — `log_chit_entry`: same pattern (`fx_rate_micro=None` param, snapshot call after flush). Add `from . import fx` to chits.py imports.

(Import note: if any of these modules already do `from . import fx` or `from .fx import ...`, reuse what's there — don't double-import.)

- [ ] **Step 4: Run tests + full suite**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_snapshot.py -v` → PASS.
Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q` → all pass (existing tests get NULL snapshots — autouse fixture returns None and no stored rate exists in most fixtures, which is fine because columns are nullable).

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/assets.py src/khata/services/holdings.py src/khata/services/loans.py src/khata/services/chits.py tests/test_fx_snapshot.py
git commit -m "feat(fx): snapshot rate on every entry-creation path"
```

---

### Task 5: API — optional explicit `fx_rate_micro` on create (422 invalid)

**Files:**
- Modify: `src/khata/api/plans.py` (helpers ~line 30; handlers at `payments` :327, `holding/buys` :538, `holding/sells` :563, `loan/entries` :689, `chit/entries` :714)
- Test: `tests/test_plans_api.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plans_api.py` (reuse its existing `client` fixture and `_register` helper):

```python
def test_payment_with_explicit_fx_rate(client):
    _register(client)
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1,00,000"}).get_json()["plan"]["id"]
    r = client.post(f"/api/plans/{pid}/payments", json={
        "amount": "50,000", "method": "upi", "funding_source": "savings",
        "fx_rate_micro": 11_364})
    assert r.status_code == 201
    state = r.get_json()["state"]
    row = state["ledger"][0]
    assert row["fx_rate_micro"] == 11_364
    assert row["fx_counter_currency"] == "USD"


def test_payment_invalid_fx_rate_is_422(client):
    _register(client)
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1,00,000"}).get_json()["plan"]["id"]
    for bad in (0, -5, "88", 1.5, True):
        r = client.post(f"/api/plans/{pid}/payments", json={
            "amount": "1,000", "method": "upi", "funding_source": "savings",
            "fx_rate_micro": bad})
        assert r.status_code == 422, f"{bad!r} should be 422, got {r.status_code}"
```

(The first test asserts on serialized `fx_rate_micro` — serialization lands in Task 7. Until then assert via DB if needed; simplest is to implement Tasks 5–7 in order and run this test after Task 7. To keep TDD honest NOW, assert `r.status_code == 201` only, and add the two `row[...]` assertions in Task 7.)

- [ ] **Step 2: Run tests to verify the 422 test fails**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_plans_api.py -k fx_rate -v`
Expected: 422 test FAILS (unknown JSON keys are ignored today → 201).

- [ ] **Step 3: Implement**

In `src/khata/api/plans.py`, after `_parse_dt` (~line 33), add:

```python
class _FxRateArgError(ValueError):
    """Invalid explicit fx_rate_micro — maps to 422 (not the generic 400)."""


def _fx_rate_arg(data):
    """Optional explicit snapshot rate from the client: a positive int
    (counter-per-entry ×1e6) or None. bool is an int in Python — reject it."""
    v = data.get("fx_rate_micro")
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise _FxRateArgError("fx_rate_micro must be a positive integer (×1e6)")
    return v
```

Then in each of the five create handlers, pass the parsed value through and catch the new error FIRST (it subclasses ValueError, so its `except` must precede the generic one). Pattern, shown for `payment` (apply identically to the other four):

```python
    try:
        amount = to_minor(data.get("amount", ""), plan.currency)
        occurred = _parse_dt(data.get("occurred_at"))
        entry = assets.log_payment(
            g.db, plan=plan, user_id=_payer_uid(plan, data, user.id), amount_minor=amount, occurred_at=occurred,
            method=data.get("method", ""), funding_source=data.get("funding_source", ""),
            proof_ref=data.get("proof_ref"), note=data.get("note"), acting_user_id=user.id,
            funding_plan_id=_funding_plan_id(data, user),
            fx_rate_micro=_fx_rate_arg(data))
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
```

For the other four handlers, add `fx_rate_micro=_fx_rate_arg(data)` to the service call (`holdings.add_buy`, `holdings.add_sell`, `loans.log_loan_entry`, `chits.log_chit_entry`) and the same `except _FxRateArgError` block before each handler's existing generic except. (`loan/disbursements` POST, if present, gets the same treatment — check for a `add_disbursement` API call site with `grep -n "add_disbursement" src/khata/api/plans.py` and wire it too.)

- [ ] **Step 4: Run tests + full suite**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_plans_api.py -q` then `-q` full suite.
Expected: all pass (fx-row assertions deferred to Task 7 if you took that option).

- [ ] **Step 5: Commit**

```bash
git add src/khata/api/plans.py tests/test_plans_api.py
git commit -m "feat(fx): accept explicit fx_rate_micro on entry creation (422 invalid)"
```

---

### Task 6: PATCH — edit the snapshot rate

**Files:**
- Modify: `src/khata/services/assets.py` (`update_ledger_entry`, ~line 81)
- Modify: `src/khata/api/plans.py` (`update_entry`, ~line 355)
- Test: `tests/test_fx_snapshot.py` + `tests/test_plans_api.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fx_snapshot.py`:

```python
from khata.services.assets import update_ledger_entry


def test_update_entry_rate_only_leaves_amount_and_status(ctx):
    s, u, plan = ctx
    e = log_payment(s, plan=plan, user_id=u.id, amount_minor=100, occurred_at=_dt(),
                    method="upi", funding_source="savings")
    assert e.amount_status == "agreed"
    update_ledger_entry(s, plan=plan, entry_id=e.id, acting_user_id=u.id,
                        fx_rate_micro=22_222)
    assert e.fx_rate_micro == 22_222
    assert e.fx_counter_currency == "USD"   # set even when creation left it NULL
    assert e.amount_minor == 100            # untouched
    assert e.amount_status == "agreed"      # rate edit never re-opens confirmation
```

Append to `tests/test_plans_api.py`:

```python
def test_patch_entry_fx_rate(client):
    _register(client)
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1,00,000"}).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/payments", json={
        "amount": "1,000", "method": "upi", "funding_source": "savings"})
    eid = client.get(f"/api/plans/{pid}").get_json()["state"]["ledger"][0]["id"]
    r = client.patch(f"/api/plans/{pid}/entries/{eid}", json={"fx_rate_micro": 11_364})
    assert r.status_code == 200
    assert client.patch(f"/api/plans/{pid}/entries/{eid}",
                        json={"fx_rate_micro": -1}).status_code == 422
    assert client.patch(f"/api/plans/{pid}/entries/{eid}",
                        json={"fx_rate_micro": "x"}).status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_snapshot.py::test_update_entry_rate_only_leaves_amount_and_status tests/test_plans_api.py::test_patch_entry_fx_rate -v`
Expected: FAIL — `update_ledger_entry` rejects the kwarg / PATCH ignores the key.

- [ ] **Step 3: Implement**

`src/khata/services/assets.py` — `update_ledger_entry`: add `fx_rate_micro=None` to the signature (after `funding_plan_id=_UNSET`); insert before the `if amount_changed or attrib_changed:` block:

```python
    if fx_rate_micro is not None:
        # rate is metadata about the entry — editing it never touches amount,
        # amount_status, or the confirmation loop (spec §4)
        entry.fx_rate_micro = fx_rate_micro
        entry.fx_counter_currency = fx.counter_currency_for(entry.currency)
```

`src/khata/api/plans.py` — `update_entry` (~line 372, inside the `fields` build):

```python
        if "fx_rate_micro" in data:
            fields["fx_rate_micro"] = _fx_rate_arg(data)
```

and add the same `except _FxRateArgError → 422` arm before this handler's generic except.

- [ ] **Step 4: Run tests + full suite, commit**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q` → all pass.

```bash
git add src/khata/services/assets.py src/khata/api/plans.py tests/test_fx_snapshot.py tests/test_plans_api.py
git commit -m "feat(fx): editable snapshot rate via entry PATCH"
```

---

### Task 7: serialization — fx fields + derived counter value in ledger arrays

**Files:**
- Modify: `src/khata/services/assets.py` (`asset_state` ledger dict, ~line 315)
- Modify: `src/khata/services/loans.py` (`loan_state` ledger dict, ~line 473)
- Modify: `src/khata/services/chits.py` (`chit_state` ledger dict, ~line 108)
- Test: `tests/test_fx_snapshot.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fx_snapshot.py`:

```python
from khata.services.assets import asset_state


def test_asset_state_ledger_exposes_fx_fields(ctx):
    s, u, plan = ctx
    e = log_payment(s, plan=plan, user_id=u.id, amount_minor=5_000_000, occurred_at=_dt(),
                    method="upi", funding_source="savings", fx_rate_micro=11_364)
    log_payment(s, plan=plan, user_id=u.id, amount_minor=100, occurred_at=_dt(),
                method="upi", funding_source="savings")  # NULL-rate row
    rows = {r["id"]: r for r in asset_state(s, plan)["ledger"]}
    snap = rows[e.id]
    assert snap["fx_rate_micro"] == 11_364
    assert snap["fx_counter_currency"] == "USD"
    # ₹50,000.00 × 0.011364 = $568.20 → 56_820 USD-minor (Decimal ROUND_HALF_UP)
    assert snap["counter_value_minor"] == 56_820
    null_row = next(r for r in rows.values() if r["id"] != e.id)
    assert null_row["fx_rate_micro"] is None
    assert null_row["fx_counter_currency"] is None
    assert null_row["counter_value_minor"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_snapshot.py::test_asset_state_ledger_exposes_fx_fields -v`
Expected: FAIL — `KeyError: 'fx_rate_micro'`.

- [ ] **Step 3: Add the three fields to all three ledger dicts**

In each of the three ledger list-comprehension dicts (`assets.py` asset_state, `loans.py` loan_state, `chits.py` chit_state), add:

```python
         "fx_rate_micro": e.fx_rate_micro, "fx_counter_currency": e.fx_counter_currency,
         "counter_value_minor": (fx.convert(e.amount_minor, rate_micro=e.fx_rate_micro)
                                 if e.fx_rate_micro else None),
```

(`from . import fx` already added to all three modules in Task 4.)

- [ ] **Step 4: Run test + full suite + manual loan/chit check**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q` → all pass.
Then verify loan + chit dicts compile and serve by running their existing API tests explicitly:
`/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_chits_api.py tests/test_loan_service.py tests/test_plans_api.py -q` → pass.
Also NOW add the deferred assertions from Task 5 Step 1 (`row["fx_rate_micro"] == 11_364`, `row["fx_counter_currency"] == "USD"`) if they were deferred, and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/assets.py src/khata/services/loans.py src/khata/services/chits.py tests/test_fx_snapshot.py tests/test_plans_api.py
git commit -m "feat(fx): serialize snapshot rate + derived counter value in ledgers"
```

---

### Task 8: conversion policy — dashboard "paid" uses per-entry rates

**Files:**
- Modify: `src/khata/services/dashboard.py` (lines 27–51)
- Test: `tests/test_dashboard_service.py` (extend)

Loans stay at the current rate (outstanding includes computed accrued interest — not a pure entry sum, spec §5). Net worth (`networth.py`) is all spot/current-rate figures — **no change**. Only the dashboard asset "paid" loop is a pure ledger-entry sum.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dashboard_service.py`:

```python
def test_paid_uses_per_entry_snapshot_with_null_fallback(ctx):
    s, u = ctx
    from khata.services.fx import set_rate
    # current stored rate: ₹90 per $1 — used ONLY for the NULL-rate entry
    set_rate(s, base="INR", quote="USD", rate_micro=90_000_000, as_of=_dt())
    plan = create_asset_plan(s, owner_id=u.id, name="US thing", currency="USD",
                             total_price_minor=100_000)
    # $100 with a historical snapshot of ₹80/$ → ₹8,000.00 = 800_000 INR-minor
    log_payment(s, plan=plan, user_id=u.id, amount_minor=10_000, occurred_at=_dt(),
                method="upi", funding_source="savings", fx_rate_micro=80_000_000)
    # $100 with no snapshot → current rate ₹90/$ → ₹9,000.00 = 900_000
    log_payment(s, plan=plan, user_id=u.id, amount_minor=10_000, occurred_at=_dt(),
                method="upi", funding_source="savings")
    s.commit()
    d = net_position(s, u.id)   # user base currency is INR (default)
    assert d["paid_to_date_minor"] == 800_000 + 900_000


def test_paid_same_currency_ignores_snapshot(ctx):
    s, u = ctx
    plan = create_asset_plan(s, owner_id=u.id, name="Plot", currency="INR",
                             total_price_minor=50_000_000)
    # INR entry with a USD snapshot — base is INR, so the amount passes through raw
    log_payment(s, plan=plan, user_id=u.id, amount_minor=10_000_000, occurred_at=_dt(),
                method="upi", funding_source="savings", fx_rate_micro=11_364)
    s.commit()
    assert net_position(s, u.id)["paid_to_date_minor"] == 10_000_000
```

(If `User` defaults `base_currency` to something else, set `u.base_currency = "INR"` in the test before `net_position` — check `models/user.py`.)

- [ ] **Step 2: Run tests to verify the first fails**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_dashboard_service.py -k snapshot -v`
Expected: first test FAILS — both entries convert at ₹90 today → `1_800_000 != 1_700_000`.

- [ ] **Step 3: Implement in `src/khata/services/dashboard.py`**

After the existing `_add` closure, add a per-entry sibling:

```python
    def _add_entry(field: str, e):
        """Per-entry conversion (spec §5): same-currency passthrough; else the
        entry's own snapshot when it targets base; else the current stored rate
        (exactly the old behavior — NULL-rate entries don't regress)."""
        if e.currency == base:
            totals[field] += e.amount_minor
            return
        if e.fx_rate_micro and e.fx_counter_currency == base:
            totals[field] += fx.convert(e.amount_minor, rate_micro=e.fx_rate_micro)
            return
        _add(field, e.currency, e.amount_minor)
```

And change the "paid" loop (lines 47–51) from `_add("paid", p.currency, e.amount_minor)` to:

```python
    for p in owned + member:
        if p.type == "asset":
            for e in p.ledger_entries:
                if e.direction == "out" and e.logged_by_user_id == user_id:
                    _add_entry("paid", e)
```

- [ ] **Step 4: Run tests + full suite, commit**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q` → all pass.

```bash
git add src/khata/services/dashboard.py tests/test_dashboard_service.py
git commit -m "feat(fx): dashboard paid-to-date converts per-entry snapshot rates"
```

---

### Task 9: daily refresh — scheduler job + atomic claim

**Files:**
- Modify: `src/khata/services/fx.py` (claim helpers)
- Modify: `src/khata/scheduler.py`
- Test: `tests/test_fx_scheduler.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fx_scheduler.py`:

```python
from datetime import datetime

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.services import fx


@pytest.fixture
def s():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as sess:
        yield sess


def test_claim_once_per_day(s):
    now = datetime(2026, 6, 11, 9, 0)
    assert fx.claim_daily_refresh(s, now=now) is True       # first caller wins
    assert fx.claim_daily_refresh(s, now=now) is False      # same day → already claimed
    nxt = datetime(2026, 6, 12, 0, 5)
    assert fx.claim_daily_refresh(s, now=nxt) is True       # new day → claimable again


def test_release_claim_allows_retry(s):
    now = datetime(2026, 6, 11, 9, 0)
    prev = fx.refresh_last_run(s)                            # None on a fresh DB
    assert fx.claim_daily_refresh(s, now=now) is True
    fx.release_refresh_claim(s, previous=prev)               # fetch failed → give back
    assert fx.claim_daily_refresh(s, now=now) is True        # retry same day succeeds


def test_fx_tick_stores_canonical_inr_per_usd(s, monkeypatch):
    """_fx_tick end-to-end: claim → fetch_latest(USD,INR) → set_rate(INR,USD)."""
    import khata.scheduler as sched

    class _App:
        config = {}
    # fake session factory returning OUR session (context-manager protocol)
    class _SF:
        def __call__(self):
            return self
        def __enter__(self):
            return s
        def __exit__(self, *a):
            return False
    _App.config["SESSION_FACTORY"] = _SF()
    monkeypatch.setattr(sched, "fx_live", type("L", (), {
        "fetch_latest": staticmethod(lambda base, quote: 88_120_000)}))
    sched._fx_tick(_App())
    assert fx.get_rate(s, "INR", "USD") == 88_120_000        # canonical direction


def test_fx_tick_failure_keeps_old_rate_and_releases_claim(s, monkeypatch):
    import khata.scheduler as sched
    from datetime import datetime as dt, timezone
    fx.set_rate(s, base="INR", quote="USD", rate_micro=80_000_000,
                as_of=dt(2026, 6, 10, tzinfo=timezone.utc))
    s.commit()

    class _App:
        config = {}
    class _SF:
        def __call__(self):
            return self
        def __enter__(self):
            return s
        def __exit__(self, *a):
            return False
    _App.config["SESSION_FACTORY"] = _SF()
    monkeypatch.setattr(sched, "fx_live", type("L", (), {
        "fetch_latest": staticmethod(lambda base, quote: None)}))
    sched._fx_tick(_App())
    assert fx.get_rate(s, "INR", "USD") == 80_000_000        # old rate kept
    assert fx.claim_daily_refresh(s, now=datetime(2026, 6, 11, 10, 0)) is True  # retryable
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_scheduler.py -v`
Expected: FAIL — `AttributeError: module 'khata.services.fx' has no attribute 'claim_daily_refresh'`.

- [ ] **Step 3: Implement claim helpers in `services/fx.py`**

Add imports: extend the existing sqlalchemy import to `from sqlalchemy import or_, select, update`, add `from datetime import datetime` and `FxRefreshState` to the models import. Append:

```python
def _refresh_state(session: Session) -> "FxRefreshState":
    """Get-or-create the single claim row (id=1). create_all'd DBs have no seed row."""
    row = session.get(FxRefreshState, 1)
    if row is None:
        row = FxRefreshState(id=1)
        session.add(row)
        session.commit()
    return row


def refresh_last_run(session: Session) -> "datetime | None":
    return _refresh_state(session).last_run_at


def claim_daily_refresh(session: Session, *, now: datetime) -> bool:
    """Atomically claim today's live-FX refresh (mirrors backup_store.claim_due):
    the UPDATE's WHERE makes exactly one concurrent caller win per calendar day."""
    _refresh_state(session)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    res = session.execute(
        update(FxRefreshState).where(
            FxRefreshState.id == 1,
            or_(FxRefreshState.last_run_at.is_(None),
                FxRefreshState.last_run_at < start_of_day),
        ).values(last_run_at=now))
    session.commit()
    return res.rowcount == 1


def release_refresh_claim(session: Session, *, previous) -> None:
    """Give the slot back after a failed fetch so a later hourly tick retries today."""
    session.execute(update(FxRefreshState).where(FxRefreshState.id == 1)
                    .values(last_run_at=previous))
    session.commit()
```

- [ ] **Step 4: Implement `_fx_tick` in `scheduler.py`**

Change the import line to `from .services import backup_store, fx, fx_live` and add `timezone` to the datetime import. Append after `_tick`:

```python
def _fx_tick(app) -> None:
    """Once per UTC day (hourly checks, atomic claim): refresh the canonical
    INR/USD rate from frankfurter. fetch_latest("USD","INR") returns INR-per-USD
    (frankfurter is quote-per-base); the canonical FxRate row is base=INR,
    quote=USD (base-per-quote) — same number, stored Settings-compatible.
    Fetch failure → release the claim (retry next hour) and keep the old rate."""
    SessionLocal = app.config["SESSION_FACTORY"]
    now = datetime.now()
    with SessionLocal() as s:
        try:
            prev = fx.refresh_last_run(s)
            if not fx.claim_daily_refresh(s, now=now):
                return
            rate = fx_live.fetch_latest("USD", "INR")
            if rate:
                fx.set_rate(s, base="INR", quote="USD", rate_micro=rate,
                            as_of=datetime.now(timezone.utc))
                s.commit()
            else:
                fx.release_refresh_claim(s, previous=prev)
        except Exception:        # never let an FX error kill the scheduler thread
            s.rollback()
```

In `start_scheduler`, after the auto-backup `add_job`, add:

```python
    sched.add_job(lambda: _fx_tick(app), "interval", minutes=60, id="fx-refresh",
                  next_run_time=datetime.now() + timedelta(seconds=75),
                  max_instances=1, coalesce=True)
```

- [ ] **Step 5: Run tests + full suite, commit**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_scheduler.py -v` then full `-q` → all pass.

```bash
git add src/khata/services/fx.py src/khata/scheduler.py tests/test_fx_scheduler.py
git commit -m "feat(fx): daily live-rate refresh with atomic cross-worker claim"
```

---

### Task 10: backfill — `POST /api/admin/fx-backfill`

**Files:**
- Modify: `src/khata/api/admin.py`
- Test: `tests/test_fx_backfill_api.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fx_backfill_api.py` (admin bootstrap: copy the registration/admin-promotion pattern from the top of `tests/test_admin_api.py` — reuse its helper verbatim if one exists):

```python
from datetime import date

import pytest

from khata import create_app
from khata.config import Config


@pytest.fixture
def client():
    cfg = Config()
    cfg.database_url = "sqlite:///:memory:"
    cfg.testing = True
    app = create_app(cfg)
    app.config["TESTING"] = True
    return app.test_client()


def _make_admin(client):
    """Register a user and promote to admin. MIRROR tests/test_admin_api.py's
    setup exactly (it knows how the first admin is seeded in this codebase)."""
    r = client.post("/api/auth/register", json={
        "email": "a@b.com", "password": "pw12345678", "display_name": "A"})
    assert r.status_code in (200, 201)
    # promotion mechanism per test_admin_api.py — adjust to match it
    return r


def test_backfill_requires_admin(client):
    client.post("/api/auth/register", json={
        "email": "x@b.com", "password": "pw12345678", "display_name": "X"})
    assert client.post("/api/admin/fx-backfill").status_code == 403


def test_backfill_fills_nulls_idempotently(client, monkeypatch):
    _make_admin(client)
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1,00,000"}).get_json()["plan"]["id"]
    # Saturday-dated entry → must take Friday's rate
    client.post(f"/api/plans/{pid}/payments", json={
        "amount": "1,000", "method": "upi", "funding_source": "savings",
        "occurred_at": "2026-06-06T12:00:00+00:00"})
    # entry that already has a rate → must be skipped
    client.post(f"/api/plans/{pid}/payments", json={
        "amount": "2,000", "method": "upi", "funding_source": "savings",
        "occurred_at": "2026-06-05T12:00:00+00:00", "fx_rate_micro": 99_999})

    import khata.api.admin as admin_api
    monkeypatch.setattr(admin_api.fx_live, "fetch_range",
                        lambda start, end, base, quote: {date(2026, 6, 5): 88_000_000})

    r = client.post("/api/admin/fx-backfill")
    assert r.status_code == 200
    body = r.get_json()
    assert body == {"filled": 1, "skipped": 1, "no_rate": 0}

    ledger = client.get(f"/api/plans/{pid}").get_json()["state"]["ledger"]
    by_amt = {row["amount_minor"]: row for row in ledger}
    # INR entry: counter USD → USD-per-INR = inverse of ₹88/$ = 11_364 micro
    assert by_amt[100_000]["fx_rate_micro"] == 11_364
    assert by_amt[100_000]["fx_counter_currency"] == "USD"
    assert by_amt[200_000]["fx_rate_micro"] == 99_999      # untouched

    # idempotent re-run: nothing left to fill
    r2 = client.post("/api/admin/fx-backfill")
    assert r2.get_json() == {"filled": 0, "skipped": 2, "no_rate": 0}


def test_backfill_frankfurter_down_counts_no_rate(client, monkeypatch):
    _make_admin(client)
    pid = client.post("/api/plans", json={
        "name": "P", "currency": "INR", "total_price": "1,00,000"}).get_json()["plan"]["id"]
    client.post(f"/api/plans/{pid}/payments", json={
        "amount": "1,000", "method": "upi", "funding_source": "savings"})
    import khata.api.admin as admin_api
    monkeypatch.setattr(admin_api.fx_live, "fetch_range", lambda *a, **k: {})
    r = client.post("/api/admin/fx-backfill")
    assert r.get_json() == {"filled": 0, "skipped": 0, "no_rate": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_backfill_api.py -v`
Expected: FAIL — 404 on `/api/admin/fx-backfill` (route missing). Fix `_make_admin` against `test_admin_api.py`'s pattern first if registration/promotion differs.

- [ ] **Step 3: Implement in `src/khata/api/admin.py`**

Add imports: `from decimal import Decimal, ROUND_HALF_UP`, `from sqlalchemy import select`, `from ..models import LedgerEntry`, and extend the services import to `from ..services import admin, backup_store, fx, fx_live`. Append:

```python
@bp.post("/fx-backfill")
def fx_backfill():
    """One-time idempotent FX backfill: stamp every NULL-rate ledger entry with
    the frankfurter rate of its occurred_at date (weekend → nearest prior
    business day). PROD DB WRITE — run manually, once, with explicit user
    authorization (spec §7). Safe to re-run: non-NULL entries are skipped."""
    _, err = _require_admin()
    if err:
        return err
    skipped = g.db.scalar(
        select(LedgerEntry.id).where(LedgerEntry.fx_rate_micro.is_not(None)).limit(1))
    skipped = len(g.db.scalars(
        select(LedgerEntry.id).where(LedgerEntry.fx_rate_micro.is_not(None))).all())
    entries = g.db.scalars(
        select(LedgerEntry).where(LedgerEntry.fx_rate_micro.is_(None))).all()
    if not entries:
        return jsonify(filled=0, skipped=skipped, no_rate=0), 200
    days = sorted(e.occurred_at.date() for e in entries)
    # ONE range call: frankfurter base=USD → INR-per-USD per business day
    inr_per_usd = fx_live.fetch_range(days[0], days[-1], "USD", "INR")
    micro2 = fx_live.MICRO * fx_live.MICRO
    filled = no_rate = 0
    for e in entries:
        rate = fx_live.rate_for_date(inr_per_usd, e.occurred_at.date())
        if not rate or e.currency not in ("INR", "USD"):
            no_rate += 1
            continue
        if e.currency == "USD":
            e.fx_rate_micro = rate                      # counter INR-per-USD, direct
        else:
            # INR entry → counter USD-per-INR = inverse, exact Decimal
            e.fx_rate_micro = int((Decimal(micro2) / rate).quantize(
                Decimal(1), rounding=ROUND_HALF_UP))
        e.fx_counter_currency = fx.counter_currency_for(e.currency)
        filled += 1
    g.db.commit()
    return jsonify(filled=filled, skipped=skipped, no_rate=no_rate), 200
```

(Delete the stray first `skipped =` line — keep only the `len(...)` count. Shown here so the implementer doesn't reproduce it: final code has ONE `skipped` assignment.)

- [ ] **Step 4: Run tests + full suite, commit**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_fx_backfill_api.py -v` then full `-q`.

```bash
git add src/khata/api/admin.py tests/test_fx_backfill_api.py
git commit -m "feat(fx): admin fx-backfill endpoint (idempotent, weekend-safe)"
```

---

### Task 11: UI — fx line under ledger amounts (3 detail pages)

**Files:**
- Create: `src/khata/static/assets/fx.js`
- Modify: `src/khata/static/asset-detail.html` (renderLedger, after the amt-pct block ~line 432)
- Modify: `src/khata/static/loan-detail.html` (renderLedger, after `amt.append(amtSpan(signed));` ~line 555)
- Modify: `src/khata/static/chit-detail.html` (renderLedger, after `amt.append(aw);` ~line 590)

No JS test harness exists for static pages; verify headless per repo memory rule (Step 4).

- [ ] **Step 1: Create `src/khata/static/assets/fx.js`**

```javascript
// FX snapshot helpers (spec docs/specs/2026-06-11-fx-snapshot-design.md §8).
// Server stores fx_rate_micro = counter-per-entry ×1e6 and derives
// counter_value_minor; these helpers only FORMAT — no money math beyond display.
(function(){
  const SYM = { INR: '₹', USD: '$' };

  // small mono line under a ledger amount: "$568.18 @ ₹88.00/$".
  // lr: serialized ledger row; entryCcy: the plan/entry currency (page BASE).
  // Returns an element, or null when the row has no snapshot.
  window.fxLine = function(lr, entryCcy){
    if(!lr || !lr.fx_rate_micro || !lr.fx_counter_currency || lr.counter_value_minor==null) return null;
    const es = SYM[(entryCcy||'').toUpperCase()] || entryCcy;
    const cs = SYM[lr.fx_counter_currency] || lr.fx_counter_currency;
    const v = Math.abs(lr.counter_value_minor);
    const val = cs + Math.floor(v/100).toLocaleString('en-US') + '.' + String(v%100).padStart(2,'0');
    // rate in natural direction — quote the side that is ≥ 1 (₹88.00/$, never $0.0114/₹)
    const r = lr.fx_rate_micro / 1e6;
    const rate = r >= 1 ? (cs + r.toFixed(2) + '/' + es) : (es + (1/r).toFixed(2) + '/' + cs);
    const line = document.createElement('span');
    line.textContent = val + ' @ ' + rate;
    line.style.cssText = 'display:block;font-family:"JetBrains Mono";font-weight:500;'
      + 'font-size:10.5px;color:var(--ink-faint);margin-top:3px;letter-spacing:.01em';
    return line;
  };

  // edit-form helpers: the form always shows the NATURAL rate (INR per USD, ≥1)
  // regardless of entry currency; storage is entry→counter micro.
  window.fxNaturalFromMicro = function(rateMicro, entryCcy){
    if(!rateMicro) return '';
    const r = (entryCcy === 'USD') ? rateMicro/1e6 : 1e6/rateMicro;
    return String(Math.round(r*10000)/10000);
  };
  window.fxMicroFromNatural = function(val, entryCcy){
    const r = parseFloat(String(val||'').replace(/,/g,''));
    if(!isFinite(r) || r <= 0) return null;
    return (entryCcy === 'USD') ? Math.round(r*1e6) : Math.round(1e6/r);
  };
})();
```

- [ ] **Step 2: Load fx.js + append the line on each page**

In all three of `asset-detail.html`, `loan-detail.html`, `chit-detail.html`: add `<script src="/static/assets/fx.js"></script>` immediately BEFORE the page's main inline `<script>` tag (next to the existing `/static/assets/*.js` includes — find with `grep -n 'assets/.*\.js' <file>`).

`asset-detail.html` — in `renderLedger`, directly after the amt-pct block (the `if(tot>0){...}` that appends `amt-pct`, before `row.append(amt);`):

```javascript
    const fxl = fxLine(lr, BASE);
    if(fxl) amt.append(fxl);
```

`loan-detail.html` — in `renderLedger`, after `amt.append(amtSpan(signed));` and before `lrow.append(amt);`:

```javascript
    const fxl = fxLine(it, BASE);
    if(fxl) amt.append(fxl);
```

`chit-detail.html` — in `renderLedger`, after `amt.append(aw);` and before the `if(e.id!=null){` edit-affordance block:

```javascript
    const fxl = fxLine(e, BASE);
    if(fxl) amt.append(fxl);
```

- [ ] **Step 3: Verify each page still references only defined globals**

Run: `grep -n "fxLine\|fx.js" src/khata/static/asset-detail.html src/khata/static/loan-detail.html src/khata/static/chit-detail.html`
Expected: each file shows one `fx.js` script tag and one `fxLine(` call site.

- [ ] **Step 4: Headless visual verification**

Start the app against a scratch DB and check the rendered line (repo rule: verify UI headless before "done"):

```bash
cd /private/tmp/khata-landing && KHATA_DATABASE_URL="sqlite:////tmp/fxui.db" \
  /Users/assistant/dev/active/khata/.venv/bin/python -m flask --app khata:create_app run --port 5099 &
sleep 2
# register, create INR asset plan, set manual rate, log payment with explicit fx_rate_micro,
# then load /asset/<id> with puppeteer/curl and confirm the "@" line renders.
```

(Use the existing puppeteer harness pattern from the responsive pass if available; otherwise curl the state API and confirm `fx_rate_micro` is present, then eyeball via `node -e` puppeteer screenshot.) Kill the server and remove `/tmp/fxui.db` after.

- [ ] **Step 5: Commit**

```bash
git add src/khata/static/assets/fx.js src/khata/static/asset-detail.html src/khata/static/loan-detail.html src/khata/static/chit-detail.html
git commit -m "feat(web): FX snapshot line under ledger amounts"
```

---

### Task 12: UI — editable rate field in the three edit forms

**Files:**
- Modify: `src/khata/static/asset-detail.html` (form ~line 141, `openOver` ~:616, `openEdit` ~:625, save handler ~:791)
- Modify: `src/khata/static/loan-detail.html` (edit form ~line 218, `openEdit` ~:1150, `edit-save` ~:1363)
- Modify: `src/khata/static/chit-detail.html` (edit form ~line 268, `openEdit` ~:761, `edit-save` ~:885)

Behavior (spec §8): field prefilled from the snapshot in natural direction ("1 USD = ₹88.00"); saving sends `fx_rate_micro` ONLY when the field is non-empty AND changed; clearing the field leaves the snapshot unchanged.

- [ ] **Step 1: asset-detail.html**

After the note fld (line 141 `<div class="fld"><label for="note">Note (optional)</label>...`), add:

```html
    <div class="fld" id="fxrate-fld" style="display:none"><label for="fxrate">FX rate · 1 USD = ₹</label><input id="fxrate" placeholder="88.00" inputmode="decimal"></div>
```

In `openOver()` (new payment — no rate field), after `$('proof-fld').style.display='none';` add:

```javascript
  $('fxrate-fld').style.display='none';
```

In `openEdit(lr)`, after `$('proof-fld').style.display='';` add:

```javascript
  $('fxrate-fld').style.display='';
  $('fxrate').value = fxNaturalFromMicro(lr.fx_rate_micro, BASE);
  $('fxrate').dataset.initial = $('fxrate').value;
```

In the `$('save')` click handler, after the `body` object is built (before the `if($('paidby-fld')...` line), add:

```javascript
  // explicit FX rate: send only when edited and non-empty (clearing = leave unchanged)
  if(editId && $('fxrate-fld').style.display!=='none'){
    const fv=$('fxrate').value.trim();
    if(fv && fv!==$('fxrate').dataset.initial){
      const micro=fxMicroFromNatural(fv, BASE);
      if(micro) body.fx_rate_micro = micro;
    }
  }
```

- [ ] **Step 2: loan-detail.html**

After the edit-note fld (line 218), add:

```html
    <div class="fld" id="edit-fxrate-fld"><label for="edit-fxrate">FX rate · 1 USD = ₹</label><input id="edit-fxrate" placeholder="88.00" inputmode="decimal"></div>
```

In `openEdit(it)` (~:1150), after `$('edit-occurred').value=...;` add:

```javascript
  $('edit-fxrate').value = fxNaturalFromMicro(it.fx_rate_micro, BASE);
  $('edit-fxrate').dataset.initial = $('edit-fxrate').value;
```

In the `$('edit-save')` handler (~:1363), after the `body` build, add:

```javascript
  const fv=$('edit-fxrate').value.trim();
  if(fv && fv!==$('edit-fxrate').dataset.initial){
    const micro=fxMicroFromNatural(fv, BASE);
    if(micro) body.fx_rate_micro = micro;
  }
```

- [ ] **Step 3: chit-detail.html**

After the edit-note fld (line 268), add the same `<div class="fld" id="edit-fxrate-fld">...` block as loan-detail. In `openEdit(e)` (~:761), after `$('edit-occurred').value=...;` add:

```javascript
  $('edit-fxrate').value = fxNaturalFromMicro(e.fx_rate_micro, BASE);
  $('edit-fxrate').dataset.initial = $('edit-fxrate').value;
```

In its `$('edit-save')` handler (~:885), after the `body` build, add the same `fv` block as loan-detail (with `$('edit-fxrate')`).

- [ ] **Step 4: Verify wiring + headless check**

Run: `grep -cn "fxMicroFromNatural" src/khata/static/asset-detail.html src/khata/static/loan-detail.html src/khata/static/chit-detail.html` → 1 each.
Re-run the Task 11 Step 4 headless check: edit an entry, set rate 85, confirm the PATCH body carries `fx_rate_micro` (85_000_000 for a USD plan / 11_765 for an INR plan) and the ledger line updates.

- [ ] **Step 5: Commit**

```bash
git add src/khata/static/asset-detail.html src/khata/static/loan-detail.html src/khata/static/chit-detail.html
git commit -m "feat(web): editable FX rate field in entry edit forms"
```

---

### Task 13: Settings hint + AS-BUILT + final verification

**Files:**
- Modify: `src/khata/static/settings.html` (line 137)
- Modify: `docs/specs/khata-AS-BUILT.md` (change log)

- [ ] **Step 1: Settings hint**

Change line 137 of `settings.html` from:

```html
              <div class="hint" id="fxhint">Exchange rate — used to show every plan in your base currency.</div>
```

to:

```html
              <div class="hint" id="fxhint">Exchange rate — used to show every plan in your base currency. Refreshes daily from ECB (frankfurter.app); a manual rate is overwritten at the next refresh.</div>
```

- [ ] **Step 2: AS-BUILT entry**

Append a change-log entry to `docs/specs/khata-AS-BUILT.md` (follow the file's existing entry format) covering: snapshot columns + migration `fxsnapshot01`, `fx_live` client, snapshot fallback chain, explicit rate on create/PATCH (422), per-entry dashboard conversion, daily scheduler refresh + claim table, admin fx-backfill (prod-write warning: run once, manually, only on explicit user authorization), ledger fx line + edit-form rate field + settings hint.

- [ ] **Step 3: Final full suite**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q`
Expected: ALL pass (≈288 existing + ~30 new).

- [ ] **Step 4: Commit**

```bash
git add src/khata/static/settings.html docs/specs/khata-AS-BUILT.md
git commit -m "docs+web(fx): settings daily-refresh hint + AS-BUILT entry"
```

---

## Post-merge runbook (NOT part of implementation — user-gated)

1. PR from `feat/fx-snapshot` → squash-merge.
2. Deploy via the standard rsync ritual (excludes per memory; restart needed — Python changed). Run `alembic upgrade head` on prod **before** restart.
3. **Only on explicit user order:** `POST /api/admin/fx-backfill` once on prod (prod DB write).

## Self-review (done at planning time)

- Spec coverage: §1→T1, §2→T2, §3→T3+T4, §4→T6+T7, §5→T8 (loans/networth stay current-rate — justified in header notes), §6→T9 (direction fix documented), §7→T10, §8→T11+T12+T13, §9→T2/T3/T9/T10 error paths, §10→tests in every task.
- Direction sanity: snapshot always counter-per-entry; helper math cross-checked (₹80/$ stored → INR entry snapshot 12_500; ₹50,000 @ 11_364 → $568.20).
- Known soft spots flagged inline for the implementer: create-plan service signatures in T4 tests, admin promotion bootstrap in T10 tests, alembic env var name in T1 Step 6.
