# Transfer funding-source + FX display fidelity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let money routed through a middleman carry its funding source (loan / savings / specific loan) all the way to the seller, and show each in-transit amount at the rate it was actually sent instead of a single global rate.

**Architecture:** Funding provenance is stored on the origin `TransferHop` (two new nullable columns) and threaded forward through the existing contribution-tracing walk, so terminal fan-out produces one ledger entry per `(contributor, funding_source, funding_plan_id)`. Editing an origin hop's funding re-stamps its already-fanned-out ledger entries. FX display fidelity is a pure read-path fix: the transit API emits each hop's stored FX snapshot, and the frontend converts a single transaction's amount using that snapshot rather than the global display rate.

**Tech Stack:** Python 3, Flask, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), Alembic (SQLite, `batch_alter_table`), pytest, vanilla JS frontend (`asset-detail.html` + `assets/transfers.js`).

## Global Constraints

- Money is integer minor units only — never float. Parse via `khata.money.to_minor`; INR/USD both use 2 minor digits.
- `funding_source` vocabulary is exactly `khata.services.assets.SOURCES` = `{savings, loan, borrowed, sold_asset, chit_payout, other}`. `NULL` = untagged.
- `fx_rate_micro` on hops and ledger entries is **counter-per-entry ×1e6**; `fx.convert(amount_minor, rate_micro=…)` derives the native counter value.
- Plan base currency is canonical (INR here); the display currency (USD) is derived per-transaction. Do NOT change stored amounts.
- Every code change updates `docs/specs/khata-AS-BUILT.md` in the same body of work (Task 9), and the screen is headless-verified via `/build-screen` before "done" (project rule in `CLAUDE.md`).
- Aggregates (totals, "in transit", contributor sums, funding bars) stay on the global snapshot rate `conv()`. Only single-transaction rows use native rates.
- Existing migration head is `th2hopattach01`. The new migration chains from it.

---

### Task 1: Schema — funding columns on `transfer_hops`

**Files:**
- Create: `alembic/versions/th3hopfund01_hop_funding.py`
- Modify: `src/khata/models/transfer.py` (add two columns to `TransferHop`, after line 51 `resolution`)
- Test: `tests/test_hop_funding.py`

**Interfaces:**
- Produces: `TransferHop.funding_source: str | None`, `TransferHop.funding_plan_id: int | None` (FK → `plans.id`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_hop_funding.py`:

```python
from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.assets import create_asset_plan
from khata.services import transfers


def _dt(day=1):
    return datetime(2026, 7, day, tzinfo=timezone.utc)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="u@x.com", display_name="U", password_hash="x")
        s.add(u); s.flush()
        loan = create_asset_plan(s, owner_id=u.id, name="Car loan",
                                 currency="INR", total_price_minor=10000000)
        loan.type = "loan"
        plan = create_asset_plan(s, owner_id=u.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        s.commit()
        yield s, u, plan, loan


def test_hop_stores_funding_columns(ctx):
    s, u, plan, loan = ctx
    from khata.models import TransferHop
    # Pure model test — Task 1 is schema-only; create_hop wiring lands in Task 2.
    hop = TransferHop(
        plan_id=plan.id, from_user_id=u.id, to_name="Middleman",
        amount_minor=200000, currency="INR", occurred_at=_dt(),
        method="transfer", logged_by_user_id=u.id,
        funding_source="loan", funding_plan_id=loan.id)
    s.add(hop); s.flush()
    fresh = s.get(TransferHop, hop.id)
    assert fresh.funding_source == "loan"
    assert fresh.funding_plan_id == loan.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hop_funding.py::test_hop_stores_funding_columns -v`
Expected: FAIL — `TypeError: 'funding_source' is an invalid keyword argument for TransferHop` (the model has no such column yet).

- [ ] **Step 3: Add the columns to the model**

In `src/khata/models/transfer.py`, immediately after the `resolution` column (line 51), add:

```python
    # Funding provenance of THIS hop's own-funds portion (the source_hop_id-NULL
    # HopSource row): where the sender's own money came from. NULL = untagged.
    funding_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    funding_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("plans.id"), nullable=True)
