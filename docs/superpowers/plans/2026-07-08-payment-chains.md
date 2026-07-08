# Payment Chains (Transfer Routing) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-hop money routing (buyer2 → buyer1 → seller) with in-transit tracking, split attribution on merged transfers, remainder resolution, receipt confirmation, and a seller plan role.

**Architecture:** New `transfer_hops` + `hop_sources` + `transfer_hop_audit` tables. Non-terminal hops are in-transit and never touch plan totals. A terminal hop (money reached seller) fans out into normal `LedgerEntry` rows — one per ultimate contributor — via the existing `assets.log_payment`, so totals/confirmation/FX/audit machinery is untouched. Everything that consumes upstream money is itself a hop (forward, return, fee), so `outstanding = amount − Σ consumed` is the single accounting rule.

**Tech Stack:** Flask blueprints, SQLAlchemy 2.x mapped_column models, Alembic (batch_alter_table for sqlite), pytest with in-memory sqlite, vanilla-JS static HTML pages.

**Spec:** `docs/specs/2026-07-08-payment-chains-design.md`

## Global Constraints

- Hop `currency` = plan currency in v1 (mirrors LedgerEntry behavior); `fx_rate_micro`/`fx_counter_currency` are display snapshots only, same as entries.
- Plan paid totals remain "Σ ledger entries" — hops NEVER count. Fee entries get `kind='transfer_fee'` and are EXCLUDED from paid sums.
- Allocation of consumed money is greedy oldest-first (by `hop_sources.id`) — same idiom as loan interest pool.
- Alembic head before this work: `fxsnapshot01`. New revision chains from it.
- Every task's commit includes updating `docs/specs/khata-AS-BUILT.md` is deferred to Task 12 (single doc update at end).
- Run tests with `python -m pytest` from repo root (`/Users/assistant/dev/active/khata`).

---

### Task 1: Models + migration ✅

**Files:**
- Create: `src/khata/models/transfer.py`
- Modify: `src/khata/models/__init__.py`
- Modify: `src/khata/models/ledger.py` (add `source_hop_id`)
- Create: `alembic/versions/th1hopchain01_transfer_hops.py`
- Test: `tests/test_transfer_models.py`

**Interfaces:**
- Produces: `TransferHop`, `HopSource`, `TransferHopAudit` models; `LedgerEntry.source_hop_id: int | None`.
- Party fields: exactly one of `{from,to}_user_id / _contact_id / _name` non-null per side.

- [x] **Step 1: Write the failing test**

```python
# tests/test_transfer_models.py
from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, TransferHop, HopSource, LedgerEntry
from khata.services.assets import create_asset_plan


def _dt():
    return datetime(2026, 7, 1, tzinfo=timezone.utc)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u1 = User(email="a@b.com", display_name="B1", password_hash="x")
        u2 = User(email="c@d.com", display_name="B2", password_hash="x")
        s.add_all([u1, u2]); s.flush()
        plan = create_asset_plan(s, owner_id=u1.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        s.commit()
        yield s, u1, u2, plan


def test_hop_roundtrip(ctx):
    s, u1, u2, plan = ctx
    hop = TransferHop(plan_id=plan.id, from_user_id=u2.id, to_user_id=u1.id,
                      amount_minor=1000000, currency="INR", occurred_at=_dt(),
                      method="transfer", logged_by_user_id=u2.id,
                      receipt_status="pending")
    s.add(hop); s.flush()
    hop.chain_id = hop.id
    s.flush()
    got = s.get(TransferHop, hop.id)
    assert got.chain_id == hop.id
    assert got.is_terminal is False
    assert got.resolution is None
    assert got.sources == []


def test_hop_source_links(ctx):
    s, u1, u2, plan = ctx
    h1 = TransferHop(plan_id=plan.id, from_user_id=u2.id, to_user_id=u1.id,
                     amount_minor=1000000, currency="INR", occurred_at=_dt(),
                     method="transfer", logged_by_user_id=u2.id)
    s.add(h1); s.flush(); h1.chain_id = h1.id
    h2 = TransferHop(plan_id=plan.id, from_user_id=u1.id, to_name="Seller",
                     amount_minor=900000, currency="INR", occurred_at=_dt(),
                     method="transfer", logged_by_user_id=u1.id,
                     chain_id=h1.id, is_terminal=True)
    s.add(h2); s.flush()
    s.add(HopSource(hop_id=h2.id, source_hop_id=h1.id, amount_minor=900000))
    s.flush()
    assert h2.sources[0].source_hop_id == h1.id
    assert h1.consumers[0].hop_id == h2.id


def test_ledger_entry_source_hop(ctx):
    s, u1, u2, plan = ctx
    h = TransferHop(plan_id=plan.id, from_user_id=u1.id, to_name="Seller",
                    amount_minor=100, currency="INR", occurred_at=_dt(),
                    method="cash", logged_by_user_id=u1.id, is_terminal=True)
    s.add(h); s.flush(); h.chain_id = h.id
    e = LedgerEntry(plan_id=plan.id, logged_by_user_id=u1.id, direction="out",
                    amount_minor=100, currency="INR", occurred_at=_dt(),
                    source_hop_id=h.id)
    s.add(e); s.flush()
    assert s.get(LedgerEntry, e.id).source_hop_id == h.id
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transfer_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'TransferHop'`

- [x] **Step 3: Write the models**

```python
# src/khata/models/transfer.py
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TransferHop(Base):
    """One hop of money on its way to a plan's seller. Non-terminal hops are
    in-transit and never count toward plan totals; a terminal hop fans out
    into LedgerEntry rows (one per ultimate contributor). Everything that
    consumes upstream money is itself a hop: a forward, a return
    (resolution='returned') or a fee write-off (resolution='fee') — so
    outstanding(hop) = amount − Σ consumed is the only accounting rule."""
    __tablename__ = "transfer_hops"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    # chain groups hops; equals the first hop's id. Set post-flush on roots.
    chain_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    from_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    from_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    from_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    to_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    to_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate_micro: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fx_counter_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    proof_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # agreed | pending | countered — pending only when receiver is a registered
    # user other than the logger (mirrors LedgerEntry.amount_status).
    receipt_status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="agreed", default="agreed")
    counter_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Nature of THIS hop: NULL = normal transfer; 'returned' = money going back
    # to its origin; 'fee' = written off (kept by an intermediary as commission).
    resolution: Mapped[str | None] = mapped_column(String(12), nullable=True)
    logged_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sources: Mapped[list["HopSource"]] = relationship(
        back_populates="hop", cascade="all, delete-orphan",
        foreign_keys="HopSource.hop_id", order_by="HopSource.id")
    consumers: Mapped[list["HopSource"]] = relationship(
        foreign_keys="HopSource.source_hop_id", viewonly=True)
    audit: Mapped[list["TransferHopAudit"]] = relationship(
        back_populates="hop", cascade="all, delete-orphan",
        order_by="TransferHopAudit.changed_at")


class HopSource(Base):
    """Where a hop's money came from. source_hop_id NULL = the from-party's
    own funds. Σ amount_minor over a hop's sources == the hop's amount_minor."""
    __tablename__ = "hop_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    hop_id: Mapped[int] = mapped_column(
        ForeignKey("transfer_hops.id", ondelete="CASCADE"), nullable=False, index=True)
    source_hop_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfer_hops.id"), nullable=True, index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    hop: Mapped["TransferHop"] = relationship(
        back_populates="sources", foreign_keys=[hop_id])


class TransferHopAudit(Base):
    """Immutable create/edit/delete records — mirror of LedgerEntryAudit."""
    __tablename__ = "transfer_hop_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    hop_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfer_hops.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # create | edit | delete
    changed_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)

    hop: Mapped["TransferHop | None"] = relationship(back_populates="audit")
```

In `src/khata/models/__init__.py` add:

```python
from .transfer import TransferHop, HopSource, TransferHopAudit  # noqa: F401
```

In `src/khata/models/ledger.py`, after the `fx_counter_currency` column of `LedgerEntry`, add:

```python
    # Set when this entry was spawned by a terminal transfer hop (payment chains).
    source_hop_id: Mapped[int | None] = mapped_column(
        ForeignKey("transfer_hops.id", ondelete="SET NULL"), nullable=True)
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_transfer_models.py -v`
Expected: 3 PASS

- [x] **Step 5: Write the migration**

```python
# alembic/versions/th1hopchain01_transfer_hops.py
"""transfer_hops, hop_sources, transfer_hop_audit + ledger_entries.source_hop_id

Revision ID: th1hopchain01
Revises: fxsnapshot01
Create Date: 2026-07-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'th1hopchain01'
down_revision: Union[str, None] = 'fxsnapshot01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'transfer_hops',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(),
                  sa.ForeignKey('plans.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('chain_id', sa.BigInteger(), nullable=True, index=True),
        sa.Column('from_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('from_contact_id', sa.Integer(),
                  sa.ForeignKey('contacts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('from_name', sa.Text(), nullable=True),
        sa.Column('to_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('to_contact_id', sa.Integer(),
                  sa.ForeignKey('contacts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('to_name', sa.Text(), nullable=True),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('fx_rate_micro', sa.BigInteger(), nullable=True),
        sa.Column('fx_counter_currency', sa.String(3), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('method', sa.String(20), nullable=True),
        sa.Column('proof_ref', sa.Text(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('is_terminal', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('receipt_status', sa.String(12), nullable=False, server_default='agreed'),
        sa.Column('counter_amount_minor', sa.BigInteger(), nullable=True),
        sa.Column('resolution', sa.String(12), nullable=True),
        sa.Column('logged_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        'hop_sources',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('hop_id', sa.Integer(),
                  sa.ForeignKey('transfer_hops.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('source_hop_id', sa.Integer(),
                  sa.ForeignKey('transfer_hops.id'), nullable=True, index=True),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
    )
    op.create_table(
        'transfer_hop_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(),
                  sa.ForeignKey('plans.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('hop_id', sa.Integer(),
                  sa.ForeignKey('transfer_hops.id', ondelete='SET NULL'), nullable=True, index=True),
        sa.Column('action', sa.String(8), nullable=False),
        sa.Column('changed_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('snapshot', sa.Text(), nullable=False),
        sa.Column('diff', sa.Text(), nullable=True),
    )
    with op.batch_alter_table('ledger_entries') as batch:
        batch.add_column(sa.Column('source_hop_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ledger_entries') as batch:
        batch.drop_column('source_hop_id')
    op.drop_table('transfer_hop_audit')
    op.drop_table('hop_sources')
    op.drop_table('transfer_hops')
```

