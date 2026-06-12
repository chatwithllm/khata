from datetime import datetime, timezone, date

import pytest
from sqlalchemy import select

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, FxRate, FxRefreshState, BackupConfig, LedgerEntry
from khata.services.assets import create_asset_plan, log_payment
from khata.services.loans import create_loan_plan, add_disbursement
from khata.services.sharing import add_member
from khata.services.backup import export_all, import_replace, BackupError


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


def _json_roundtrip(data):
    import json
    return json.loads(json.dumps(data))


def test_export_then_replace_into_fresh_instance():
    S1 = _fresh()
    with S1() as s1:
        _seed(s1)
        data = export_all(s1)

    assert data["version"] == 1
    assert len(data["tables"]["users"]) == 2
    assert len(data["tables"]["plans"]) == 2
    assert len(data["tables"]["ledger_entries"]) == 2  # one payment + one disbursement
    assert len(data["tables"]["plan_memberships"]) == 1

    data = _json_roundtrip(data)

    S2 = _fresh()
    with S2() as s2:
        stats = import_replace(s2, data)
        s2.commit()
        assert stats["users"] == 2
        assert stats["plans"] == 2
        assert stats["ledger_entries"] == 2
        assert stats["plan_memberships"] == 1
        assert stats["loans"] == 1 and stats["asset_purchases"] == 1

        plot = s2.query(Plan).filter_by(name="Plot").one()
        assert plot.asset.total_price_minor == 100000000
        assert s2.get(User, plot.owner_user_id).email == "o@b.com"
        entry = plot.ledger_entries[0]
        assert entry.amount_minor == 2500000
        assert entry.logged_by_user_id == plot.owner_user_id
        mem = plot.memberships[0]
        assert s2.get(User, mem.user_id).email == "m@b.com"
        loan = s2.query(Plan).filter_by(name="Gold loan").one().loan
        assert loan.direction == "taken" and loan.rate_bps == 1200


def test_replace_preserves_original_ids():
    S1 = _fresh()
    with S1() as s1:
        owner, _, a, ln = _seed(s1)
        data = _json_roundtrip(export_all(s1))
        old_owner_id, old_plan_id = owner.id, a.id

    S2 = _fresh()
    with S2() as s2:
        # pre-pollute the target so autoincrement counters differ
        s2.add(User(email="x@y.com", display_name="X", password_hash="x"))
        s2.commit()
        import_replace(s2, data)
        s2.commit()
        # rows carry the BACKUP's ids, not freshly assigned ones
        assert s2.scalar(select(User.id).where(User.email == "o@b.com")) == old_owner_id
        assert s2.query(Plan).filter_by(name="Plot").one().id == old_plan_id


def test_replace_wipes_existing_data_no_duplicates():
    S = _fresh()
    with S() as s:
        _seed(s)
        data = _json_roundtrip(export_all(s))
        # restore onto the SAME non-empty instance: counts stay identical
        import_replace(s, data); s.commit()
        assert s.query(User).count() == 2
        assert s.query(Plan).count() == 2
        # the duplicate bug, dead: a second restore of the same file changes nothing
        import_replace(s, data); s.commit()
        assert s.query(User).count() == 2
        assert s.query(Plan).count() == 2
        assert s.query(LedgerEntry).count() == 2


def test_replace_removes_plans_absent_from_backup():
    S = _fresh()
    with S() as s:
        owner, _, _, _ = _seed(s)
        data = _json_roundtrip(export_all(s))
        # a plan created AFTER the backup must vanish on restore
        create_asset_plan(s, owner_id=owner.id, name="Later plot", currency="INR",
                          total_price_minor=5000)
        s.commit()
        assert s.query(Plan).count() == 3
        import_replace(s, data); s.commit()
        assert s.query(Plan).count() == 2
        assert s.query(Plan).filter_by(name="Later plot").count() == 0


def test_rejects_non_backup_and_bad_version():
    S = _fresh()
    with S() as s:
        with pytest.raises(BackupError):
            import_replace(s, {"nope": 1})
        with pytest.raises(BackupError):
            import_replace(s, {"version": 999, "tables": {}})


def test_rejects_backup_with_no_users():
    S = _fresh()
    with S() as s:
        _seed(s)
        with pytest.raises(BackupError):
            import_replace(s, {"version": 1, "tables": {"users": [], "plans": []}})
        s.rollback()
        # instance untouched — validation failed BEFORE the wipe
        assert s.query(User).count() == 2
        assert s.query(Plan).count() == 2


def test_fx_rates_replaced_not_duplicated():
    S = _fresh()
    with S() as s:
        s.add(User(email="o@b.com", display_name="O", password_hash="x"))
        s.add(FxRate(base_currency="INR", quote_currency="USD", rate_micro=83000000,
                     as_of=_dt()))
        s.commit()
        data = _json_roundtrip(export_all(s))
        import_replace(s, data); s.commit()
        import_replace(s, data); s.commit()
        assert s.query(FxRate).count() == 1


def test_operational_state_untouched_by_restore():
    # backup_config + fx_refresh_state are not in backup files — restore must not wipe them
    S = _fresh()
    with S() as s:
        _seed(s)
        s.add(BackupConfig(enabled=True))
        s.add(FxRefreshState())
        s.commit()
        data = _json_roundtrip(export_all(s))
        import_replace(s, data); s.commit()
        assert s.query(BackupConfig).count() == 1
        assert s.query(FxRefreshState).count() == 1