```

(`String` and `ForeignKey` are already imported at line 3.)

- [ ] **Step 4: Create the Alembic migration**

Create `alembic/versions/th3hopfund01_hop_funding.py`:

```python
"""transfer_hops.funding_source + funding_plan_id — provenance of in-transit money

Revision ID: th3hopfund01
Revises: th2hopattach01
Create Date: 2026-07-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'th3hopfund01'
down_revision: Union[str, None] = 'th2hopattach01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('transfer_hops') as batch:
        batch.add_column(sa.Column('funding_source', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('funding_plan_id', sa.Integer(), nullable=True))
    op.create_index('ix_transfer_hops_funding_plan_id', 'transfer_hops', ['funding_plan_id'])


def downgrade() -> None:
    op.drop_index('ix_transfer_hops_funding_plan_id', table_name='transfer_hops')
    with op.batch_alter_table('transfer_hops') as batch:
        batch.drop_column('funding_plan_id')
        batch.drop_column('funding_source')
```

Note: the test uses `Base.metadata.create_all` (not migrations), so the model change alone turns it green. The migration keeps the real SQLite DBs in sync.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_hop_funding.py::test_hop_stores_funding_columns -v`
Expected: PASS.

- [ ] **Step 6: Apply the migration to the dev DB and confirm head**

Run: `python -m alembic upgrade head && python -m alembic heads`
Expected: no error; head prints `th3hopfund01 (head)`.

- [ ] **Step 7: Commit**

```bash
git add src/khata/models/transfer.py alembic/versions/th3hopfund01_hop_funding.py tests/test_hop_funding.py
git commit -m "feat(transfer): funding_source + funding_plan_id columns on transfer_hops"
```

---

### Task 2: Persist funding on create/update hop

**Files:**
- Modify: `src/khata/services/transfers.py` (`create_hop` ~line 70-139; `update_hop` ~line 380-421)
- Test: `tests/test_hop_funding.py`

**Interfaces:**
- Consumes: `SOURCES` from `khata.services.assets`.
- Produces:
  - `create_hop(..., funding_source=None, funding_plan_id=None)` — stores both on the hop.
  - `update_hop(..., funding_source=_UNSET, funding_plan_id=_UNSET)` — updates when provided; `_UNSET` sentinel distinguishes "not provided" from "clear to NULL".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hop_funding.py`:

```python
def test_create_hop_rejects_bad_funding_source(ctx):
    s, u, plan, loan = ctx
    with pytest.raises(transfers.TransferValidationError):
        transfers.create_hop(
            s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id,
            to_name="M", amount_minor=1000, occurred_at=_dt(),
            method="transfer", funding_source="not_a_source")


def test_update_hop_sets_and_clears_funding(ctx):
    s, u, plan, loan = ctx
    hop = transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id,
        to_name="M", amount_minor=1000, occurred_at=_dt(), method="transfer")
    s.commit()
    assert hop.funding_source is None
    transfers.update_hop(s, plan=plan, hop_id=hop.id, acting_user_id=u.id,
                         funding_source="loan", funding_plan_id=loan.id)
    s.commit()
    assert hop.funding_source == "loan"
    assert hop.funding_plan_id == loan.id
    # explicit clear
    transfers.update_hop(s, plan=plan, hop_id=hop.id, acting_user_id=u.id,
                         funding_source=None, funding_plan_id=None)
    s.commit()
    assert hop.funding_source is None
    assert hop.funding_plan_id is None


def test_update_hop_without_funding_kwargs_leaves_it(ctx):
    s, u, plan, loan = ctx
    hop = transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id,
        to_name="M", amount_minor=1000, occurred_at=_dt(), method="transfer",
        funding_source="savings")
    s.commit()
    transfers.update_hop(s, plan=plan, hop_id=hop.id, acting_user_id=u.id,
                         method="upi")
    s.commit()
    assert hop.funding_source == "savings"   # untouched when kwarg omitted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hop_funding.py -v`
Expected: the three new tests FAIL (funding not persisted / `update_hop` has no `funding_source` kwarg).

- [ ] **Step 3: Implement in `create_hop`**

In `src/khata/services/transfers.py`:

Add near the top of the file (after the imports, before `class TransferError`):

```python
_UNSET = object()
```

Change the import line 9 from:

```python
from .assets import METHODS
```
to:
```python
from .assets import METHODS, SOURCES
```

In `create_hop`, change the `funding_source` default from `"other"` to `None` (untagged) and add `funding_plan_id=None`. Update the signature line (was `funding_source="other") -> TransferHop:`):

```python
def create_hop(session: Session, *, plan, logged_by_user_id, amount_minor, occurred_at,
               method, to_user_id=None, to_contact_id=None, to_name=None,
               from_user_id=None, from_contact_id=None, from_name=None,
               sources=None, is_terminal=False, resolution=None,
               proof_ref=None, note=None, fx_rate_micro=None,
               funding_source=None, funding_plan_id=None) -> TransferHop:
```

After the existing `if method not in METHODS:` validation block, add:

```python
    if funding_source is not None and funding_source not in SOURCES:
        raise TransferValidationError(f"unknown funding_source: {funding_source}")
```

In the `hop = TransferHop(...)` constructor (line 110-120), add these two keyword args:

```python
        funding_source=funding_source, funding_plan_id=funding_plan_id,
```

In the terminal fan-out call (currently line 134-137):

```python
    if hop.is_terminal and hop.resolution is None:
        fan_out_terminal(session, plan=plan, hop=hop,
                         acting_user_id=logged_by_user_id,
                         funding_source=funding_source)
```
change to (drop the `funding_source=` argument — fan-out will read it from the hop in Task 3; harmless now because `fan_out_terminal` still accepts the kwarg with a default until Task 3):

```python
    if hop.is_terminal and hop.resolution is None:
        fan_out_terminal(session, plan=plan, hop=hop,
                         acting_user_id=logged_by_user_id)
```

- [ ] **Step 4: Implement in `update_hop`**

Change the `update_hop` signature (line 380-382) to add the two sentinel-defaulted kwargs:

```python
def update_hop(session: Session, *, plan, hop_id, acting_user_id,
               amount_minor=None, occurred_at=None, method=None,
               proof_ref=None, note=None, fx_rate_micro=None,
               funding_source=_UNSET, funding_plan_id=_UNSET) -> TransferHop:
```

Just before `session.flush()` near the end of `update_hop` (line 418), add:

```python
    if funding_source is not _UNSET and funding_source != hop.funding_source:
        if funding_source is not None and funding_source not in SOURCES:
            raise TransferValidationError(f"unknown funding_source: {funding_source}")
        diff["funding_source"] = {"old": hop.funding_source, "new": funding_source}
        hop.funding_source = funding_source
    if funding_plan_id is not _UNSET and funding_plan_id != hop.funding_plan_id:
        diff["funding_plan_id"] = {"old": hop.funding_plan_id, "new": funding_plan_id}
        hop.funding_plan_id = funding_plan_id
```

(Re-stamp of downstream ledger entries is wired in Task 5; this task only persists the fields.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_hop_funding.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the transfer regression suite**

Run: `python -m pytest tests/test_transit_breakdown.py tests/test_transfers_api.py tests/test_hop_attachments.py -v`
Expected: all PASS (no behavior change for existing paths).

- [ ] **Step 7: Commit**

```bash
git add src/khata/services/transfers.py tests/test_hop_funding.py
git commit -m "feat(transfer): create_hop/update_hop persist funding_source + funding_plan_id"
```

---

### Task 3: Thread funding provenance through fan-out

**Files:**
- Modify: `src/khata/services/transfers.py` (`_alloc` ~252-272, `resolve_contributions` ~275-292, `plan_transfers` transit loop ~360-367, `resolve_remainder` fee loop ~477, `fan_out_terminal` ~490-506)
- Test: `tests/test_hop_funding.py`

**Interfaces:**
- Produces:
  - `_alloc(...) -> list[tuple[int | None, str | None, int | None, int]]` — `(uid, funding_source, funding_plan_id, amount)`.
  - `resolve_contributions(...) -> list[tuple[int | None, str | None, int | None, int]]` — merged by `(uid, funding_source, funding_plan_id)`.
  - `fan_out_terminal(session, *, plan, hop, acting_user_id)` — no `funding_source` param; reads each origin's stored funding.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hop_funding.py`:

```python
def test_fanout_splits_per_funding_source(ctx):
    s, u, plan, loan = ctx
    from khata.models import LedgerEntry
    from sqlalchemy import select
    # u sends two origin hops to a middleman: one loan-funded, one savings-funded
    h_loan = transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id, to_name="Mid",
        amount_minor=200000, occurred_at=_dt(1), method="transfer",
        funding_source="loan", funding_plan_id=loan.id)
    h_sav = transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id, to_name="Mid",
        amount_minor=100000, occurred_at=_dt(2), method="transfer",
        funding_source="savings")
    # middleman (still u for test simplicity) forwards all 300000 to the seller
    transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_name="Mid", to_name="Seller",
        amount_minor=300000, occurred_at=_dt(3), method="transfer", is_terminal=True,
        sources=[{"source_hop_id": h_loan.id, "amount_minor": 200000},
                 {"source_hop_id": h_sav.id, "amount_minor": 100000}])
    s.commit()
    entries = s.scalars(select(LedgerEntry).where(LedgerEntry.plan_id == plan.id)).all()
    by = {(e.funding_source, e.funding_plan_id): e.amount_minor for e in entries}
    assert by[("loan", loan.id)] == 200000
    assert by[("savings", None)] == 100000
    assert len(entries) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hop_funding.py::test_fanout_splits_per_funding_source -v`
Expected: FAIL — today fan-out merges by uid only, producing one `$3000` entry with a single funding source.

- [ ] **Step 3: Rewrite `_alloc` to carry provenance**

Replace the body of `_alloc` (lines 252-272). Only the own-funds branch changes — it now emits the hop's funding fields:

```python
def _alloc(session: Session, h: TransferHop, take: int, taken_before: int) -> list[tuple]:
    """Allocate `take` units of hop h's money to ultimate origins, skipping the
    first `taken_before` units (already claimed by earlier consumers). Greedy
    oldest-first over the hop's sources (HopSource.id order). Each tuple is
    (uid, funding_source, funding_plan_id, amount)."""
    out: list[tuple] = []
    pos = 0
    for src in h.sources:                    # ordered by HopSource.id
        if take <= 0:
            break
        seg = src.amount_minor
        overlap_start = max(pos, taken_before)
        overlap_end = min(pos + seg, taken_before + take)
        grab = overlap_end - overlap_start
        if grab > 0:
            if src.source_hop_id is None:
                out.append((_own_party_user(h), h.funding_source, h.funding_plan_id, grab))
            else:
                up = session.get(TransferHop, src.source_hop_id)
                out.extend(_alloc(session, up, grab, overlap_start - pos))
        pos += seg
    return out
```

- [ ] **Step 4: Rewrite `resolve_contributions` to merge by (uid, source, plan)**

Replace `resolve_contributions` (lines 275-292):

```python
def resolve_contributions(session: Session, hop: TransferHop) -> list[tuple]:
    """(uid, funding_source, funding_plan_id, amount) tuples for a hop's money,
    walked to ultimate origins. uid None = non-user origin. Greedy oldest-first."""
    result: list[tuple] = []
    for src in hop.sources:
        if src.source_hop_id is None:
            result.append((_own_party_user(hop), hop.funding_source,
                           hop.funding_plan_id, src.amount_minor))
        else:
            up = session.get(TransferHop, src.source_hop_id)
            prior = _prior_consumption(session, up, before_source_id=src.id)
            result.extend(_alloc(session, up, src.amount_minor, prior))
    merged: dict[tuple, int] = {}
    for uid, fsrc, fplan, amt in result:
        key = (uid, fsrc, fplan)
        merged[key] = merged.get(key, 0) + amt
    return [(uid, fsrc, fplan, amt) for (uid, fsrc, fplan), amt in merged.items()]
```

- [ ] **Step 5: Update the `plan_transfers` transit loop**

In `plan_transfers`, the in-transit attribution loop (lines 360-367) unpacks `_alloc`. Change:

```python
        for uid, amt in _alloc(session, h, out, consumed(session, h)):
            uid = uid if uid is not None else h.logged_by_user_id
            transit_by[uid] = transit_by.get(uid, 0) + amt
```
to:
```python
        for uid, _fsrc, _fplan, amt in _alloc(session, h, out, consumed(session, h)):
            uid = uid if uid is not None else h.logged_by_user_id
            transit_by[uid] = transit_by.get(uid, 0) + amt
```

- [ ] **Step 6: Update `fan_out_terminal`**

Replace `fan_out_terminal` (lines 490-506):

```python
def fan_out_terminal(session: Session, *, plan, hop: TransferHop, acting_user_id):
    """Spawn one LedgerEntry per (contributor, funding_source, funding_plan_id) of a
    terminal hop. Non-user origins are attributed to the hop logger with 'other'."""
    from .assets import log_payment
    entries = []
    for uid, fsrc, fplan, amt in resolve_contributions(session, hop):
        entry = log_payment(
            session, plan=plan, user_id=uid if uid is not None else hop.logged_by_user_id,
            amount_minor=amt, occurred_at=hop.occurred_at, method=hop.method,
            funding_source=fsrc or "other", funding_plan_id=fplan,
            proof_ref=hop.proof_ref, note=hop.note,
            acting_user_id=acting_user_id)
        entry.source_hop_id = hop.id
        entries.append(entry)
    session.flush()
    return entries
```

- [ ] **Step 7: Update the `resolve_remainder` fee loop**

In `resolve_remainder`, the fee branch (line 477) unpacks `resolve_contributions`. Change:

```python
        for uid, part in resolve_contributions(session, res_hop):
```
to:
```python
        for uid, _fsrc, _fplan, part in resolve_contributions(session, res_hop):
```

(Fee entries keep `funding_source="other"` — unchanged, per spec "out of scope".)

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_hop_funding.py::test_fanout_splits_per_funding_source -v`
Expected: PASS.

- [ ] **Step 9: Run the full transfer suite**

Run: `python -m pytest tests/test_transit_breakdown.py tests/test_transfers_api.py tests/test_hop_attachments.py tests/test_hop_funding.py -v`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add src/khata/services/transfers.py tests/test_hop_funding.py
git commit -m "feat(transfer): thread funding provenance through fan-out (per-source ledger split)"
```

---

### Task 4: Emit hop FX snapshot from `plan_transfers`

**Files:**
- Modify: `src/khata/services/transfers.py` (`plan_transfers` hop-row dict ~335-352; add `fx` import)
- Test: `tests/test_hop_funding.py`

**Interfaces:**
- Produces: each `plan_transfers` hop row gains `fx_rate_micro`, `fx_counter_currency`, `counter_value_minor`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hop_funding.py`:

```python
def test_plan_transfers_emits_hop_fx(ctx):
    s, u, plan, loan = ctx
    # $1000 sent at ₹94.47/$ → stored 9,447,000 INR paise; rate_micro = counter-per-entry
    rate_micro = round(1e6 / 94.47)  # USD-per-INR ×1e6
    transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id, to_name="Mid",
        amount_minor=9447000, occurred_at=_dt(), method="transfer",
        fx_rate_micro=rate_micro)
    s.commit()
    data = transfers.plan_transfers(s, plan)
    hop = data["chains"][0]["hops"][0]
    assert hop["fx_rate_micro"] == rate_micro
    assert hop["fx_counter_currency"] == "USD"
    # round-trips back to ~$1000.00 (100000 cents), not $988
    assert abs(hop["counter_value_minor"] - 100000) <= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_hop_funding.py::test_plan_transfers_emits_hop_fx -v`
Expected: FAIL — `KeyError: 'fx_rate_micro'` (row dict lacks the FX trio).

- [ ] **Step 3: Add the FX import**

At the top of `plan_transfers` (it already does `from datetime import date` inline at line 318), add an inline import for `fx` right after it:

```python
    from datetime import date
    from . import fx
```

- [ ] **Step 4: Add the FX trio to the hop-row dict**

In the `rows.append({...})` block inside `plan_transfers` (lines 335-352), add three keys (place them next to `"amount_minor"`):

```python
                "fx_rate_micro": h.fx_rate_micro,
                "fx_counter_currency": h.fx_counter_currency,
                "counter_value_minor": (fx.convert(h.amount_minor, rate_micro=h.fx_rate_micro)
                                        if h.fx_rate_micro else None),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_hop_funding.py::test_plan_transfers_emits_hop_fx -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/khata/services/transfers.py tests/test_hop_funding.py
git commit -m "feat(transfer): emit per-hop FX snapshot trio from plan_transfers"
```

---

### Task 5: Re-stamp downstream ledger entries on origin-hop edit

**Files:**
- Modify: `src/khata/services/transfers.py` (add `_downstream_terminals`, `_reconcile_terminal_entries`, `restamp_downstream`; wire into `update_hop`)
- Test: `tests/test_hop_funding.py`

**Interfaces:**
- Consumes: `resolve_contributions` (Task 3), `log_payment` + `delete_ledger_entry` from `khata.services.assets`.
- Produces: `restamp_downstream(session, *, plan, hop, acting_user_id)` — recomputes and reconciles fan-out ledger entries for every terminal hop downstream of `hop` (including `hop` itself if terminal). Called from `update_hop` when funding fields change.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hop_funding.py`:

```python
def _chain_through_middleman(s, u, plan, amount, source, plan_id=None):
    """origin hop (u→Mid) with own funds, then terminal (Mid→Seller) drawing it all."""
    origin = transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id, to_name="Mid",
        amount_minor=amount, occurred_at=_dt(1), method="transfer",
        funding_source=source, funding_plan_id=plan_id)
    transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_name="Mid", to_name="Seller",
        amount_minor=amount, occurred_at=_dt(2), method="transfer", is_terminal=True,
        sources=[{"source_hop_id": origin.id, "amount_minor": amount}])
    return origin


def test_edit_origin_restamps_downstream_entry(ctx):
    s, u, plan, loan = ctx
    from khata.models import LedgerEntry
    from sqlalchemy import select
    origin = _chain_through_middleman(s, u, plan, 200000, None)
    s.commit()
    entry = s.scalars(select(LedgerEntry).where(LedgerEntry.plan_id == plan.id)).one()
    assert entry.funding_source == "other"    # origin was untagged → fan-out default
    assert entry.funding_plan_id is None
    # now tag the origin as loan-funded
    transfers.update_hop(s, plan=plan, hop_id=origin.id, acting_user_id=u.id,
                         funding_source="loan", funding_plan_id=loan.id)
    s.commit()
    entry = s.scalars(select(LedgerEntry).where(LedgerEntry.plan_id == plan.id)).one()
    assert entry.funding_source == "loan"      # re-stamped in place
    assert entry.funding_plan_id == loan.id


def test_edit_origin_split_creates_two_entries(ctx):
    s, u, plan, loan = ctx
    from khata.models import LedgerEntry
    from sqlalchemy import select
    # one origin hop of 300000, all forwarded to seller as one terminal → one entry
    origin = transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id, to_name="Mid",
        amount_minor=300000, occurred_at=_dt(1), method="transfer")
    transfers.create_hop(
        s, plan=plan, logged_by_user_id=u.id, from_name="Mid", to_name="Seller",
        amount_minor=300000, occurred_at=_dt(2), method="transfer", is_terminal=True,
        sources=[{"source_hop_id": origin.id, "amount_minor": 300000}])
    s.commit()
    assert len(s.scalars(select(LedgerEntry).where(LedgerEntry.plan_id == plan.id)).all()) == 1
    # tagging the single origin loan-funded keeps it one entry (merge stays 1)
    transfers.update_hop(s, plan=plan, hop_id=origin.id, acting_user_id=u.id,
                         funding_source="loan", funding_plan_id=loan.id)
    s.commit()
    entries = s.scalars(select(LedgerEntry).where(LedgerEntry.plan_id == plan.id)).all()
    assert len(entries) == 1
    assert entries[0].funding_source == "loan"
    assert entries[0].amount_minor == 300000


def test_restamp_ignores_manual_entries(ctx):
    s, u, plan, loan = ctx
    from khata.services.assets import log_payment
    from khata.models import LedgerEntry
    from sqlalchemy import select
    manual = log_payment(s, plan=plan, user_id=u.id, amount_minor=5000,
                         occurred_at=_dt(), method="cash", funding_source="savings",
                         acting_user_id=u.id)
    origin = _chain_through_middleman(s, u, plan, 200000, None)
    s.commit()
    transfers.update_hop(s, plan=plan, hop_id=origin.id, acting_user_id=u.id,
                         funding_source="loan", funding_plan_id=loan.id)
    s.commit()
    fresh = s.get(LedgerEntry, manual.id)
    assert fresh is not None and fresh.funding_source == "savings"   # untouched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_hop_funding.py -k restamp_or_split -v` (or run the three new tests by name)
Expected: `test_edit_origin_restamps_downstream_entry` FAILS (entry still `other` after edit); the split/manual tests may pass incidentally but the restamp one drives the change.

- [ ] **Step 3: Add downstream-terminal discovery**

In `src/khata/services/transfers.py`, add after `resolve_contributions`:

```python
def _downstream_terminals(session: Session, hop: TransferHop) -> list[TransferHop]:
    """Every terminal hop reachable by following consumers of `hop` (and `hop`
    itself if it is terminal). A consumer of hop H is any hop with a HopSource
    row whose source_hop_id == H.id."""
    seen: set[int] = set()
    stack = [hop.id]
    terminals: list[TransferHop] = []
    while stack:
        hid = stack.pop()
        rows = session.scalars(select(HopSource).where(HopSource.source_hop_id == hid)).all()
        for r in rows:
            if r.hop_id in seen:
                continue
            seen.add(r.hop_id)
            consumer = session.get(TransferHop, r.hop_id)
            if consumer is None:
                continue
            if consumer.is_terminal:
                terminals.append(consumer)
            stack.append(consumer.id)
    if hop.is_terminal and hop.id not in {t.id for t in terminals}:
        terminals.append(hop)
    return terminals
```

- [ ] **Step 4: Add the reconcile + restamp functions**

Add below `_downstream_terminals`:

```python
def _fanout_entries(session: Session, terminal_id: int) -> list:
    """The auto-generated ledger entries for a terminal hop: source_hop_id points
    at it and kind is unset (fee write-offs carry kind='transfer_fee')."""
    from ..models import LedgerEntry
    rows = session.scalars(select(LedgerEntry).where(
        LedgerEntry.source_hop_id == terminal_id)).all()
    return [e for e in rows if e.kind is None]


def _reconcile_terminal_entries(session: Session, *, plan, terminal: TransferHop,
                                acting_user_id) -> None:
    """Make the terminal hop's fan-out ledger entries match resolve_contributions
    under current funding provenance. Per-contributor amounts are unchanged (chain
    structure is unchanged); only the (funding_source, funding_plan_id) split moves.
    Update in place when a contributor still maps to one entry; rebuild that
    contributor's entries when the group count changed (split or merge)."""
    from collections import defaultdict
    from .assets import log_payment, delete_ledger_entry

    want_by: dict[int, list] = defaultdict(list)
    for uid, fsrc, fplan, amt in resolve_contributions(session, terminal):
        key = uid if uid is not None else terminal.logged_by_user_id
        want_by[key].append((fsrc, fplan, amt))

    exist_by: dict[int, list] = defaultdict(list)
    for e in _fanout_entries(session, terminal.id):
        exist_by[e.logged_by_user_id].append(e)

    for uid in set(want_by) | set(exist_by):
        w = want_by.get(uid, [])
        ex = exist_by.get(uid, [])
        if len(w) == 1 and len(ex) == 1:
            fsrc, fplan, amt = w[0]
            e = ex[0]
            e.funding_source = fsrc or "other"
            e.funding_plan_id = fplan
            e.amount_minor = amt
        else:
            for e in ex:
                delete_ledger_entry(session, plan=plan, entry_id=e.id,
                                    acting_user_id=acting_user_id)
            for fsrc, fplan, amt in w:
                entry = log_payment(
                    session, plan=plan, user_id=uid, amount_minor=amt,
                    occurred_at=terminal.occurred_at, method=terminal.method,
                    funding_source=fsrc or "other", funding_plan_id=fplan,
                    proof_ref=terminal.proof_ref, note=terminal.note,
                    acting_user_id=acting_user_id)
                entry.source_hop_id = terminal.id
    session.flush()


