from datetime import datetime, timezone, date

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, LedgerEntry
from khata.services.assets import create_asset_plan, log_payment
from khata.services.loans import create_loan_plan, add_disbursement
from khata.services.sharing import add_member
from khata.services.backup import export_all, import_merge, BackupError


def _fresh():
    e = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    return make_session_factory(e)


def _dt():
    return datetime(2026, 5, 1, tzinfo=timezone.utc)


def _seed(s):
    owner = User(email="o@b.com", display_name="Owner", password_hash="hash-o")
    mate = User(email="m@b.com", display_name="Mate", password_hash="hash-m")
    s.add_all([owner, mate]); s.flush()
    a = create_asset_plan(s, owner_id=owner.id, name="Plot", currency="INR",
                          total_price_minor=100000000)
    log_payment(s, plan=a, user_id=owner.id, amount_minor=2500000, occurred_at=_dt(),
                method="upi", funding_source="savings")
    add_member(s, plan=a, email="m@b.com")
    ln = create_loan_plan(s, owner_id=owner.id, name="Gold loan", currency="INR",
                          direction="taken", interest_type="monthly", rate_bps=1200,
                          start_date=date(2026, 1, 1))
    add_disbursement(s, plan=ln, user_id=owner.id, amount_minor=50000000, occurred_at=_dt())
    s.commit()
    return owner, mate, a, ln


def test_export_then_import_into_fresh_instance():
    S1 = _fresh()
    with S1() as s1:
        _seed(s1)
        data = export_all(s1)

    assert data["version"] == 1
    assert len(data["tables"]["users"]) == 2
    assert len(data["tables"]["plans"]) == 2
    assert len(data["tables"]["ledger_entries"]) == 2  # one payment + one disbursement
    assert len(data["tables"]["plan_memberships"]) == 1

    # round-trips through JSON (no non-serializable values)
    import json
    data = json.loads(json.dumps(data))

    S2 = _fresh()
    with S2() as s2:
        stats = import_merge(s2, data)
        s2.commit()
        assert stats["users_created"] == 2 and stats["users_matched"] == 0
        assert stats["plans"] == 2
        assert stats["ledger_entries"] == 2
        assert stats["memberships"] == 1
        assert stats["loans"] == 1 and stats["asset_purchases"] == 1

        # data is intact + FKs remapped consistently
        plot = s2.query(Plan).filter_by(name="Plot").one()
        assert plot.asset.total_price_minor == 100000000
        assert s2.get(User, plot.owner_user_id).email == "o@b.com"
        entry = plot.ledger_entries[0]
        assert entry.amount_minor == 2500000
        assert entry.logged_by_user_id == plot.owner_user_id  # remapped to the new owner id
        mem = plot.memberships[0]
        assert s2.get(User, mem.user_id).email == "m@b.com"
        loan = s2.query(Plan).filter_by(name="Gold loan").one().loan
        assert loan.direction == "taken" and loan.rate_bps == 1200


def test_merge_matches_users_by_email_and_adds_plans():
    S = _fresh()
    with S() as s:
        _seed(s)
        data = export_all(s)
        import json; data = json.loads(json.dumps(data))
        # re-import onto the SAME instance: users matched (not duplicated), plans added
        stats = import_merge(s, data)
        s.commit()
        assert stats["users_matched"] == 2 and stats["users_created"] == 0
        assert stats["plans"] == 2
        assert s.query(User).count() == 2          # no duplicate users
        assert s.query(Plan).count() == 4          # original 2 + merged 2


def test_rejects_non_backup():
    S = _fresh()
    with S() as s:
        with pytest.raises(BackupError):
            import_merge(s, {"nope": 1})
        with pytest.raises(BackupError):
            import_merge(s, {"version": 999, "tables": {}})


def test_fx_rates_dedup_on_repeat_import():
    from khata.models import FxRate
    S = _fresh()
    with S() as s:
        s.add(User(email="o@b.com", display_name="O", password_hash="x"))
        s.add(FxRate(base_currency="INR", quote_currency="USD", rate_micro=83000000,
                     as_of=_dt()))
        s.commit()
        data = export_all(s)
        import json; data = json.loads(json.dumps(data))
        import_merge(s, data); s.commit()
        import_merge(s, data); s.commit()
        assert s.query(FxRate).count() == 1   # deduped by (base, quote, as_of)
