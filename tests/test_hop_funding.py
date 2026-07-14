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
    assert abs(hop["counter_value_minor"] - 100000) <= 5


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


def test_backfill_hop_fx_from_notes(ctx):
    s, u, plan, loan = ctx   # plan currency is INR
    from khata.models import TransferHop
    # foreign-currency hop, rate only in the note prefix, no structured fx
    h1 = transfers.create_hop(s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id,
        to_name="Mid", amount_minor=9447000, occurred_at=_dt(1), method="transfer",
        note="$1,000 USD @94.47 — sent to mid")
    # already has a rate -> must be left untouched
    h2 = transfers.create_hop(s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id,
        to_name="Mid2", amount_minor=1000, occurred_at=_dt(2), method="transfer",
        note="$10 USD @95.00", fx_rate_micro=12345)
    # no parseable FX prefix -> left null
    h3 = transfers.create_hop(s, plan=plan, logged_by_user_id=u.id, from_user_id=u.id,
        to_name="Mid3", amount_minor=5000, occurred_at=_dt(3), method="transfer",
        note="cash handoff")
    s.commit()

    n = transfers.backfill_hop_fx_from_notes(s)
    s.commit()
    assert n == 1
    assert s.get(TransferHop, h1.id).fx_rate_micro == round(1e6 / 94.47)
    assert s.get(TransferHop, h1.id).fx_counter_currency == "USD"
    # round-trips back to ~$1000 (100000 cents)
    from khata.services import fx
    cv = fx.convert(9447000, rate_micro=s.get(TransferHop, h1.id).fx_rate_micro)
    assert abs(cv - 100000) <= 5
    assert s.get(TransferHop, h2.id).fx_rate_micro == 12345   # untouched
    assert s.get(TransferHop, h3.id).fx_rate_micro is None    # no prefix
    # idempotent: a second run changes nothing
    assert transfers.backfill_hop_fx_from_notes(s) == 0