def restamp_downstream(session: Session, *, plan, hop: TransferHop, acting_user_id) -> None:
    """After a hop's funding provenance changes, re-derive the fan-out ledger
    entries of every terminal hop that its money reaches."""
    for terminal in _downstream_terminals(session, hop):
        _reconcile_terminal_entries(session, plan=plan, terminal=terminal,
                                    acting_user_id=acting_user_id)
```

- [ ] **Step 5: Wire into `update_hop`**

In `update_hop`, replace the funding block added in Task 2 with a version that tracks whether funding changed, and call `restamp_downstream` after `session.flush()`:

```python
    fund_changed = False
    if funding_source is not _UNSET and funding_source != hop.funding_source:
        if funding_source is not None and funding_source not in SOURCES:
            raise TransferValidationError(f"unknown funding_source: {funding_source}")
        diff["funding_source"] = {"old": hop.funding_source, "new": funding_source}
        hop.funding_source = funding_source
        fund_changed = True
    if funding_plan_id is not _UNSET and funding_plan_id != hop.funding_plan_id:
        diff["funding_plan_id"] = {"old": hop.funding_plan_id, "new": funding_plan_id}
        hop.funding_plan_id = funding_plan_id
        fund_changed = True
    session.flush()
    if fund_changed:
        restamp_downstream(session, plan=plan, hop=hop, acting_user_id=acting_user_id)
    if diff:
        _write_audit(session, hop, "edit", acting_user_id, diff)
    return hop
