from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, Retirement


def _s():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    return make_session_factory(e)()


def test_retirement_persists_and_cascade():
    s = _s()
    u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
    p = Plan(owner_user_id=u.id, type="retirement", name="401k", currency="INR"); s.add(p); s.flush()
    s.add(Retirement(plan_id=p.id, current_balance_minor=2500000, monthly_contribution_minor=1000000,
                     employer_match_bps=5000, annual_return_bps=800, inflation_bps=600,
                     current_age=30, retirement_age=60))
    s.commit()
    got = s.get(Plan, p.id).retirement
    assert got.retirement_age == 60 and got.employer_match_bps == 5000
    pid = p.id; s.delete(s.get(Plan, pid)); s.commit()
    assert s.get(Retirement, pid) is None