- [x] **Step 6: Verify migration runs**

Run: `cp khata_dev.db /tmp/khata_mig_test.db && DATABASE_URL=sqlite:////tmp/khata_mig_test.db alembic upgrade head && DATABASE_URL=sqlite:////tmp/khata_mig_test.db alembic downgrade -1 && rm /tmp/khata_mig_test.db`
Expected: upgrade + downgrade both succeed. (If `alembic.ini` uses a different env var, check `alembic/env.py` and match its mechanism.)

- [x] **Step 7: Run full test suite**

Run: `python -m pytest -q`
Expected: all pass (existing suite unaffected)

- [x] **Step 8: Commit**

```bash
git add src/khata/models/transfer.py src/khata/models/__init__.py src/khata/models/ledger.py alembic/versions/th1hopchain01_transfer_hops.py tests/test_transfer_models.py
git commit -m "feat(chains): transfer hop models + migration"
```

---

### Task 2: Transfers service — hop creation, validation, outstanding math ✅

**Files:**
- Create: `src/khata/services/transfers.py`
- Test: `tests/test_transfers_service.py`

**Interfaces:**
- Consumes: models from Task 1; `assets.METHODS`, `assets.ValidationError` pattern.
- Produces:
  - `create_hop(session, *, plan, logged_by_user_id, amount_minor, occurred_at, method, to_user_id=None, to_contact_id=None, to_name=None, from_user_id=None, from_contact_id=None, from_name=None, sources=None, is_terminal=False, resolution=None, proof_ref=None, note=None, fx_rate_micro=None, funding_source="other") -> TransferHop`
    - `sources`: list of `{"source_hop_id": int | None, "amount_minor": int}`; `None`/empty → single own-funds source for full amount.
  - `outstanding(session, hop) -> int`
  - `TransferError(Exception)` base, `TransferValidationError(TransferError)`

- [x] **Step 1: Write the failing test**

```python
# tests/test_transfers_service.py
from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, TransferHop
from khata.services.assets import create_asset_plan
from khata.services import transfers
from khata.services.transfers import TransferValidationError


def _dt(day=1):
    return datetime(2026, 7, day, tzinfo=timezone.utc)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        b1 = User(email="b1@x.com", display_name="B1", password_hash="x")
        b2 = User(email="b2@x.com", display_name="B2", password_hash="x")
        s.add_all([b1, b2]); s.flush()
        plan = create_asset_plan(s, owner_id=b1.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        s.commit()
        yield s, b1, b2, plan


def _hop(s, plan, **kw):
    base = dict(logged_by_user_id=kw.get("logged_by_user_id"),
                amount_minor=1000000, occurred_at=_dt(), method="transfer")
    base.update(kw)
    return transfers.create_hop(s, plan=plan, **base)


def test_root_hop_gets_own_chain_and_own_funds_source(ctx):
    s, b1, b2, plan = ctx
    h = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_user_id=b1.id)
    assert h.chain_id == h.id
    assert len(h.sources) == 1
    assert h.sources[0].source_hop_id is None
    assert h.sources[0].amount_minor == 1000000


def test_receipt_pending_only_for_other_user_receiver(ctx):
    s, b1, b2, plan = ctx
    to_user = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_user_id=b1.id)
    to_name = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_name="Agent")
    to_self = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b1.id, to_user_id=b2.id)
    assert to_user.receipt_status == "pending"
    assert to_name.receipt_status == "agreed"
    assert to_self.receipt_status == "agreed"


def test_exactly_one_party_per_side(ctx):
    s, b1, b2, plan = ctx
    with pytest.raises(TransferValidationError):
        _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id)   # no to-party
    with pytest.raises(TransferValidationError):
        _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id,
             to_user_id=b1.id, to_name="also a name")                 # two to-parties


def test_consuming_hop_joins_chain_and_outstanding_drops(ctx):
    s, b1, b2, plan = ctx
    h1 = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_user_id=b1.id)
    h2 = _hop(s, plan, logged_by_user_id=b1.id, from_user_id=b1.id, to_name="Seller",
              amount_minor=900000, is_terminal=True,
              sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    assert h2.chain_id == h1.chain_id
    assert transfers.outstanding(s, h1) == 100000
    assert transfers.outstanding(s, h2) == 0     # terminal = delivered, nothing to consume


def test_cannot_overconsume_source(ctx):
    s, b1, b2, plan = ctx
    h1 = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_user_id=b1.id)
    with pytest.raises(TransferValidationError):
        _hop(s, plan, logged_by_user_id=b1.id, from_user_id=b1.id, to_name="Seller",
             amount_minor=1100000, is_terminal=True,
             sources=[{"source_hop_id": h1.id, "amount_minor": 1100000}])


def test_sources_must_sum_to_amount(ctx):
    s, b1, b2, plan = ctx
    h1 = _hop(s, plan, logged_by_user_id=b2.id, from_user_id=b2.id, to_user_id=b1.id)
    with pytest.raises(TransferValidationError):
        _hop(s, plan, logged_by_user_id=b1.id, from_user_id=b1.id, to_name="Seller",
             amount_minor=2000000, is_terminal=True,
             sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transfers_service.py -v`
Expected: FAIL — `ModuleNotFoundError: khata.services.transfers`

- [x] **Step 3: Implement the service**

```python
# src/khata/services/transfers.py
"""Payment chains: multi-hop money routing toward a plan's seller.
See docs/specs/2026-07-08-payment-chains-design.md."""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import HopSource, TransferHop, TransferHopAudit
from .assets import METHODS


class TransferError(Exception):
    pass


class TransferValidationError(TransferError):
    pass


def _hop_snapshot(hop: TransferHop) -> str:
    return json.dumps({
        "plan_id": hop.plan_id, "chain_id": hop.chain_id,
        "from_user_id": hop.from_user_id, "from_contact_id": hop.from_contact_id,
        "from_name": hop.from_name,
        "to_user_id": hop.to_user_id, "to_contact_id": hop.to_contact_id,
        "to_name": hop.to_name,
        "amount_minor": hop.amount_minor, "currency": hop.currency,
        "occurred_at": hop.occurred_at.isoformat(), "method": hop.method,
        "proof_ref": hop.proof_ref, "note": hop.note,
        "is_terminal": hop.is_terminal, "receipt_status": hop.receipt_status,
        "resolution": hop.resolution,
        "sources": [{"source_hop_id": src.source_hop_id, "amount_minor": src.amount_minor}
                    for src in hop.sources],
    })


def _write_audit(session, hop, action, actor_uid, diff=None):
    session.add(TransferHopAudit(
        plan_id=hop.plan_id, hop_id=hop.id, action=action,
        changed_by_user_id=actor_uid, snapshot=_hop_snapshot(hop),
        diff=json.dumps(diff) if diff else None))


def _one_party(user_id, contact_id, name, side):
    given = [v for v in (user_id, contact_id, (name or "").strip() or None) if v is not None]
    if len(given) != 1:
        raise TransferValidationError(f"exactly one {side}-party required (user, contact or name)")


def consumed(session: Session, hop: TransferHop) -> int:
    """Total drawn from this hop by downstream hops."""
    rows = session.scalars(select(HopSource).where(HopSource.source_hop_id == hop.id)).all()
    return sum(r.amount_minor for r in rows)


def outstanding(session: Session, hop: TransferHop) -> int:
    """Undelivered remainder sitting with this hop's receiver. Terminal, returned
    and fee hops are endpoints — money stopped there, nothing is outstanding."""
    if hop.is_terminal or hop.resolution in ("returned", "fee"):
        return 0
    return hop.amount_minor - consumed(session, hop)


def _receipt_status_for(to_user_id, logged_by_user_id) -> str:
    if to_user_id is not None and to_user_id != logged_by_user_id:
        return "pending"
    return "agreed"


def create_hop(session: Session, *, plan, logged_by_user_id, amount_minor, occurred_at,
               method, to_user_id=None, to_contact_id=None, to_name=None,
               from_user_id=None, from_contact_id=None, from_name=None,
               sources=None, is_terminal=False, resolution=None,
               proof_ref=None, note=None, fx_rate_micro=None,
               funding_source="other") -> TransferHop:
    if amount_minor <= 0:
        raise TransferValidationError("amount must be > 0")
    if method not in METHODS:
        raise TransferValidationError(f"unknown method: {method}")
    if resolution not in (None, "returned", "fee"):
        raise TransferValidationError(f"unknown resolution: {resolution}")
    if from_user_id is None and from_contact_id is None and not (from_name or "").strip():
        from_user_id = logged_by_user_id     # default: logger sent the money
    _one_party(from_user_id, from_contact_id, from_name, "from")
    _one_party(to_user_id, to_contact_id, to_name, "to")

    src_rows = list(sources or [])
    if not src_rows:
        src_rows = [{"source_hop_id": None, "amount_minor": amount_minor}]
    if sum(r["amount_minor"] for r in src_rows) != amount_minor:
        raise TransferValidationError("sources must sum to the hop amount")
    if any(r["amount_minor"] <= 0 for r in src_rows):
        raise TransferValidationError("source amounts must be > 0")

    chain_id = None
    for r in src_rows:
        if r["source_hop_id"] is None:
            continue
        src_hop = session.get(TransferHop, r["source_hop_id"])
        if src_hop is None or src_hop.plan_id != plan.id:
            raise TransferValidationError("source hop not found on this plan")
        if src_hop.is_terminal:
            raise TransferValidationError("cannot draw from a terminal hop")
        if r["amount_minor"] > outstanding(session, src_hop):
            raise TransferValidationError(
                f"source hop {src_hop.id} has only {outstanding(session, src_hop)} outstanding")
        if chain_id is None:
            chain_id = src_hop.chain_id

    hop = TransferHop(
        plan_id=plan.id, chain_id=chain_id,
        from_user_id=from_user_id, from_contact_id=from_contact_id,
        from_name=(from_name or "").strip() or None,
        to_user_id=to_user_id, to_contact_id=to_contact_id,
        to_name=(to_name or "").strip() or None,
        amount_minor=amount_minor, currency=plan.currency,
        occurred_at=occurred_at, method=method, proof_ref=proof_ref, note=note,
        is_terminal=bool(is_terminal), resolution=resolution,
        receipt_status=_receipt_status_for(to_user_id, logged_by_user_id),
        logged_by_user_id=logged_by_user_id)
    session.add(hop)
    session.flush()
    if hop.chain_id is None:
        hop.chain_id = hop.id
    for r in src_rows:
        session.add(HopSource(hop_id=hop.id, source_hop_id=r["source_hop_id"],
                              amount_minor=r["amount_minor"]))
    session.flush()
    if fx_rate_micro is not None:
        from . import fx
        hop.fx_rate_micro = fx_rate_micro
        hop.fx_counter_currency = fx.counter_currency_for(hop.currency)
        session.flush()
    _write_audit(session, hop, "create", logged_by_user_id)
    return hop
```