```

Note: this replaces the existing trailing `session.flush()` / `if diff:` / `return hop` at the end of `update_hop` — do not double-flush or double-return.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_hop_funding.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the full transfer suite**

Run: `python -m pytest tests/test_transit_breakdown.py tests/test_transfers_api.py tests/test_hop_attachments.py tests/test_hop_funding.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/khata/services/transfers.py tests/test_hop_funding.py
git commit -m "feat(transfer): re-stamp downstream ledger entries when origin hop funding is edited"
```

---

### Task 6: API relays funding fields on create + patch

**Files:**
- Modify: `src/khata/api/transfers.py` (`create_hop` handler ~26-62; `patch_hop` handler ~76-105)
- Test: `tests/test_transfers_api.py`

**Interfaces:**
- Consumes: service `create_hop`/`update_hop` funding kwargs (Tasks 2, 5).
- Produces: POST `/api/plans/<id>/hops` accepts `funding_source`, `funding_plan_id`; PATCH `/api/plans/<id>/hops/<hop_id>` accepts them (present-key semantics).

- [ ] **Step 1: Write the failing test**

`tests/test_transfers_api.py` provides a `client` fixture and helpers `_register(client, email, name)` / `_login(client, email)` (see lines 8-39). Append this test using the same style (solo owner, no member needed):

```python
def test_hop_funding_persists_via_api(client):
    _register(client, "u1@x.com", "U1")
    pid = client.post("/api/plans", json={
        "name": "Plot", "currency": "INR", "total_price": "10,00,000"}).get_json()["plan"]["id"]
    # create a transit hop tagged loan-funded (no linked loan)
    r = client.post(f"/api/plans/{pid}/hops", json={
        "amount": "2000", "method": "transfer", "to_name": "Middleman",
        "funding_source": "loan"})
    assert r.status_code == 201
    hop_id = r.get_json()["hop"]["id"]
    hop = client.get(f"/api/plans/{pid}/hops").get_json()["chains"][0]["hops"][0]
    assert hop["funding_source"] == "loan"
    # patch to savings
    assert client.patch(f"/api/plans/{pid}/hops/{hop_id}",
                        json={"funding_source": "savings"}).status_code == 200
    hop = client.get(f"/api/plans/{pid}/hops").get_json()["chains"][0]["hops"][0]
    assert hop["funding_source"] == "savings"
    # omitting the key on a later patch leaves it untouched
    assert client.patch(f"/api/plans/{pid}/hops/{hop_id}",
                        json={"method": "upi"}).status_code == 200
    hop = client.get(f"/api/plans/{pid}/hops").get_json()["chains"][0]["hops"][0]
    assert hop["funding_source"] == "savings"
    assert hop["method"] == "upi"
