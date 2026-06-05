from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, Chit, LedgerEntry


def _s():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    return make_session_factory(e)()


def test_chit_persists_and_cascade():
    s = _s()
    u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
    p = Plan(owner_user_id=u.id, type="chit", name="20mo chit", currency="INR"); s.add(p); s.flush()
    s.add(Chit(plan_id=p.id, chit_value_minor=100000000, n_members=20, commission_bps=500,
               start_date=__import__("datetime").date(2026, 1, 1)))
    from datetime import datetime, timezone
    s.add(LedgerEntry(plan_id=p.id, logged_by_user_id=u.id, kind="chit_contribution", direction="out",
                      amount_minor=500000, currency="INR", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    s.commit()
    got = s.get(Plan, p.id)
    assert got.chit.n_members == 20 and got.chit.commission_bps == 500
    assert got.ledger_entries[0].kind == "chit_contribution"
    pid = p.id; s.delete(s.get(Plan, pid)); s.commit()
    assert s.get(Chit, pid) is None
