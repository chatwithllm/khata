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
    m = sharing.add_member(s, plan=plan, email="s@x.com", role="seller")
    m.status = "active"; s.flush()
    assert sharing.role_of(s, plan=plan, user_id=owner.id) == "owner"
    assert sharing.role_of(s, plan=plan, user_id=seller.id) == "seller"
    assert sharing.role_of(s, plan=plan, user_id=99999) is None


def test_invalid_role_rejected(ctx):
    s, owner, seller, plan = ctx
    with pytest.raises(ValueError):
        sharing.add_member(s, plan=plan, email="s@x.com", role="superadmin")