NOTE: this sets the FX snapshot directly (mirroring `update_ledger_entry` at `assets.py:220-224`) rather than reusing `fx.snapshot_entry_rate`, which was written for LedgerEntry. If you want auto-rate lookup when no explicit rate is given, read `src/khata/services/fx.py` first and only reuse `snapshot_entry_rate` if it touches nothing entry-specific.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_transfers_service.py -v`
Expected: 6 PASS

- [x] **Step 5: Commit**

```bash
git add src/khata/services/transfers.py tests/test_transfers_service.py
git commit -m "feat(chains): hop creation, chain linking, outstanding math"
```

---

### Task 3: Terminal fan-out — ultimate contributors → ledger entries ✅

**Files:**
- Modify: `src/khata/services/transfers.py`
- Test: `tests/test_transfers_fanout.py`

**Interfaces:**
- Consumes: `assets.log_payment` (Task 0 — existing), `create_hop` (Task 2).
- Produces:
  - `resolve_contributions(session, hop) -> list[tuple[int | None, int]]` — `(user_id, amount)` pairs; `user_id=None` = non-user origin (contact/free-text), attributed to hop logger at entry time. Greedy oldest-first by `HopSource.id`, tracking prior consumption of each upstream hop.
  - `fan_out_terminal(session, *, plan, hop, acting_user_id, funding_source="other") -> list[LedgerEntry]` — called by `create_hop` when `is_terminal=True` and `resolution is None`.

- [x] **Step 1: Write the failing test**

```python
# tests/test_transfers_fanout.py
from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, LedgerEntry
from khata.services.assets import create_asset_plan, asset_state
from khata.services import transfers


def _dt(day=1):
    return datetime(2026, 7, day, tzinfo=timezone.utc)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        b1 = User(email="b1@x.com", display_name="B1", password_hash="x")
        b2 = User(email="b2@x.com", display_name="B2", password_hash="x")
        b3 = User(email="b3@x.com", display_name="B3", password_hash="x")
        s.add_all([b1, b2, b3]); s.flush()
        plan = create_asset_plan(s, owner_id=b1.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        s.commit()
        yield s, b1, b2, b3, plan


def test_merged_terminal_fans_out_per_contributor(ctx):
    s, b1, b2, b3, plan = ctx
    # b2 sends 10k to b1 (in transit)
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=1000000, occurred_at=_dt(1), method="transfer")
    # b1 pays seller 20k: 10k from h1 + 10k own
    h2 = transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                              from_user_id=b1.id, to_name="Seller",
                              amount_minor=2000000, occurred_at=_dt(5), method="transfer",
                              is_terminal=True,
                              sources=[{"source_hop_id": h1.id, "amount_minor": 1000000},
                                       {"source_hop_id": None, "amount_minor": 1000000}])
    entries = s.query(LedgerEntry).filter_by(source_hop_id=h2.id).all()
    by_user = {e.logged_by_user_id: e.amount_minor for e in entries}
    assert by_user == {b2.id: 1000000, b1.id: 1000000}
    st = asset_state(s, plan)
    assert st["paid_to_date_minor"] == 2000000
    # b2's entry attributed by b1 -> needs b2's confirmation (existing machinery)
    e_b2 = next(e for e in entries if e.logged_by_user_id == b2.id)
    assert e_b2.amount_status == "pending"


def test_partial_forward_counts_only_delivered(ctx):
    s, b1, b2, b3, plan = ctx
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=1000000, occurred_at=_dt(1), method="transfer")
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=900000, occurred_at=_dt(5), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    st = asset_state(s, plan)
    assert st["paid_to_date_minor"] == 900000
    assert transfers.outstanding(s, h1) == 100000


def test_multilevel_chain_walks_to_ultimate_origin(ctx):
    s, b1, b2, b3, plan = ctx
    # b3 -> b2 600, b2 adds 400 own and sends 1000 -> b1, b1 sends 900 -> seller
    hA = transfers.create_hop(s, plan=plan, logged_by_user_id=b3.id,
                              from_user_id=b3.id, to_user_id=b2.id,
                              amount_minor=600, occurred_at=_dt(1), method="upi")
    hB = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=1000, occurred_at=_dt(2), method="upi",
                              sources=[{"source_hop_id": hA.id, "amount_minor": 600},
                                       {"source_hop_id": None, "amount_minor": 400}])
    hT = transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                              from_user_id=b1.id, to_name="Seller",
                              amount_minor=900, occurred_at=_dt(3), method="upi",
                              is_terminal=True,
                              sources=[{"source_hop_id": hB.id, "amount_minor": 900}])
    entries = s.query(LedgerEntry).filter_by(source_hop_id=hT.id).all()
    by_user = {e.logged_by_user_id: e.amount_minor for e in entries}
    # greedy oldest-first: 900 from hB = 600 (b3's lineage) + 300 of b2's own 400
    assert by_user == {b3.id: 600, b2.id: 300}


def test_contact_origin_attributed_to_logger(ctx):
    s, b1, b2, b3, plan = ctx
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                              from_name="Uncle", to_user_id=b1.id,
                              amount_minor=500, occurred_at=_dt(1), method="cash")
    hT = transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                              from_user_id=b1.id, to_name="Seller",
                              amount_minor=500, occurred_at=_dt(2), method="cash",
                              is_terminal=True,
                              sources=[{"source_hop_id": h1.id, "amount_minor": 500}])
    entries = s.query(LedgerEntry).filter_by(source_hop_id=hT.id).all()
    assert len(entries) == 1
    assert entries[0].logged_by_user_id == b1.id      # logger stands in for non-user origin
    assert entries[0].amount_minor == 500
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transfers_fanout.py -v`
Expected: FAIL — no entries created (`by_user == {}`)

- [x] **Step 3: Implement fan-out**

Add to `src/khata/services/transfers.py`:

```python
def _own_party_user(hop: TransferHop) -> int | None:
    """The from-party as a user id, or None when the origin is a contact/name."""
    return hop.from_user_id


def resolve_contributions(session: Session, hop: TransferHop) -> list[tuple[int | None, int]]:
    """(user_id, amount) pairs for a hop's money, walked to ultimate origins.
    user_id None = non-user origin (contact / free-text). Greedy oldest-first:
    each upstream hop's own-funds and lineage portions are consumed in
    HopSource.id order, tracking how much earlier consumers already took."""
    def _alloc(h: TransferHop, take: int, taken_before: int) -> list[tuple[int | None, int]]:
        """Allocate `take` units of hop h's money, skipping the first
        `taken_before` units (already claimed by earlier consumers)."""
        out: list[tuple[int | None, int]] = []
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
                    out.append((_own_party_user(h), grab))
                else:
                    up = session.get(TransferHop, src.source_hop_id)
                    out.extend(_alloc(up, grab, overlap_start - pos))
            pos += seg
        return out

    result: list[tuple[int | None, int]] = []
    for src in hop.sources:
        if src.source_hop_id is None:
            result.append((_own_party_user(hop), src.amount_minor))
        else:
            up = session.get(TransferHop, src.source_hop_id)
            prior = _prior_consumption(session, up, before_source_id=src.id)
            result.extend(_alloc(up, src.amount_minor, prior))
    # merge duplicates
    merged: dict[int | None, int] = {}
    for uid, amt in result:
        merged[uid] = merged.get(uid, 0) + amt
    return list(merged.items())


def _prior_consumption(session: Session, hop: TransferHop, *, before_source_id: int) -> int:
    """How much of `hop` was consumed by HopSource rows earlier than the given one."""
    rows = session.scalars(
        select(HopSource).where(HopSource.source_hop_id == hop.id,
                                HopSource.id < before_source_id)).all()
    return sum(r.amount_minor for r in rows)


