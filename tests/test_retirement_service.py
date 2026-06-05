import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.retirement import (create_retirement_plan, update_retirement,
                                       retirement_state, RetirementError, ValidationError)


@pytest.fixture
def ctx():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    S = make_session_factory(e)
    with S() as s:
        u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
        yield s, u


def test_zero_return_is_balance_plus_contributions(ctx):
    s, u = ctx
    # balance 10,000 + 5,000/mo for 12yr (n=144) at 0% return, 0% inflation, no match
    p = create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
        current_balance_minor=1000000, monthly_contribution_minor=500000, employer_match_bps=0,
        annual_return_bps=0, inflation_bps=0, current_age=48, retirement_age=60)
    s.commit()
    st = retirement_state(s, p.retirement)
    assert st["months_to_retirement"] == 144
    assert st["effective_monthly_minor"] == 500000
    assert st["total_contributions_minor"] == 72000000          # 5000 × 144
    assert st["projected_corpus_minor"] == 73000000             # 10000 + 72000
    assert st["projected_corpus_real_minor"] == 73000000        # 0% inflation


def test_already_at_retirement_age_is_current_balance(ctx):
    s, u = ctx
    p = create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
        current_balance_minor=2500000, monthly_contribution_minor=1000000, employer_match_bps=0,
        annual_return_bps=800, inflation_bps=600, current_age=60, retirement_age=60)
    s.commit()
    st = retirement_state(s, p.retirement)
    assert st["months_to_retirement"] == 0
    assert st["projected_corpus_minor"] == 2500000             # n=0 → just the balance


def test_compound_projection_8pct(ctx):
    s, u = ctx
    # 10,000/mo, 8% return, 6% inflation, 30→60 (n=360), no match, no starting balance
    p = create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
        current_balance_minor=0, monthly_contribution_minor=1000000, employer_match_bps=0,
        annual_return_bps=800, inflation_bps=600, current_age=30, retirement_age=60)
    s.commit()
    st = retirement_state(s, p.retirement)
    assert st["projected_corpus_minor"] == 1490359449          # nominal
    assert st["projected_corpus_real_minor"] == 247462156      # today's money (< nominal)


def test_employer_match_increases_effective(ctx):
    s, u = ctx
    p = create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
        current_balance_minor=0, monthly_contribution_minor=1000000, employer_match_bps=5000,
        annual_return_bps=0, inflation_bps=0, current_age=59, retirement_age=60)
    s.commit()
    st = retirement_state(s, p.retirement)
    assert st["effective_monthly_minor"] == 1500000            # 10000 × 1.5
    assert st["projected_corpus_minor"] == 18000000            # 15000 × 12


def test_validation_and_update(ctx):
    s, u = ctx
    with pytest.raises(ValidationError):
        create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
            current_age=60, retirement_age=50)                 # retirement < current
    p = create_retirement_plan(s, owner_id=u.id, name="R", currency="INR",
        current_balance_minor=0, monthly_contribution_minor=1000000, annual_return_bps=0,
        inflation_bps=0, current_age=50, retirement_age=60)
    update_retirement(s, plan=p, monthly_contribution_minor=2000000)
    s.commit()
    assert retirement_state(s, p.retirement)["projected_corpus_minor"] == 2000000 * 120  # 20000 × 120mo
