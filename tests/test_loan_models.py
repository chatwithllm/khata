from datetime import date, datetime, timezone

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, Loan, LedgerEntry


def _session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_loan_and_kind_entry_persist():
    s = _session()
    u = User(email="a@b.com", display_name="A", password_hash="x")
    s.add(u)
    s.flush()
    plan = Plan(owner_user_id=u.id, type="loan", name="Gold loan", currency="INR")
    s.add(plan)
    s.flush()
    s.add(Loan(plan_id=plan.id, direction="taken", interest_type="yearly",
               rate_bps=850, start_date=date(2026, 1, 14)))
    s.add(LedgerEntry(plan_id=plan.id, logged_by_user_id=u.id, direction="in",
                      kind="disbursement", amount_minor=60000000, currency="INR",
                      occurred_at=datetime.now(timezone.utc)))
    s.commit()

    got = s.get(Plan, plan.id)
    assert got.loan.direction == "taken" and got.loan.rate_bps == 850
    e = got.ledger_entries[0]
    assert e.kind == "disbursement" and e.method is None and e.funding_source is None


def test_loan_secured_and_collateral_persist():
    from datetime import date
    from khata.db import Base, make_engine, make_session_factory
    from khata.models import User, Plan, Loan
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    s = make_session_factory(e)()
    u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
    hp = Plan(owner_user_id=u.id, type="holding", name="Gold", currency="INR"); s.add(hp); s.flush()
    lp = Plan(owner_user_id=u.id, type="loan", name="GL", currency="INR"); s.add(lp); s.flush()
    s.add(Loan(plan_id=lp.id, direction="taken", interest_type="none", rate_bps=0,
               start_date=date(2026, 1, 1), secured=True, collateral_plan_id=hp.id))
    s.commit()
    got = s.get(Plan, lp.id).loan
    assert got.secured is True and got.collateral_plan_id == hp.id