def fan_out_terminal(session: Session, *, plan, hop: TransferHop, acting_user_id,
                     funding_source="other"):
    """Spawn one LedgerEntry per ultimate contributor of a terminal hop.
    Non-user origins are attributed to the hop logger (spec §Attribution)."""
    from .assets import log_payment
    entries = []
    for uid, amt in resolve_contributions(session, hop):
        entry = log_payment(
            session, plan=plan, user_id=uid if uid is not None else hop.logged_by_user_id,
            amount_minor=amt, occurred_at=hop.occurred_at,
            method=hop.method, funding_source=funding_source,
            proof_ref=hop.proof_ref, note=hop.note,
            acting_user_id=acting_user_id)
        entry.source_hop_id = hop.id
        entries.append(entry)
    session.flush()
    return entries
```

And at the end of `create_hop`, just before `_write_audit(...)`:

```python
    if hop.is_terminal and hop.resolution is None:
        fan_out_terminal(session, plan=plan, hop=hop,
                         acting_user_id=logged_by_user_id,
                         funding_source=funding_source)
```

- [x] **Step 4: Run tests**

Run: `python -m pytest tests/test_transfers_fanout.py tests/test_transfers_service.py -v`
Expected: all PASS

- [x] **Step 5: Commit**

```bash
git add src/khata/services/transfers.py tests/test_transfers_fanout.py
git commit -m "feat(chains): terminal hop fans out ledger entries per ultimate contributor"
```

---

### Task 4: Receipt confirmation (confirm / counter / accept) ✅

**Files:**
- Modify: `src/khata/services/transfers.py`
- Test: `tests/test_transfers_receipt.py`

**Interfaces:**
- Produces: `respond_receipt(session, *, plan, hop_id, actor_uid, action, amount_minor=None) -> TransferHop`
  - `confirm`: receiver (`to_user_id`) accepts → `agreed`.
  - `counter`: receiver proposes different amount → `countered` (`counter_amount_minor` set, `amount_minor` untouched).
  - `accept`: logger accepts the counter → `amount_minor = counter`, `agreed`. Rejected if the new amount would leave the hop over-consumed.
  - `counter` by logger while `countered`: re-counter, back to `pending`.
  - `list_receipt_confirmations(session, user_id) -> list[dict]` — hops pending on this user (mirrors `assets.list_amount_confirmations` shape: keys `hop_id, plan_id, plan_name, amount_minor, counter_amount_minor, status, from_display, logged_at`).

- [x] **Step 1: Write the failing test**

```python
# tests/test_transfers_receipt.py
from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.assets import create_asset_plan
from khata.services import transfers
from khata.services.transfers import TransferValidationError


def _dt():
    return datetime(2026, 7, 1, tzinfo=timezone.utc)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        b1 = User(email="b1@x.com", display_name="B1", password_hash="x")
        b2 = User(email="b2@x.com", display_name="B2", password_hash="x")
        s.add_all([b1, b2]); s.flush()
        plan = create_asset_plan(s, owner_id=b1.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        h = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                                 from_user_id=b2.id, to_user_id=b1.id,
                                 amount_minor=1000000, occurred_at=_dt(), method="transfer")
        s.commit()
        yield s, b1, b2, plan, h


def test_receiver_confirms(ctx):
    s, b1, b2, plan, h = ctx
    transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b1.id, action="confirm")
    assert h.receipt_status == "agreed"


def test_stranger_cannot_confirm(ctx):
    s, b1, b2, plan, h = ctx
    with pytest.raises(TransferValidationError):
        transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b2.id, action="confirm")


def test_counter_then_accept_updates_amount(ctx):
    s, b1, b2, plan, h = ctx
    transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b1.id,
                              action="counter", amount_minor=900000)
    assert h.receipt_status == "countered"
    assert h.counter_amount_minor == 900000
    assert h.amount_minor == 1000000
    transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b2.id, action="accept")
    assert h.amount_minor == 900000
    assert h.receipt_status == "agreed"


def test_accept_blocked_if_counter_below_consumed(ctx):
    s, b1, b2, plan, h = ctx
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=950000, occurred_at=_dt(), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h.id, "amount_minor": 950000}])
    transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b1.id,
                              action="counter", amount_minor=900000)
    with pytest.raises(TransferValidationError):
        transfers.respond_receipt(s, plan=plan, hop_id=h.id, actor_uid=b2.id, action="accept")


def test_pending_receipt_listed_for_receiver(ctx):
    s, b1, b2, plan, h = ctx
    rows = transfers.list_receipt_confirmations(s, b1.id)
    assert any(r["hop_id"] == h.id for r in rows)
    assert transfers.list_receipt_confirmations(s, b2.id) == []
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transfers_receipt.py -v`
Expected: FAIL — `AttributeError: respond_receipt`

- [x] **Step 3: Implement**

Add to `src/khata/services/transfers.py`:

```python
def respond_receipt(session: Session, *, plan, hop_id, actor_uid, action,
                    amount_minor=None) -> TransferHop:
    """Receipt agreement loop, mirroring assets.respond_amount:
    receiver confirms/counters; the LOGGER (not plan owner) accepts/re-counters —
    the hop is a two-party fact between sender-side logger and receiver."""
    hop = session.get(TransferHop, hop_id)
    if hop is None or hop.plan_id != plan.id:
        raise TransferValidationError("hop not found")
    is_receiver = actor_uid == hop.to_user_id
    is_logger = actor_uid == hop.logged_by_user_id

    if action == "confirm":
        if hop.receipt_status != "pending" or not is_receiver:
            raise TransferValidationError("nothing to confirm")
        hop.receipt_status = "agreed"
        hop.counter_amount_minor = None
    elif action == "accept":
        if hop.receipt_status != "countered" or not is_logger:
            raise TransferValidationError("no counter to accept")
        if hop.counter_amount_minor < consumed(session, hop):
            raise TransferValidationError("counter is below the amount already forwarded")
        hop.amount_minor = hop.counter_amount_minor
        _rebase_own_source(session, hop)
        hop.receipt_status = "agreed"
        hop.counter_amount_minor = None
    elif action == "counter":
        if amount_minor is None or amount_minor <= 0:
            raise TransferValidationError("counter amount must be > 0")
        if hop.receipt_status == "pending" and is_receiver:
            hop.counter_amount_minor = amount_minor
            hop.receipt_status = "countered"
        elif hop.receipt_status == "countered" and is_logger:
            if amount_minor < consumed(session, hop):
                raise TransferValidationError("amount is below the amount already forwarded")
            hop.amount_minor = amount_minor
            _rebase_own_source(session, hop)
            hop.counter_amount_minor = None
            hop.receipt_status = "pending"
        else:
            raise TransferValidationError("not your turn to counter")
    else:
        raise TransferValidationError(f"unknown action: {action}")
    session.flush()
    _write_audit(session, hop, "edit", actor_uid,
                 diff={"receipt": {"action": action, "amount_minor": amount_minor}})
    return hop


def _rebase_own_source(session: Session, hop: TransferHop) -> None:
    """After an amount change, resize the hop's own-funds source row so
    sources still sum to amount_minor. Only single own-funds-row hops can be
    resized automatically; hops with upstream sources reject amount changes."""
    own = [s for s in hop.sources if s.source_hop_id is None]
    upstream = [s for s in hop.sources if s.source_hop_id is not None]
    up_total = sum(s.amount_minor for s in upstream)
    if hop.amount_minor < up_total:
        raise TransferValidationError("amount below the upstream money in this hop")
    if own:
        own[0].amount_minor = hop.amount_minor - up_total
        for extra in own[1:]:
            session.delete(extra)
    elif hop.amount_minor != up_total:
        session.add(HopSource(hop_id=hop.id, source_hop_id=None,
                              amount_minor=hop.amount_minor - up_total))
    session.flush()


def list_receipt_confirmations(session: Session, user_id) -> list[dict]:
    """Hops waiting on THIS user: pending receipts where they're the receiver,
    countered receipts where they're the logger."""
    from ..models import Plan, User as _User
    hops = session.scalars(select(TransferHop).where(
        ((TransferHop.receipt_status == "pending") & (TransferHop.to_user_id == user_id)) |
        ((TransferHop.receipt_status == "countered") & (TransferHop.logged_by_user_id == user_id))
    )).all()
    out = []
    for h in hops:
        plan = session.get(Plan, h.plan_id)
        if h.from_user_id:
            u = session.get(_User, h.from_user_id)
            from_display = u.display_name if u else None
        elif h.from_contact_id:
            from ..models import Contact
            c = session.get(Contact, h.from_contact_id)
            from_display = c.name if c else None
        else:
            from_display = h.from_name
        out.append({"hop_id": h.id, "plan_id": h.plan_id,
                    "plan_name": plan.name if plan else None,
                    "amount_minor": h.amount_minor,
                    "counter_amount_minor": h.counter_amount_minor,
                    "status": h.receipt_status, "from_display": from_display,
                    "logged_at": h.created_at.isoformat() if h.created_at else None})
    return out
