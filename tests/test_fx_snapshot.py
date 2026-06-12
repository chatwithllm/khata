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


from datetime import date

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


# ---------------------------------------------------------------------------
# Task 4: hook tests — every entry-creation path must stamp fx snapshot
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 6: PATCH — edit the snapshot rate
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 7: serialization — fx fields + derived counter value in ledger arrays
# ---------------------------------------------------------------------------

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
