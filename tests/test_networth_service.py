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
    # base INR; a USD holding; rate 1 USD = ₹83.42
    h = create_holding_plan(s, owner_id=u.id, name="US Equity", currency="USD",
                            asset_class="equity", unit="share")
    add_buy(s, plan=h, user_id=u.id, quantity_micro=10_000_000, amount_minor=80000,
            occurred_at=_dt(1))
    set_quote(s, plan=h, price_minor=10, as_of=_dt(2))   # $0.10/share × 10 shares = $1.00 value
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