```

This test fails first on the `hop["funding_source"]` `KeyError` (row dict change, Step 2) and then on the patch-to-savings assertion (API patch relay, Step 5).

- [ ] **Step 2: Add funding fields to the transit row dict**

In `src/khata/services/transfers.py` `plan_transfers`, in the same `rows.append({...})` block, add:

```python
                "funding_source": h.funding_source,
                "funding_plan_id": h.funding_plan_id,
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_transfers_api.py::test_hop_funding_persists_via_api -v`
Expected: FAIL — after Step 2 the row dict exposes `funding_source`, so the first assert passes, but the patch handler does not yet forward `funding_source`, so the `== "savings"` assert FAILS.

- [ ] **Step 4: Update the create handler**

In `src/khata/api/transfers.py` `create_hop`, change the `funding_source=` argument (line 52) and add `funding_plan_id`:

```python
            funding_source=d.get("funding_source"),
            funding_plan_id=(int(d["funding_plan_id"]) if d.get("funding_plan_id") else None),
```

- [ ] **Step 5: Update the patch handler**

In `patch_hop` (lines 85-96), after the existing `for k in ("method", "proof_ref", "note"):` loop, add present-key handling for the funding fields:

```python
        if "funding_source" in d:
            fields["funding_source"] = d.get("funding_source") or None
        if "funding_plan_id" in d:
            fields["funding_plan_id"] = (int(d["funding_plan_id"])
                                         if d.get("funding_plan_id") else None)
