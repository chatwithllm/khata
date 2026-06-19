from datetime import datetime, timezone, date

import pytest
from sqlalchemy import select

from khata.db import Base, make_engine, make_session_factory
from khata.models import User, Plan, FxRate, FxRefreshState, BackupConfig, LedgerEntry, Attachment
from khata.services.assets import create_asset_plan, log_payment
from khata.services.loans import create_loan_plan, add_disbursement
from khata.services.sharing import add_member
from khata.services.backup import export_all, import_replace, BackupError
from khata.services import contacts as contacts_svc, attachments as att_svc


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


def test_inconsistent_backup_rows_raise_backup_error_not_integrity_error():
    # dangling FK (entry -> missing plan) must surface as BackupError (400-able),
    # never a raw IntegrityError (500). Rollback leaves the instance untouched.
    S = _fresh()
    with S() as s:
        _seed(s)
        data = _json_roundtrip(export_all(s))
        data["tables"]["ledger_entries"].append({
            "id": 9999, "plan_id": 4242, "user_id": 1, "entry_type": "payment",
            "amount_minor": 100, "currency": "INR",
            "entry_date": "2026-06-11", "created_at": "2026-06-11T00:00:00+00:00",
        })
        with pytest.raises(BackupError, match="ledger_entries"):
            import_replace(s, data)
        s.rollback()
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


_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f9f0000000049454e44ae426082"
)


def test_contact_and_attachment_backup_roundtrip():
    """Contact row, loan.contact_id FK, and contact attachment all survive export/import."""
    S1 = _fresh()
    with S1() as s1:
        owner = User(email="owner@x.com", display_name="Owner", password_hash="h")
        s1.add(owner); s1.flush()

        ct = contacts_svc.create_contact(s1, owner_id=owner.id, name="Ravi Kumar")
        s1.flush()

        ln = create_loan_plan(s1, owner_id=owner.id, name="Personal loan", currency="INR",
                              direction="given", interest_type="none", rate_bps=0,
                              start_date=date(2026, 1, 1))
        contacts_svc.assign_loan(s1, owner_id=owner.id, plan=ln, contact_id=ct.id)
        s1.flush()

        a = att_svc.add_attachment(s1, contact=ct, uploaded_by=owner.id,
                                   filename="id.png", raw=_PNG)
        s1.commit()

        orig_contact_id = ct.id
        orig_att_id = a.id
        orig_loan_plan_id = ln.id
        data = _json_roundtrip(export_all(s1))

    # Verify the backup dict carries the right data.
    assert any(r["id"] == orig_contact_id and r["name"] == "Ravi Kumar"
               for r in data["tables"]["contacts"])
    att_rows = [r for r in data["tables"]["attachments"] if r["id"] == orig_att_id]
    assert len(att_rows) == 1
    assert att_rows[0]["contact_id"] == orig_contact_id
    assert att_rows[0]["ledger_entry_id"] is None

    # Restore into a fresh instance and verify round-trip integrity.
    S2 = _fresh()
    with S2() as s2:
        stats = import_replace(s2, data); s2.commit()

        assert stats["contacts"] == 1
        assert stats["attachments"] == 1

        from khata.models import Contact as ContactModel, Loan as LoanModel
        restored_ct = s2.get(ContactModel, orig_contact_id)
        assert restored_ct is not None and restored_ct.name == "Ravi Kumar"

        restored_loan = s2.query(LoanModel).filter_by(plan_id=orig_loan_plan_id).one()
        assert restored_loan.contact_id == orig_contact_id

        restored_att = s2.get(Attachment, orig_att_id)
        assert restored_att is not None
        assert restored_att.contact_id == orig_contact_id
        assert restored_att.ledger_entry_id is None
        assert restored_att.mime == "image/png"
        assert restored_att.data == _PNG
