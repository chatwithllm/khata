from datetime import datetime, timezone

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan
from khata.services.assets import (
    create_asset_plan, log_payment, update_ledger_entry,
    respond_amount, list_amount_confirmations, asset_state, ValidationError,
)


def _dt():
    return datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        owner = User(email="o@b.com", display_name="Owner", password_hash="x")
        priya = User(email="p@b.com", display_name="Priya", password_hash="x")
        s.add_all([owner, priya]); s.flush()
        plan = create_asset_plan(s, owner_id=owner.id, name="Joint plot",
                                 currency="INR", total_price_minor=100000000)
        s.commit()
        yield s, owner, priya, plan


def _pay(s, plan, *, uid, acting, amt):
    return log_payment(s, plan=plan, user_id=uid, amount_minor=amt, occurred_at=_dt(),
                       method="upi", funding_source="savings", acting_user_id=acting)


def test_self_logged_is_agreed(ctx):
    s, owner, priya, plan = ctx
    e = _pay(s, plan, uid=owner.id, acting=owner.id, amt=800000)
    assert e.amount_status == "agreed"


def test_owner_attributes_to_contributor_is_pending(ctx):
    s, owner, priya, plan = ctx
    e = _pay(s, plan, uid=priya.id, acting=owner.id, amt=200000)
    assert e.amount_status == "pending"
    # surfaces to Priya, not to the owner
    assert any(r["entry_id"] == e.id for r in list_amount_confirmations(s, priya.id))
    assert list_amount_confirmations(s, owner.id) == []


def test_confirm_path(ctx):
    s, owner, priya, plan = ctx
    e = _pay(s, plan, uid=priya.id, acting=owner.id, amt=200000)
    respond_amount(s, plan=plan, entry_id=e.id, actor_uid=priya.id, action="confirm")
    assert e.amount_status == "agreed"
    assert list_amount_confirmations(s, priya.id) == []


def test_counter_then_accept(ctx):
    s, owner, priya, plan = ctx
    e = _pay(s, plan, uid=priya.id, acting=owner.id, amt=200000)
    # Priya proposes a higher figure; recorded amount unchanged until owner accepts.
    respond_amount(s, plan=plan, entry_id=e.id, actor_uid=priya.id, action="counter",
                   amount_minor=250000)
    assert e.amount_status == "countered"
    assert e.amount_minor == 200000 and e.counter_amount_minor == 250000
    # now it's the owner's turn
    assert any(r["entry_id"] == e.id for r in list_amount_confirmations(s, owner.id))
    assert list_amount_confirmations(s, priya.id) == []
    # owner accepts → recorded amount becomes the counter
    respond_amount(s, plan=plan, entry_id=e.id, actor_uid=owner.id, action="accept")
    assert e.amount_status == "agreed"
    assert e.amount_minor == 250000 and e.counter_amount_minor is None


def test_owner_recounter_bounces_back(ctx):
    s, owner, priya, plan = ctx
    e = _pay(s, plan, uid=priya.id, acting=owner.id, amt=200000)
    respond_amount(s, plan=plan, entry_id=e.id, actor_uid=priya.id, action="counter",
                   amount_minor=250000)
    # owner re-counters with a compromise → recorded amount set, back to Priya
    respond_amount(s, plan=plan, entry_id=e.id, actor_uid=owner.id, action="counter",
                   amount_minor=230000)
    assert e.amount_status == "pending"
    assert e.amount_minor == 230000 and e.counter_amount_minor is None
    respond_amount(s, plan=plan, entry_id=e.id, actor_uid=priya.id, action="confirm")
    assert e.amount_status == "agreed" and e.amount_minor == 230000


def test_wrong_turn_rejected(ctx):
    s, owner, priya, plan = ctx
    e = _pay(s, plan, uid=priya.id, acting=owner.id, amt=200000)
    # owner can't confirm on the contributor's behalf
    with pytest.raises(ValidationError):
        respond_amount(s, plan=plan, entry_id=e.id, actor_uid=owner.id, action="confirm")
    # owner can't accept when there's no counter yet
    with pytest.raises(ValidationError):
        respond_amount(s, plan=plan, entry_id=e.id, actor_uid=owner.id, action="accept")
    # a stranger amount isn't valid
    with pytest.raises(ValidationError):
        respond_amount(s, plan=plan, entry_id=e.id, actor_uid=priya.id, action="counter",
                       amount_minor=0)


def test_interim_amount_counts_and_flags(ctx):
    s, owner, priya, plan = ctx
    _pay(s, plan, uid=owner.id, acting=owner.id, amt=800000)
    _pay(s, plan, uid=priya.id, acting=owner.id, amt=200000)  # pending
    st = asset_state(s, plan)
    # recorded total counts the unconfirmed entry
    assert st["paid_to_date_minor"] == 1000000
    pri = next(c for c in st["contributors"] if c["display_name"] == "Priya")
    assert pri["unconfirmed"] is True
    own = next(c for c in st["contributors"] if c["display_name"] == "Owner")
    assert own["unconfirmed"] is False


def test_edit_amount_reopens_confirmation(ctx):
    s, owner, priya, plan = ctx
    e = _pay(s, plan, uid=priya.id, acting=owner.id, amt=200000)
    respond_amount(s, plan=plan, entry_id=e.id, actor_uid=priya.id, action="confirm")
    assert e.amount_status == "agreed"
    # owner edits the amount → must be re-confirmed
    update_ledger_entry(s, plan=plan, entry_id=e.id, amount_minor=300000, acting_user_id=owner.id)
    assert e.amount_status == "pending"