```

(These land in `**fields` passed to `update_hop`, which uses the `_UNSET` sentinel so absent keys leave the hop untouched.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_transfers_api.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/khata/api/transfers.py src/khata/services/transfers.py tests/test_transfers_api.py
git commit -m "feat(transfer): API relays funding_source + funding_plan_id; transit rows expose them"
```

---

### Task 7: Frontend — native per-transaction FX display

**Files:**
- Modify: `src/khata/static/asset-detail.html` (add `nativeMinor`/`fmtDisp` helpers near `conv()` ~347; ledger row amount ~839; wire transit `fmt` callbacks ~1742)
- Modify: `src/khata/static/assets/transfers.js` (hop amount render ~143; breakdown portions ~168-179)
- Verify: headless (no JS unit harness in repo)

**Interfaces:**
- Consumes: hop rows now carry `fx_rate_micro`, `fx_counter_currency`, `counter_value_minor` (Task 4); ledger rows already carry the same trio.
- Produces:
  - `nativeMinor(amountMinor, row)` → display-currency minor using the row's own rate when `DISP === row.fx_counter_currency`, else `conv(amountMinor)`.
  - transfers.js mount opts `fmtHopAmt(h)` and `fmtSrcAmt(minor, hop)`.

- [ ] **Step 1: Add the native-display helpers**

In `src/khata/static/asset-detail.html`, immediately after `conv()` (ends line 350), add:

```javascript
// Display a SINGLE transaction's amount at the rate it was actually sent.
// row must carry fx_rate_micro + fx_counter_currency (hop or ledger row).
// Falls back to the global snapshot rate when there is no per-txn rate or the
// display currency differs from the transaction's counter currency.
function nativeMinor(amountMinor, row){
  if(amountMinor===null||amountMinor===undefined) return amountMinor;
  if(row && DISP===row.fx_counter_currency && row.fx_rate_micro)
    return Math.round(amountMinor*row.fx_rate_micro/1e6);
  return conv(amountMinor);
}
function fmtDisp(minor){ return sym(DISP)+fmtNum(minor, DISP); }
```

- [ ] **Step 2: Use native display for ledger rows**