```

- [x] **Step 4: Run tests**

Run: `python -m pytest tests/test_transfers_receipt.py -v`
Expected: 5 PASS

- [x] **Step 5: Commit**

```bash
git add src/khata/services/transfers.py tests/test_transfers_receipt.py
git commit -m "feat(chains): hop receipt confirm/counter/accept + pending list"
```

---

### Task 5: Edit/delete guards + remainder resolutions (return / fee) ✅

**Files:**
- Modify: `src/khata/services/transfers.py`
- Modify: `src/khata/services/assets.py` (exclude `kind='transfer_fee'` from paid)
- Test: `tests/test_transfers_guards.py`

**Interfaces:**
- Produces:
  - `update_hop(session, *, plan, hop_id, acting_user_id, **fields) -> TransferHop` — editable: `occurred_at, method, proof_ref, note, fx_rate_micro, amount_minor` (amount via `_rebase_own_source` rules; re-opens receipt if receiver is another user). NOT editable: parties, is_terminal, sources.
  - `delete_hop(session, *, plan, hop_id, acting_user_id) -> None` — blocked while any downstream hop consumes it; terminal hop delete also deletes its spawned `LedgerEntry` rows (via `assets.delete_ledger_entry` so entry audit records survive).
  - `resolve_remainder(session, *, plan, hop_id, acting_user_id, action, occurred_at, amount_minor=None, method="transfer", note=None) -> TransferHop` — `action` `'return'|'fee'`; default amount = full outstanding; creates a consuming hop with `resolution='returned'|'fee'`; `'fee'` additionally spawns a `LedgerEntry(kind='transfer_fee')` per ultimate contributor of the consumed money.

- [x] **Step 1: Write the failing test**

```python
# tests/test_transfers_guards.py
from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, LedgerEntry, TransferHop
from khata.services.assets import create_asset_plan, asset_state
from khata.services import transfers
from khata.services.transfers import TransferValidationError


def _dt(day=1):
    return datetime(2026, 7, day, tzinfo=timezone.utc)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        b1 = User(email="b1@x.com", display_name="B1", password_hash="x")
        b2 = User(email="b2@x.com", display_name="B2", password_hash="x")
        s.add_all([b1, b2]); s.flush()
        plan = create_asset_plan(s, owner_id=b1.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                                  from_user_id=b2.id, to_user_id=b1.id,
                                  amount_minor=1000000, occurred_at=_dt(1), method="transfer")
        s.commit()
        yield s, b1, b2, plan, h1


def test_cannot_delete_consumed_hop(ctx):
    s, b1, b2, plan, h1 = ctx
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=900000, occurred_at=_dt(5), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    with pytest.raises(TransferValidationError):
        transfers.delete_hop(s, plan=plan, hop_id=h1.id, acting_user_id=b2.id)


def test_delete_terminal_removes_spawned_entries(ctx):
    s, b1, b2, plan, h1 = ctx
    hT = transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                              from_user_id=b1.id, to_name="Seller",
                              amount_minor=900000, occurred_at=_dt(5), method="transfer",
                              is_terminal=True,
                              sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    assert s.query(LedgerEntry).filter_by(source_hop_id=hT.id).count() == 1
    transfers.delete_hop(s, plan=plan, hop_id=hT.id, acting_user_id=b1.id)
    assert s.query(LedgerEntry).filter_by(source_hop_id=hT.id).count() == 0
    assert transfers.outstanding(s, h1) == 1000000    # freed back up


def test_cannot_shrink_amount_below_consumed(ctx):
    s, b1, b2, plan, h1 = ctx
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=900000, occurred_at=_dt(5), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    with pytest.raises(TransferValidationError):
        transfers.update_hop(s, plan=plan, hop_id=h1.id, acting_user_id=b2.id,
                             amount_minor=800000)


def test_return_resolution_closes_outstanding(ctx):
    s, b1, b2, plan, h1 = ctx
    r = transfers.resolve_remainder(s, plan=plan, hop_id=h1.id, acting_user_id=b1.id,
                                    action="return", occurred_at=_dt(9))
    assert r.resolution == "returned"
    assert r.amount_minor == 1000000
    assert r.to_user_id == b2.id            # back to origin party
    assert transfers.outstanding(s, h1) == 0
    assert asset_state(s, plan)["paid_to_date_minor"] == 0


def test_fee_resolution_creates_flagged_entry_not_counted_in_paid(ctx):
    s, b1, b2, plan, h1 = ctx
    transfers.resolve_remainder(s, plan=plan, hop_id=h1.id, acting_user_id=b1.id,
                                action="fee", occurred_at=_dt(9), amount_minor=50000,
                                note="agent commission")
    fee_entries = s.query(LedgerEntry).filter_by(kind="transfer_fee").all()
    assert len(fee_entries) == 1
    assert fee_entries[0].logged_by_user_id == b2.id      # ultimate origin pays the fee
    assert fee_entries[0].amount_minor == 50000
    st = asset_state(s, plan)
    assert st["paid_to_date_minor"] == 0                  # fee never counts as paid
    assert transfers.outstanding(s, h1) == 950000
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transfers_guards.py -v`
Expected: FAIL — `AttributeError: delete_hop`

- [x] **Step 3: Implement**

Add to `src/khata/services/transfers.py`:

```python
def update_hop(session: Session, *, plan, hop_id, acting_user_id,
               amount_minor=None, occurred_at=None, method=None,
               proof_ref=None, note=None, fx_rate_micro=None) -> TransferHop:
    hop = session.get(TransferHop, hop_id)
    if hop is None or hop.plan_id != plan.id:
        raise TransferValidationError("hop not found")
    diff = {}
    if amount_minor is not None and amount_minor != hop.amount_minor:
        if amount_minor <= 0:
            raise TransferValidationError("amount must be > 0")
        if amount_minor < consumed(session, hop):
            raise TransferValidationError("amount below what downstream hops already consumed")
        if hop.is_terminal:
            raise TransferValidationError(
                "edit a terminal hop by deleting and re-logging it (entries were fanned out)")
        diff["amount_minor"] = {"old": hop.amount_minor, "new": amount_minor}
        hop.amount_minor = amount_minor
        _rebase_own_source(session, hop)
        if hop.to_user_id and hop.to_user_id != acting_user_id:
            hop.receipt_status = "pending"          # re-opens receipt agreement
            hop.counter_amount_minor = None
    if occurred_at is not None:
        diff["occurred_at"] = {"old": hop.occurred_at.isoformat(),
                               "new": occurred_at.isoformat()}
        hop.occurred_at = occurred_at
    if method is not None:
        if method not in METHODS:
            raise TransferValidationError(f"unknown method: {method}")
        diff["method"] = {"old": hop.method, "new": method}
        hop.method = method
    if proof_ref is not None:
        hop.proof_ref = proof_ref
    if note is not None:
        hop.note = note
    if fx_rate_micro is not None:
        from . import fx
        hop.fx_rate_micro = fx_rate_micro
        hop.fx_counter_currency = fx.counter_currency_for(hop.currency)
    session.flush()
    if diff:
        _write_audit(session, hop, "edit", acting_user_id, diff)
    return hop


def delete_hop(session: Session, *, plan, hop_id, acting_user_id) -> None:
    hop = session.get(TransferHop, hop_id)
    if hop is None or hop.plan_id != plan.id:
        raise TransferValidationError("hop not found")
    if consumed(session, hop) > 0:
        raise TransferValidationError("downstream hops draw from this one — unwind them first")
    if hop.is_terminal:
        from .assets import delete_ledger_entry
        from ..models import LedgerEntry
        entries = session.scalars(select(LedgerEntry).where(
            LedgerEntry.source_hop_id == hop.id)).all()
        for e in entries:
            delete_ledger_entry(session, plan=plan, entry_id=e.id,
                                acting_user_id=acting_user_id)
    _write_audit(session, hop, "delete", acting_user_id)
    session.flush()
    session.delete(hop)
    session.flush()


def resolve_remainder(session: Session, *, plan, hop_id, acting_user_id, action,
                      occurred_at, amount_minor=None, method="transfer",
                      note=None) -> TransferHop:
    """Close (part of) a hop's outstanding remainder: send it back to the origin
    party ('return') or write it off as a fee kept by the holder ('fee')."""
    hop = session.get(TransferHop, hop_id)
    if hop is None or hop.plan_id != plan.id:
        raise TransferValidationError("hop not found")
    if action not in ("return", "fee"):
        raise TransferValidationError(f"unknown action: {action}")
    out = outstanding(session, hop)
    amt = amount_minor if amount_minor is not None else out
    if amt <= 0 or amt > out:
        raise TransferValidationError(f"amount must be within outstanding ({out})")

    # Money flows FROM the current holder (hop's receiver) back/off.
    holder = dict(from_user_id=hop.to_user_id, from_contact_id=hop.to_contact_id,
                  from_name=hop.to_name)
    if action == "return":
        dest = dict(to_user_id=hop.from_user_id, to_contact_id=hop.from_contact_id,
                    to_name=hop.from_name)
        resolution = "returned"
    else:
        dest = dict(to_name=(note or "fee"))
        resolution = "fee"

    res_hop = create_hop(session, plan=plan, logged_by_user_id=acting_user_id,
                         amount_minor=amt, occurred_at=occurred_at, method=method,
                         sources=[{"source_hop_id": hop.id, "amount_minor": amt}],
                         resolution=resolution, note=note, **holder, **dest)

    if action == "fee":
        from .assets import log_payment
        for uid, part in resolve_contributions(session, res_hop):
            entry = log_payment(
                session, plan=plan,
                user_id=uid if uid is not None else acting_user_id,
                amount_minor=part, occurred_at=occurred_at, method=method,
                funding_source="other", note=note or "transfer fee",
                acting_user_id=acting_user_id)
            entry.kind = "transfer_fee"
            entry.source_hop_id = res_hop.id
        session.flush()
    return res_hop
```

Also in `create_hop`, receipt for return hops back to a user should NOT be pending when the destination equals the origin user who already knows — keep it simple: receipt rules unchanged (a returned-to user confirming receipt is correct behavior).

In `src/khata/services/assets.py` line ~386, change the paid computation to exclude fees:

```python
    outs = [e for e in plan.ledger_entries
            if e.direction == "out" and e.kind != "transfer_fee"]
```

And add a fees line to the state dict (after `"overpaid_minor"`):

```python
        "fees_minor": sum(e.amount_minor for e in plan.ledger_entries
                          if e.kind == "transfer_fee"),
