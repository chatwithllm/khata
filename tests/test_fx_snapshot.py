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