In `renderLedger` (line 839), the amount is `fmtNum(conv(Math.abs(lr.amount_minor||0)), DISP)`. Change to native:

```javascript
    const num=el('span'); num.textContent=fmtNum(nativeMinor(Math.abs(lr.amount_minor||0), lr), DISP);
```

Leave the running-total line (853, `conv(runningById[lr.id])`) on `conv()` — it is an aggregate sum across rows.

- [ ] **Step 3: Pass native formatters to the transit panel**

In the `KhataTransfers.mount(...)` opts object (around line 1742, currently `{me: myUserId, base: DISP, fmt: (m,c)=>fmtNum(conv(m),c), sym: sym, ...}`), add two callbacks:

```javascript
      fmtHopAmt: (h)=> fmtDisp(nativeMinor(h.amount_minor, h)),
      fmtSrcAmt: (minor, hop)=> fmtDisp(nativeMinor(minor, hop)),
```

(Keep the existing `fmt`, `sym`, `base`, `me`, `onEdit`, etc. — only append these two.)

- [ ] **Step 4: Use `fmtHopAmt` for the hop headline in transfers.js**

In `src/khata/static/assets/transfers.js` `_hopRow` (line 143), change:

```javascript
    row.append(_e('div','trx-amt',_fmt(h.amount_minor)));
```
to:
```javascript
    row.append(_e('div','trx-amt', _opts.fmtHopAmt ? _opts.fmtHopAmt(h) : _fmt(h.amount_minor)));
```

- [ ] **Step 5: Use `fmtSrcAmt` for breakdown portions in transfers.js**

In `_hopRow`, the merged-sources breakdown (lines 168-179) formats each portion with `_fmt(s.amount_minor)`. Each portion belongs to a specific hop: own-funds (`source_hop_id===null`) → the current hop `h`; drawn → the upstream hop `up`. Change the loop body:

```javascript
      for(const s of h.sources){
        if(s.source_hop_id===null){
          const amt=_opts.fmtSrcAmt ? _opts.fmtSrcAmt(s.amount_minor, h) : _fmt(s.amount_minor);
          parts.push(amt+' '+(h.from.display||'own')+"'s own");
        }else{
          const up=hopById[s.source_hop_id];
          const amt=_opts.fmtSrcAmt ? _opts.fmtSrcAmt(s.amount_minor, up||h) : _fmt(s.amount_minor);
          parts.push(amt+' from '+((up&&up.from.display)||'chain'));
        }
      }
```

- [ ] **Step 6: Keep the "in transit" total honest**

The panel header shows `_fmt(_data.in_transit_minor)` (transfers.js line 232) — an aggregate; leave it on `_fmt` (global rate). In `asset-detail.html`, add a one-line note under the transit total in the mount call site is not required, but add the "at current rate" qualifier to the header total wherever aggregate USD is shown near the transit panel. Minimum: no change needed to aggregates; they intentionally stay on `conv()`.

- [ ] **Step 7: Headless verification**

Start the app and open an asset with USD display + transit chains (per `/build-screen` and the run-app instructions). Confirm:
- a hop entered `$1000 @94.47` now shows `$1,000` (not `$988`);
- the terminal breakdown portions show native amounts;
- header total / "in transit" still render (aggregate rate) without error.

Run: `/build-screen` protocol for the asset-detail "Money in transit" panel.
Expected: hop headline amounts round-trip to entered values; no console errors.

- [ ] **Step 8: Commit**

```bash
git add src/khata/static/asset-detail.html src/khata/static/assets/transfers.js
git commit -m "fix(transfer): show in-transit + ledger amounts at each transaction's own send-rate"
```

---

### Task 8: Frontend — capture funding source on transit hops

**Files:**
- Modify: `src/khata/static/asset-detail.html` (compose form `refreshRecipUI` ~1796-1820 and `saveHop` ~1876-1930; hop editor markup ~256-284, `openHopEdit` ~1426-1460, hop save ~1466-1494; funding pill on transit rows via transfers.js opts)
- Modify: `src/khata/static/assets/transfers.js` (render funding pill in `_hopRow`)
- Verify: headless

**Interfaces:**
- Consumes: hop rows carry `funding_source`, `funding_plan_id` (Task 6); API accepts them on create + patch.
- Produces: transit compose + hop-editor persist funding; transit rows show a source pill.

- [ ] **Step 1: Compose form — send funding on transit hops**

In `saveHop` (line 1876-1899), the `body` already includes `funding_source: $('fsource').value`. Add the loan link for the transit path. In the `if(kind==='transit'){ ... }` branch, after the recipient resolution, add:

```javascript
    if($('fundplan-fld').style.display!=='none')
      body.funding_plan_id = $('fundplan').value || null;
```

Also ensure the funding fields are visible for transit: in `refreshRecipUI` (line 1796-1820) the `#fsource` field and its loan sub-field are not hidden for transit (they are shared) — confirm `#fsource` stays visible and call `fillFundPlan(null)` so the loan picker toggles. Add at the end of `refreshRecipUI`:

```javascript
  fillFundPlan($('fundplan') ? $('fundplan').value : null);
```

- [ ] **Step 2: Hop editor markup — add funding fields**

In `src/khata/static/asset-detail.html`, inside the `#hop-over` slide-over, after the Method field (line 277-278) and before the Comment field (line 279), add:

```html
    <div class="fld"><label for="hop-fsource">Funding source</label>
      <select id="hop-fsource"><option value="">— untagged —</option><option value="savings">Savings</option><option value="loan">Loan</option><option value="borrowed">Borrowed</option><option value="sold_asset">Sold asset</option><option value="chit_payout">Chit payout</option><option value="other">Other</option></select>
    </div>
    <div class="fld" id="hop-fundplan-fld" style="display:none"><label for="hop-fundplan">From which loan</label><select id="hop-fundplan"></select>
      <div class="hint" style="font-size:11.5px;color:var(--ink-faint)">Links this transfer to the loan it came from — traces to the seller when the chain lands.</div>
    </div>
```

- [ ] **Step 3: Hop editor — populate + toggle the loan picker**

Add a helper near `fillFundPlan` (line 432):