```

Then grep the other state functions and apply the same exclusion wherever entries are summed into a "paid/received" figure:

Run: `grep -n "direction == \"out\"\|direction=='out'\|amount_minor for e" src/khata/services/loans.py src/khata/services/chits.py src/khata/services/holdings.py src/khata/services/retirement.py`
For each hit that sums toward a paid/progress total, add `and e.kind != "transfer_fee"`. (Loan/chit entries are all kind-tagged already — verify rather than assume; if their sums already filter on specific kinds, `transfer_fee` is naturally excluded and no change is needed.)

- [x] **Step 4: Run tests**

Run: `python -m pytest tests/test_transfers_guards.py tests/test_transfers_fanout.py tests/test_transfers_service.py tests/test_transfers_receipt.py -v && python -m pytest -q`
Expected: all PASS, full suite green

- [x] **Step 5: Commit**

```bash
git add src/khata/services/transfers.py src/khata/services/assets.py tests/test_transfers_guards.py
git commit -m "feat(chains): hop edit/delete guards + return/fee remainder resolutions"
```

---

### Task 6: Chain listing + in-transit summary (service) ✅

**Files:**
- Modify: `src/khata/services/transfers.py`
- Test: `tests/test_transfers_state.py`

**Interfaces:**
- Produces: `plan_transfers(session, plan) -> dict` with shape:

```python
{
  "in_transit_minor": int,            # Σ outstanding over open non-terminal hops
  "chains": [
    {"chain_id": int,
     "closed": bool,                  # every non-terminal hop fully consumed/resolved
     "hops": [
       {"id": int, "seq_in_chain": int,   # by occurred_at then id
        "from": {"user_id": ..., "contact_id": ..., "name": ..., "display": str},
        "to":   {...same...},
        "amount_minor": int, "outstanding_minor": int, "consumed_minor": int,
        "occurred_at": iso, "method": str, "note": str, "has_proof": bool,
        "is_terminal": bool, "resolution": str | None,
        "receipt_status": str, "counter_amount_minor": int | None,
        "days_held": int,             # (today − occurred_at).days for open hops else 0
        "logged_by_user_id": int,
        "sources": [{"source_hop_id": int | None, "amount_minor": int}]}
     ]}
  ]
}
```
- `display` resolution: user → display_name, contact → contact name, else raw name.

- [x] **Step 1: Write the failing test**

```python
# tests/test_transfers_state.py
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
        b1 = User(email="b1@x.com", display_name="B1", password_hash="x")
        b2 = User(email="b2@x.com", display_name="B2", password_hash="x")
        s.add_all([b1, b2]); s.flush()
        plan = create_asset_plan(s, owner_id=b1.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        s.commit()
        yield s, b1, b2, plan


def test_plan_transfers_summary(ctx):
    s, b1, b2, plan = ctx
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=1000000, occurred_at=_dt(1), method="transfer")
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=900000, occurred_at=_dt(5), method="transfer",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 900000}])
    st = transfers.plan_transfers(s, plan)
    assert st["in_transit_minor"] == 100000
    assert len(st["chains"]) == 1
    ch = st["chains"][0]
    assert ch["chain_id"] == h1.chain_id
    assert ch["closed"] is False
    assert [h["amount_minor"] for h in ch["hops"]] == [1000000, 900000]
    assert ch["hops"][0]["from"]["display"] == "B2"
    assert ch["hops"][0]["outstanding_minor"] == 100000
    assert ch["hops"][1]["is_terminal"] is True


def test_closed_chain_flag(ctx):
    s, b1, b2, plan = ctx
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=b2.id,
                              from_user_id=b2.id, to_user_id=b1.id,
                              amount_minor=500, occurred_at=_dt(1), method="cash")
    transfers.create_hop(s, plan=plan, logged_by_user_id=b1.id,
                         from_user_id=b1.id, to_name="Seller",
                         amount_minor=500, occurred_at=_dt(2), method="cash",
                         is_terminal=True,
                         sources=[{"source_hop_id": h1.id, "amount_minor": 500}])
    st = transfers.plan_transfers(s, plan)
    assert st["in_transit_minor"] == 0
    assert st["chains"][0]["closed"] is True
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transfers_state.py -v`
Expected: FAIL — `AttributeError: plan_transfers`

- [x] **Step 3: Implement**

```python
def _party_dict(session, user_id, contact_id, name):
    display = name
    if user_id is not None:
        from ..models import User as _User
        u = session.get(_User, user_id)
        display = u.display_name if u else None
    elif contact_id is not None:
        from ..models import Contact
        c = session.get(Contact, contact_id)
        display = c.name if c else None
    return {"user_id": user_id, "contact_id": contact_id, "name": name,
            "display": display}


def plan_transfers(session: Session, plan) -> dict:
    from datetime import date
    hops = session.scalars(select(TransferHop)
                           .where(TransferHop.plan_id == plan.id)
                           .order_by(TransferHop.occurred_at, TransferHop.id)).all()
    chains: dict[int, list] = {}
    for h in hops:
        chains.setdefault(h.chain_id, []).append(h)

    in_transit = 0
    out_chains = []
    for cid, chain_hops in chains.items():
        rows, closed = [], True
        for i, h in enumerate(chain_hops):
            out = outstanding(session, h)
            if out > 0:
                closed = False
                in_transit += out
            rows.append({
                "id": h.id, "seq_in_chain": i + 1,
                "from": _party_dict(session, h.from_user_id, h.from_contact_id, h.from_name),
                "to": _party_dict(session, h.to_user_id, h.to_contact_id, h.to_name),
                "amount_minor": h.amount_minor,
                "outstanding_minor": out,
                "consumed_minor": consumed(session, h),
                "occurred_at": h.occurred_at.isoformat(),
                "method": h.method, "note": h.note,
                "has_proof": bool(h.proof_ref),
                "is_terminal": h.is_terminal, "resolution": h.resolution,
                "receipt_status": h.receipt_status,
                "counter_amount_minor": h.counter_amount_minor,
                "days_held": ((date.today() - h.occurred_at.date()).days if out > 0 else 0),
                "logged_by_user_id": h.logged_by_user_id,
                "sources": [{"source_hop_id": s_.source_hop_id,
                             "amount_minor": s_.amount_minor} for s_ in h.sources]})
        out_chains.append({"chain_id": cid, "closed": closed, "hops": rows})
    out_chains.sort(key=lambda c: c["hops"][0]["occurred_at"], reverse=True)
    return {"in_transit_minor": in_transit, "chains": out_chains}
```

- [x] **Step 4: Run tests**

Run: `python -m pytest tests/test_transfers_state.py -v`
Expected: 2 PASS

- [x] **Step 5: Commit**

```bash
git add src/khata/services/transfers.py tests/test_transfers_state.py
git commit -m "feat(chains): plan_transfers chain listing + in-transit summary"
```

---

### Task 7: Seller role ✅

**Files:**
- Modify: `src/khata/services/sharing.py` (role param + `role_of` helper)
- Modify: `src/khata/api/plans.py` (`add_member` accepts role; write guards)
- Test: `tests/test_seller_role.py`

**Interfaces:**
- Consumes: `PlanMembership.role` (String(16) — 'seller' fits, no migration).
- Produces:
  - `sharing.add_member(session, *, plan, email, role="contributor")` — role in `{"contributor", "seller"}`.
  - `sharing.role_of(session, *, plan, user_id) -> str | None` — 'owner' for the owner, membership role for members, None otherwise.
  - API guard: role 'seller' gets 403 from `POST /payments`, `POST/PATCH/DELETE /entries`, and (Task 8) all hop-mutating endpoints. Seller CAN read plan detail + transfers.

- [x] **Step 1: Write the failing test**

```python
# tests/test_seller_role.py
from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.assets import create_asset_plan
from khata.services import sharing


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        owner = User(email="o@x.com", display_name="O", password_hash="x")
        seller = User(email="s@x.com", display_name="S", password_hash="x")
        s.add_all([owner, seller]); s.flush()
        plan = create_asset_plan(s, owner_id=owner.id, name="Plot",
                                 currency="INR", total_price_minor=10000000)
        s.commit()
        yield s, owner, seller, plan


def test_add_member_with_seller_role(ctx):
    s, owner, seller, plan = ctx
    m = sharing.add_member(s, plan=plan, email="s@x.com", role="seller")
    assert m.role == "seller"


def test_role_of(ctx):
    s, owner, seller, plan = ctx
    sharing.add_member(s, plan=plan, email="s@x.com", role="seller")
    assert sharing.role_of(s, plan=plan, user_id=owner.id) == "owner"
    assert sharing.role_of(s, plan=plan, user_id=seller.id) == "seller"
    assert sharing.role_of(s, plan=plan, user_id=99999) is None


def test_invalid_role_rejected(ctx):
    s, owner, seller, plan = ctx
    with pytest.raises(ValueError):
        sharing.add_member(s, plan=plan, email="s@x.com", role="superadmin")
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_seller_role.py -v`
Expected: FAIL — `add_member() got an unexpected keyword argument 'role'`

- [x] **Step 3: Implement**

In `src/khata/services/sharing.py`, change `add_member` signature and the membership construction (currently `sharing.py:52-72`):

```python
ROLES = {"contributor", "seller"}


def add_member(session: Session, *, plan: Plan, email: str,
               role: str = "contributor") -> PlanMembership:
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    email = (email or "").strip().lower()
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        raise UserNotFound(email)
    if user.id == plan.owner_user_id:
        raise AlreadyMember("owner is already on the plan")
    existing = next((m for m in plan.memberships if m.user_id == user.id), None)
    if existing is not None:
        if existing.status == "declined":
            existing.status = "invited"
            existing.role = role
            session.flush()
            return existing
        raise AlreadyMember(email)
    membership = PlanMembership(plan_id=plan.id, user_id=user.id, role=role,
                                status="invited")
    plan.memberships.append(membership)
    session.flush()
    return membership


