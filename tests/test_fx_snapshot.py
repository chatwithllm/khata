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