```javascript
function hopFundSrcIsLoan(){ const v=$('hop-fsource').value; return v==='loan'||v==='borrowed'; }
function fillHopFundPlan(selectedId){
  const fld=$('hop-fundplan-fld'), sel=$('hop-fundplan');
  if(!hopFundSrcIsLoan() || !LOANS.length){ fld.style.display='none'; return; }
  fld.style.display='flex'; sel.textContent='';
  const none=document.createElement('option'); none.value=''; none.textContent='— not linked —'; sel.append(none);
  for(const lp of LOANS){ const o=document.createElement('option'); o.value=String(lp.id);
    o.textContent=lp.name+(lp.counterparty?(' · '+lp.counterparty):''); sel.append(o); }
  sel.value=(selectedId!=null)?String(selectedId):'';
}
```

In `openHopEdit` (before the final `$('scrim').classList.add('on')`, ~line 1457), populate the new fields:

```javascript
  $('hop-fsource').value = h.funding_source || '';
  fillHopFundPlan(h.funding_plan_id);
```

Wire the toggle once (near the other hop listeners, line 1462-1465):

```javascript
$('hop-fsource').addEventListener('change', ()=>fillHopFundPlan($('hop-fundplan')?$('hop-fundplan').value:null));
```

- [ ] **Step 4: Hop editor save — send funding fields**

In the hop save handler (line 1466-1493), before the PATCH `fetch`, add to `body`:

```javascript
  body.funding_source = $('hop-fsource').value || null;
  body.funding_plan_id = ($('hop-fundplan-fld').style.display!=='none' && $('hop-fundplan').value)
    ? $('hop-fundplan').value : null;
```

- [ ] **Step 5: Show a funding pill on transit rows**

In `src/khata/static/assets/transfers.js` `_hopRow` meta line (after the method span, ~line 148), add a source pill when tagged:

```javascript
    if(h.funding_source && _opts.srcLabel)
      meta.append(_e('span','trx-chip',_opts.srcLabel(h.funding_source)));
```

Pass `srcLabel` in the mount opts (asset-detail.html ~line 1742), reusing the page's existing `srcLabel`/`SRC_LABELS`:

```javascript
      srcLabel: (code)=> srcLabel(code),
```

- [ ] **Step 6: Headless verification**

Via `/build-screen`:
- Compose a transit hop with Funding source = Loan + a loan selected → reopen it; the editor shows Loan + the linked loan.
- Edit an existing closed chain's origin hop, set Loan → the funding pill appears and (per Task 5) the seller ledger entry shows the loan-deployment link.
- Confirm the "from which loan" picker appears only for loan/borrowed.

Expected: funding persists across reopen; pills render; loan link lights up.

- [ ] **Step 7: Commit**

```bash
git add src/khata/static/asset-detail.html src/khata/static/assets/transfers.js
git commit -m "feat(transfer): capture funding source on transit compose + hop editor; show source pill"
```

---

### Task 9: Docs + full verification

**Files:**
- Modify: `docs/specs/khata-AS-BUILT.md`
- Modify: `docs/specs/2026-07-08-payment-chains-design.md`, `docs/specs/2026-07-08-funding-3state-design.md` (cross-reference notes)
- Verify: full test suite + `/build-screen`

- [ ] **Step 1: Update AS-BUILT**

In `docs/specs/khata-AS-BUILT.md`, in the payment-chains / money-in-transit section, document:
- `transfer_hops.funding_source` + `funding_plan_id` (provenance of the hop's own-funds portion; NULL = untagged).
- Fan-out now emits one ledger entry per `(contributor, funding_source, funding_plan_id)`.
- Editing an origin hop's funding re-stamps downstream fan-out ledger entries (`restamp_downstream`).
- Transit + ledger rows display each transaction at its own stored send-rate (`nativeMinor`); aggregates stay on the global snapshot rate.

- [ ] **Step 2: Cross-reference the design doc**

Add a one-line pointer at the top of `docs/specs/2026-07-08-payment-chains-design.md` and `docs/specs/2026-07-08-funding-3state-design.md`:

```markdown
> Superseded/extended by [2026-07-14 transfer funding + FX display](2026-07-14-transfer-funding-fx-design.md).
```

- [ ] **Step 3: Run the entire test suite**

Run: `python -m pytest -q`
Expected: all green (no regressions across the suite).

- [ ] **Step 4: Headless screen verification**

Run the `/build-screen` protocol for the asset-detail screen (money-in-transit panel + funding flow). Confirm both original defects are resolved:
- `$1000 @94.47` shows `$1,000`;
- a middleman transfer can be tagged as loan-funded and the loan-deployment link reaches the seller ledger.

- [ ] **Step 5: Commit**

```bash
git add docs/specs/khata-AS-BUILT.md docs/specs/2026-07-08-payment-chains-design.md docs/specs/2026-07-08-funding-3state-design.md
git commit -m "docs(transfer): AS-BUILT + cross-refs for funding provenance & native FX display"
```

---

## Self-Review notes (for the executor)

- **Spec coverage:** A1→Task 4+7, A2/A3→Task 7, A4→Task 7 Step 5, B1→Task 1, B2→Task 2, B3→Task 8, B4→Task 3, B5→Task 5, B6→Task 1 (no backfill), tests→Tasks 1-6, docs/verify→Task 9. All spec sections mapped.
- **Sentinel:** `_UNSET` is defined once (Task 2 Step 3) and used by `update_hop` signature (Task 2) and its funding block (Task 5). Do not redefine it.
- **Type consistency:** `_alloc` and `resolve_contributions` both return 4-tuples `(uid, funding_source, funding_plan_id, amount)` after Task 3; every caller (`plan_transfers`, `fan_out_terminal`, `resolve_remainder`, `_reconcile_terminal_entries`) unpacks 4 values.
- **kind filter:** fan-out entries are identified by `source_hop_id == terminal.id AND kind IS NULL`; `transfer_fee` entries are excluded (`_fanout_entries`).
- **Ordering:** Tasks 1→6 keep the pytest suite green at every commit; Tasks 7-8 are frontend (headless-verified); Task 9 is docs + full verification.