def role_of(session: Session, *, plan: Plan, user_id: int) -> str | None:
    if user_id == plan.owner_user_id:
        return "owner"
    m = next((m for m in plan.memberships
              if m.user_id == user_id and m.status == "active"), None)
    return m.role if m else None
```

In `src/khata/api/plans.py`:
- `add_member` route (`plans.py:771`): pass `role=(data.get("role") or "contributor")` to `sharing.add_member`; catch `ValueError` → 400.
- Add helper near `_accessible_plan`:

```python
def _writable_plan(user, plan_id):
    """Accessible plan where the user may log/edit money (sellers are read-only)."""
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return None, err
    if sharing.role_of(g.db, plan=plan, user_id=user.id) == "seller":
        return None, (jsonify(error="forbidden", detail="sellers are read-only"), 403)
    return plan, None
```

- Switch `payment()` (`plans.py:362`) and `respond_amount()` write path to `_writable_plan`; in `_editable_entry` add the same seller check right after `_accessible_plan`.
- `get_members` (`plans.py:798`): confirm role is already included in the member dicts (`sharing.list_members`) — if not, add `"role": m.role`.

- [x] **Step 4: Run tests**

Run: `python -m pytest tests/test_seller_role.py tests/test_share_owner_api.py tests/test_invites.py -v`
Expected: PASS (existing membership tests unaffected — default role unchanged)

- [x] **Step 5: Commit**

```bash
git add src/khata/services/sharing.py src/khata/api/plans.py tests/test_seller_role.py
git commit -m "feat(chains): seller plan role — assignable, read-only"
```

---

### Task 8: Hops API ✅

**Files:**
- Create: `src/khata/api/transfers.py`
- Modify: `src/khata/__init__.py` (register blueprint)
- Modify: `src/khata/api/confirmations.py` (include hop receipts)
- Test: `tests/test_transfers_api.py`

**Interfaces:**
- Produces routes (all require auth; plan must be accessible; mutations require non-seller):
  - `POST /api/plans/<pid>/hops` — body `{amount, occurred_at, method, to_user_id|to_contact_id|to_name, from_user_id|from_contact_id|from_name?, sources?: [{source_hop_id, amount}], is_terminal?, funding_source?, proof_ref?, note?, fx_rate_micro?}`. Amounts in display units → `to_minor`. 201 `{hop: {...}, transfers: plan_transfers(...)}`.
  - `GET /api/plans/<pid>/hops` — 200 `plan_transfers(...)` (currency-formatted amounts added client-side; API returns minor units).
  - `PATCH /api/plans/<pid>/hops/<hid>` — editable fields per `update_hop`.
  - `DELETE /api/plans/<pid>/hops/<hid>`.
  - `POST /api/plans/<pid>/hops/<hid>/receipt` — `{action: confirm|counter|accept, amount?}`.
  - `POST /api/plans/<pid>/hops/<hid>/resolve` — `{action: return|fee, amount?, occurred_at?, method?, note?}`.
- Terminal-auto-detection at the API layer: if `to_contact_id` equals the plan's `asset.seller_contact_id`, or `to_user_id` has role 'seller', force `is_terminal=True`.
- `GET /api/confirmations` response gains `"receipts": transfers.list_receipt_confirmations(...)` alongside its existing list.

- [x] **Step 1: Write the failing test**

Follow the client-fixture auth pattern used in `tests/test_plans_api.py` (read its top 60 lines first for register/login helpers — reuse them verbatim).

```python
# tests/test_transfers_api.py — sketch; adapt auth helpers from test_plans_api.py
def test_hop_lifecycle(client):
    # register two users, create asset plan as u1, add u2 as member (accept invite)
    # u2 logs in, POST hop 10000 to u1 -> 201, receipt pending
    # u1 logs in, GET /hops -> in_transit_minor == 1000000 (minor units)
    # u1 POST /hops/<id>/receipt {action: confirm} -> 200 agreed
    # u1 POST terminal hop 9000 to_name Seller, sources=[{source_hop_id, amount: 9000}]
    # GET /api/plans/<pid> -> state.paid_to_date_minor == 900000
    # GET /hops -> in_transit 100000
    # u1 POST /hops/<id>/resolve {action: return} -> in_transit 0
    ...


def test_seller_role_read_only(client):
    # owner adds seller-role user; seller accepts invite
    # seller GET /api/plans/<pid> -> 200
    # seller GET /api/plans/<pid>/hops -> 200
    # seller POST /api/plans/<pid>/hops -> 403
    # seller POST /api/plans/<pid>/payments -> 403
    ...
```

Write these as real tests (no `...`) using the repo's existing API-test helpers; assert the exact status codes and JSON keys shown in the comments.

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_transfers_api.py -v`
Expected: FAIL — 404 (routes don't exist)

- [x] **Step 3: Implement the blueprint**

```python
# src/khata/api/transfers.py
from flask import Blueprint, g, jsonify, request

from ..models import Plan
from ..money import to_minor
from ..services import sharing, transfers
from ..services.transfers import TransferError
from .auth import current_user
from .plans import _accessible_plan, _writable_plan, _parse_dt, _fx_rate_arg, _FxRateArgError

bp = Blueprint("transfers", __name__, url_prefix="/api/plans")


def _hop_json(hop):
    return {"id": hop.id, "chain_id": hop.chain_id, "amount_minor": hop.amount_minor,
            "is_terminal": hop.is_terminal, "receipt_status": hop.receipt_status,
            "resolution": hop.resolution}


def _auto_terminal(plan, to_user_id, to_contact_id):
    if to_contact_id and plan.asset and plan.asset.seller_contact_id == to_contact_id:
        return True
    if to_user_id and sharing.role_of(g.db, plan=plan, user_id=to_user_id) == "seller":
        return True
    return False


@bp.post("/<int:plan_id>/hops")
def create_hop(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _writable_plan(user, plan_id)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    try:
        to_uid = int(d["to_user_id"]) if d.get("to_user_id") else None
        to_cid = int(d["to_contact_id"]) if d.get("to_contact_id") else None
        sources = [{"source_hop_id": (int(r["source_hop_id"]) if r.get("source_hop_id") else None),
                    "amount_minor": to_minor(r.get("amount", ""), plan.currency)}
                   for r in (d.get("sources") or [])]
        hop = transfers.create_hop(
            g.db, plan=plan, logged_by_user_id=user.id,
            amount_minor=to_minor(d.get("amount", ""), plan.currency),
            occurred_at=_parse_dt(d.get("occurred_at")),
            method=d.get("method", ""),
            to_user_id=to_uid, to_contact_id=to_cid, to_name=d.get("to_name"),
            from_user_id=int(d["from_user_id"]) if d.get("from_user_id") else None,
            from_contact_id=int(d["from_contact_id"]) if d.get("from_contact_id") else None,
            from_name=d.get("from_name"),
            sources=sources or None,
            is_terminal=bool(d.get("is_terminal")) or _auto_terminal(plan, to_uid, to_cid),
            funding_source=d.get("funding_source") or "other",
            proof_ref=d.get("proof_ref"), note=d.get("note"),
            fx_rate_micro=_fx_rate_arg(d))
        g.db.commit()
    except _FxRateArgError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 422
    except (TransferError, ValueError, TypeError, KeyError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(hop=_hop_json(hop), transfers=transfers.plan_transfers(g.db, plan)), 201


@bp.get("/<int:plan_id>/hops")
def list_hops(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)
    if err:
        return err
    return jsonify(transfers.plan_transfers(g.db, plan)), 200


@bp.patch("/<int:plan_id>/hops/<int:hop_id>")
def patch_hop(plan_id, hop_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _writable_plan(user, plan_id)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    try:
        fields = {}
        if "amount" in d:
            fields["amount_minor"] = to_minor(d.get("amount", ""), plan.currency)
        if "occurred_at" in d:
            fields["occurred_at"] = _parse_dt(d.get("occurred_at"))
        for k in ("method", "proof_ref", "note"):
            if k in d:
                fields[k] = d.get(k)
        if "fx_rate_micro" in d:
            fields["fx_rate_micro"] = _fx_rate_arg(d)
        transfers.update_hop(g.db, plan=plan, hop_id=hop_id,
                             acting_user_id=user.id, **fields)
        g.db.commit()
    except (TransferError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(transfers.plan_transfers(g.db, plan)), 200


@bp.delete("/<int:plan_id>/hops/<int:hop_id>")
def delete_hop(plan_id, hop_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _writable_plan(user, plan_id)
    if err:
        return err
    try:
        transfers.delete_hop(g.db, plan=plan, hop_id=hop_id, acting_user_id=user.id)
        g.db.commit()
    except (TransferError, ValueError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(transfers.plan_transfers(g.db, plan)), 200


@bp.post("/<int:plan_id>/hops/<int:hop_id>/receipt")
def receipt(plan_id, hop_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)   # receiver may be seller-role: receipts allowed
    if err:
        return err
    d = request.get_json(silent=True) or {}
    try:
        amt = to_minor(d.get("amount", ""), plan.currency) if d.get("amount") else None
        transfers.respond_receipt(g.db, plan=plan, hop_id=hop_id, actor_uid=user.id,
                                  action=(d.get("action") or "").lower(), amount_minor=amt)
        g.db.commit()
    except (TransferError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(transfers.plan_transfers(g.db, plan)), 200


@bp.post("/<int:plan_id>/hops/<int:hop_id>/resolve")
def resolve(plan_id, hop_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _writable_plan(user, plan_id)
    if err:
        return err
    d = request.get_json(silent=True) or {}
    try:
        amt = to_minor(d.get("amount", ""), plan.currency) if d.get("amount") else None
        transfers.resolve_remainder(
            g.db, plan=plan, hop_id=hop_id, acting_user_id=user.id,
            action=(d.get("action") or "").lower(),
            occurred_at=_parse_dt(d.get("occurred_at")),
            amount_minor=amt, method=d.get("method") or "transfer",
            note=d.get("note"))
        g.db.commit()
    except (TransferError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(transfers.plan_transfers(g.db, plan)), 200
```

Register in `src/khata/__init__.py` next to the other blueprints (match the local import style used there):

```python
    from .api.transfers import bp as transfers_bp
    app.register_blueprint(transfers_bp)
```

In `src/khata/api/confirmations.py`: read the file; the endpoint that returns `list_amount_confirmations` gains a sibling key:

```python
    receipts = transfers.list_receipt_confirmations(g.db, user.id)
```

added to its JSON response as `"receipts": receipts` (import `transfers` from `..services`).

- [x] **Step 4: Run tests**

Run: `python -m pytest tests/test_transfers_api.py -v && python -m pytest -q`
Expected: all PASS

- [x] **Step 5: Commit**

```bash
git add src/khata/api/transfers.py src/khata/__init__.py src/khata/api/confirmations.py tests/test_transfers_api.py
git commit -m "feat(chains): hops REST API + receipt confirmations feed"
```

---

### Task 9: UI — shared transfers.js (panel + chain timeline + log-hop form) ✅

**Files:**
- Create: `src/khata/static/assets/transfers.js`
- Modify: `src/khata/static/asset-detail.html` (include script + panel mount + payment-form recipient step)
- Test: manual headless (Step 4) — no unit test for static JS (repo has none).

**Interfaces:**
- Consumes: `GET/POST /api/plans/<pid>/hops`, `POST .../receipt`, `POST .../resolve` (Task 8); global patterns from `asset-detail.html` (`pid`, `fetch` style, `fmtMinor`-style helpers — read the file's existing money-format helper and reuse it, do not invent a new one).
- Produces: `window.KhataTransfers = { mount(el, pid, opts), refresh() }`.

- [x] **Step 1: Read the integration points**

Read `src/khata/static/asset-detail.html` in full. Identify: (a) the ledger/payments section markup + its money formatting helper, (b) the payment modal/form + its submit handler (`~line 1419`), (c) where `sharing.js`/`attach.js` are included. Also read `src/khata/static/assets/sharing.js` top 40 lines for the module pattern used.

- [x] **Step 2: Build `transfers.js`**

Requirements (follow the file's existing vanilla-JS idiom — no framework):

```javascript
// src/khata/static/assets/transfers.js
// Money-in-transit panel + chain timeline for payment chains.
// Mounts into a container on plan detail pages:
//   KhataTransfers.mount(document.getElementById('transit-panel'), PID, {currency:'INR', me:USER_ID})
window.KhataTransfers = (function(){
  let _el=null,_pid=null,_opts={};
  async function _load(){
    const r = await fetch('/api/plans/'+_pid+'/hops');
    if(!r.ok) return {in_transit_minor:0, chains:[]};
    return r.json();
  }
  function _fmt(minor){ return _opts.fmt ? _opts.fmt(minor) : (minor/100).toLocaleString(); }
  function _hopRow(h){
    const who = h.from.display+' → '+h.to.display;
    const badge = h.is_terminal ? 'delivered'
                : h.resolution === 'returned' ? 'returned'
                : h.resolution === 'fee' ? 'fee'
                : h.outstanding_minor>0 ? ('holding '+_fmt(h.outstanding_minor)+' · '+h.days_held+'d')
                : 'forwarded';
    // build DOM row: who, amount, date, method, badge, receipt controls
    // receipt controls only when h.receipt_status==='pending' && h.to.user_id===_opts.me:
    //   [Confirm] [Counter…] -> POST /receipt
    // resolve controls only when h.outstanding_minor>0:
    //   [Return] [Mark fee…] -> POST /resolve
    // ...construct with document.createElement, return the element
  }
  async function refresh(){
    const data = await _load();
    // render: header 'In transit: <fmt(in_transit_minor)>' + one card per chain,
    // vertical timeline of _hopRow(h) for each hop
  }
  function mount(el,pid,opts){ _el=el; _pid=pid; _opts=opts||{}; refresh(); }
  return {mount, refresh};
})();
```

Fill in the `...` DOM construction completely — every control listed in the comments must exist and call its endpoint, then `refresh()` and (if the page exposes it) re-fetch plan state so paid KPIs update. Style with existing classes from `app.css`/`ledger.css` (inspect them; reuse `card`, badge and button classes rather than adding new CSS).

- [x] **Step 3: Wire into asset-detail.html**

1. `<script src="/assets/transfers.js"></script>` next to the sharing.js include.
2. Add `<div id="transit-panel"></div>` section above the ledger list.
3. In the page-load function (`~line 1283` area), after plan fetch: `KhataTransfers.mount(document.getElementById('transit-panel'), pid, {me: ME.id, fmt: <existing formatter>})`.
4. Payment form: add a recipient select at the top —
   - "Paid to seller (final)" → existing behavior (`POST /payments`) **plus**, when any open hops exist, an optional "use money in transit" multi-pick that switches the submit to `POST /hops` with `is_terminal: true` and `sources` built from the picked hops (own-funds remainder auto-computed as `amount − Σ picked`).
   - "Sent to someone (in transit)" → recipient picker (plan members from `MEMBERS`, contacts from `CONTACTS`, or free-text) → submit to `POST /hops`.
   Reuse the form's existing amount/date/method/proof/note inputs for both paths.

- [x] **Step 4: Headless verify (per repo protocol)**

Follow `.claude/commands/build-screen.md` protocol. Minimum:

```bash
./run-app.sh   # or the dev-server command the protocol specifies
```

Then with browser tools or curl: register 2 users, create plan, log in-transit hop as user2, confirm receipt as user1, log terminal hop drawing the transit money, verify: in-transit panel shows correct amounts before/after, paid KPI updates, chain timeline renders hops in order, resolve-return zeroes the panel. Screenshot the panel + timeline states.

- [x] **Step 5: Commit**

```bash
git add src/khata/static/assets/transfers.js src/khata/static/asset-detail.html
git commit -m "feat(chains): in-transit panel, chain timeline, hop logging UI on asset detail"
```

---

### Task 10: Wire panel into other plan-detail pages

**Files:**
- Modify: `src/khata/static/loan-detail.html`, `src/khata/static/chit-detail.html`, `src/khata/static/holding-detail.html`, `src/khata/static/retirement-detail.html`

**Interfaces:**
- Consumes: `KhataTransfers.mount` (Task 9).

- [ ] **Step 1: Add panel to each page**

For each file: add the script include, a `<div id="transit-panel"></div>` in the same relative position (above the ledger/entries section), and the `mount(...)` call in the page-load function with that page's formatter + user id. Read each page's load function first — they differ slightly.

- [ ] **Step 2: Headless verify**

Load each detail page for a plan of that type with zero hops — the panel must render nothing/an empty state and cause no JS console errors. Log one hop on a loan plan via API and confirm the panel appears.

- [ ] **Step 3: Commit**

```bash
git add src/khata/static/loan-detail.html src/khata/static/chit-detail.html src/khata/static/holding-detail.html src/khata/static/retirement-detail.html
git commit -m "feat(chains): transit panel on loan/chit/holding/retirement detail pages"
```

---

### Task 11: Seller assignment UI + confirmations inbox

**Files:**
- Modify: `src/khata/static/asset-detail.html` (member-add form gets role select)
- Modify: the page that renders `/api/confirmations` (grep: `grep -rn "confirmations" src/khata/static/` — likely `app.html` or a shared JS) to also render the new `receipts` array with Confirm / Counter buttons hitting `POST /api/plans/<pid>/hops/<hid>/receipt`.

**Interfaces:**
- Consumes: Task 7 role param on `POST /api/plans/<pid>/members`; Task 8 `receipts` key on `GET /api/confirmations`.

- [ ] **Step 1: Member form role select**

In asset-detail's add-member form add `<select>` with options `contributor` (default) / `seller`; include `role` in the POST body. Render existing members' role badge (data already in `/members` response per Task 7).

- [ ] **Step 2: Confirmations inbox renders receipts**

Find the confirmations rendering code, append a "Transfers to confirm" group rendering each receipt row: `from_display`, amount, plan name, [Confirm] [Counter…] buttons → `POST /api/plans/<plan_id>/hops/<hop_id>/receipt`, refresh list on success.

- [ ] **Step 3: Headless verify**

Owner adds seller-role member → member list shows "seller" badge. Seller logs in → plan opens read-only (log-payment UI hidden or 403 handled gracefully — hide the button when `role_of` via members list says seller). Receiver user sees pending receipt in confirmations inbox, confirms, badge clears.

- [ ] **Step 4: Commit**

```bash
git add src/khata/static/asset-detail.html src/khata/static/<confirmations-page>
git commit -m "feat(chains): seller role UI + receipt confirmations inbox"
```

---

### Task 12: Docs + full verification

**Files:**
- Modify: `docs/specs/khata-AS-BUILT.md`

- [ ] **Step 1: Update AS-BUILT doc**

Add a "Payment chains" section: tables (`transfer_hops`, `hop_sources`, `transfer_hop_audit`, `ledger_entries.source_hop_id`), the outstanding rule, terminal fan-out behavior, fee-exclusion from paid totals, seller role, API routes, UI panels. Cross-link `docs/specs/2026-07-08-payment-chains-design.md`.

- [ ] **Step 2: Full suite + headless end-to-end**

```bash
python -m pytest -q
```
Expected: all green. Then run the full `/build-screen` verification protocol from `.claude/commands/build-screen.md` on the asset-detail screen (the repo rule: verify UI headless before "done").

- [ ] **Step 3: Commit**

```bash
git add docs/specs/khata-AS-BUILT.md
git commit -m "docs: as-built — payment chains (transfer routing)"
```
