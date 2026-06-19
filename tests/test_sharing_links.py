from datetime import date, datetime, timezone, timedelta

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.loans import create_loan_plan, add_disbursement, log_loan_entry
from khata.services import sharing_links as sl


@pytest.fixture
def ctx():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="a@b.com", display_name="Arjun", password_hash="x")
        s.add(u); s.flush()
        plan = create_loan_plan(s, owner_id=u.id, name="Lent", currency="INR",
                                direction="given", interest_type="monthly", rate_bps=300,
                                start_date=date(2023, 12, 12))
        add_disbursement(s, plan=plan, user_id=u.id, amount_minor=220000000,
                         occurred_at=datetime(2023, 12, 12, tzinfo=timezone.utc))
        s.flush()
        yield s, u, plan


def test_create_share_defaults_and_token(ctx):
    s, u, plan = ctx
    sh = sl.create_share(s, plan=plan, user_id=u.id, scope="summary", ttl_days=30)
    s.flush()
    assert sh.scope == "summary"
    assert len(sh.token) >= 32 and sh.revoked_at is None
    assert sh.expires_at > datetime.now(timezone.utc) + timedelta(days=29)


def test_create_share_validates(ctx):
    s, u, plan = ctx
    with pytest.raises(sl.ShareError):
        sl.create_share(s, plan=plan, user_id=u.id, scope="bogus", ttl_days=30)
    with pytest.raises(sl.ShareError):
        sl.create_share(s, plan=plan, user_id=u.id, scope="full", ttl_days=5)


def test_resolve_public_valid_expired_revoked_unknown(ctx):
    s, u, plan = ctx
    sh = sl.create_share(s, plan=plan, user_id=u.id, scope="full", ttl_days=7)
    s.flush()
    p, scope = sl.resolve_public(s, sh.token)
    assert p.id == plan.id and scope == "full"
    with pytest.raises(sl.ShareNotFound):
        sl.resolve_public(s, "nope-not-a-token")
    sl.revoke_share(s, plan=plan, share_id=sh.id); s.flush()
    with pytest.raises(sl.ShareGone):
        sl.resolve_public(s, sh.token)
    sh2 = sl.create_share(s, plan=plan, user_id=u.id, scope="full", ttl_days=7)
    sh2.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1); s.flush()
    with pytest.raises(sl.ShareGone):
        sl.resolve_public(s, sh2.token)


def test_public_state_redacts_and_scopes(ctx):
    s, u, plan = ctx
    # Add a payment with a sensitive note to verify it gets scrubbed
    log_loan_entry(s, plan=plan, user_id=u.id, kind="principal_repayment",
                   amount_minor=10000,
                   occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                   note="SECRET_MEMO_XYZ")
    s.flush()
    full = sl.public_state(s, plan, "full")
    summ = sl.public_state(s, plan, "summary")
    import json
    for env in (full, summ):
        assert env["plan_type"] == "loan" and env["name"] == "Lent"
        assert env["scope"] in ("full", "summary")
    blob = json.dumps(full)
    assert "@b.com" not in blob and "proof_ref" not in blob
    assert "members" not in full and "members" not in full.get("state", {})
    assert "schedule" in full["state"]
    assert "schedule" not in summ["state"] and "ledger" not in summ["state"]
    import json as _json
    fblob = _json.dumps(full)
    assert "logged_by_user_id" not in fblob
    assert "funding_plan_id" not in fblob
    # note field must be scrubbed from the public payload
    assert "SECRET_MEMO_XYZ" not in _json.dumps(full)


def test_list_and_revoke(ctx):
    s, u, plan = ctx
    a = sl.create_share(s, plan=plan, user_id=u.id, scope="summary", ttl_days=7)
    b = sl.create_share(s, plan=plan, user_id=u.id, scope="full", ttl_days=30)
    s.flush()
    rows = sl.list_shares(s, plan)
    assert len(rows) == 2 and {r["scope"] for r in rows} == {"summary", "full"}
    sl.revoke_share(s, plan=plan, share_id=a.id); s.flush()
    rows2 = {r["id"]: r for r in sl.list_shares(s, plan)}
    assert rows2[a.id]["status"] == "revoked" and rows2[b.id]["status"] == "active"


def test_revoke_wrong_plan_raises(ctx):
    s, u, plan = ctx
    from khata.services.loans import create_loan_plan
    from datetime import date as _date
    other = create_loan_plan(s, owner_id=u.id, name="Other", currency="INR",
                             direction="given", interest_type="monthly", rate_bps=100,
                             start_date=_date(2024,1,1))
    s.flush()
    sh = sl.create_share(s, plan=plan, user_id=u.id, scope="full", ttl_days=7); s.flush()
    with pytest.raises(sl.ShareNotFound):
        sl.revoke_share(s, plan=other, share_id=sh.id)


def test_scrub_strips_all_sensitive_keys():
    from khata.services.sharing_links import _scrub
    raw = {
        "ok_field": 1,
        "amount_minor": 500,
        "contributors": [{"user_id": 7, "display_name": "Priya", "avatar": "data:img", "paid_minor": 100}],
        "deployed": [{"plan_id": 9, "plan_name": "Secret Plan", "plan_type": "asset", "amount_minor": 10}],
        "collateral": {"plan_id": 3, "name": "Gold Hoard", "value_minor": 999},
        "ledger": [{"occurred_at": "x", "kind": "interest_payment", "amount_minor": 5,
                    "paid_by_name": "Priya", "paid_by_avatar": "data:img",
                    "amount_status": "pending", "counter_amount_minor": 4, "note": "memo",
                    "logged_by_user_id": 7}],
        "email": "leak@x.com",
    }
    out = _scrub(raw)
    import json
    blob = json.dumps(out)
    for bad in ["Priya", "data:img", "Secret Plan", "Gold Hoard", "leak@x.com", "memo",
                "user_id", "display_name", "avatar", "plan_name", "collateral_name_marker",
                "paid_by_name", "paid_by_avatar", "amount_status", "counter_amount_minor",
                "logged_by_user_id"]:
        assert bad not in blob, f"leaked: {bad}"
    # legit data survives
    assert out["ok_field"] == 1 and out["amount_minor"] == 500
    assert out["ledger"][0]["amount_minor"] == 5 and out["ledger"][0]["kind"] == "interest_payment"
    # contributors block removed entirely
    assert "contributors" not in out


def test_expiry_survives_session_reload(tmp_path):
    from datetime import date, datetime, timezone, timedelta
    from khata.db import Base, make_engine, make_session_factory
    from khata.models import User
    from khata.services.loans import create_loan_plan, add_disbursement
    from khata.services import sharing_links as sl
    db = tmp_path / "s.db"
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        u = User(email="a@b.com", display_name="A", password_hash="x"); s.add(u); s.flush()
        plan = create_loan_plan(s, owner_id=u.id, name="L", currency="INR",
                                direction="given", interest_type="monthly", rate_bps=300,
                                start_date=date(2023,12,12))
        add_disbursement(s, plan=plan, user_id=u.id, amount_minor=220000000,
                         occurred_at=datetime(2023,12,12,tzinfo=timezone.utc))
        sh = sl.create_share(s, plan=plan, user_id=u.id, scope="full", ttl_days=7)
        sh.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)  # already expired
        tok = sh.token
        s.commit()
    # fresh session -> expires_at reloads as NAIVE; must still cleanly raise ShareGone, not crash
    with Session() as s2:
        with __import__("pytest").raises(sl.ShareGone):
            sl.resolve_public(s2, tok)
        # list_shares must not crash on naive reload either
        from khata.models import Plan
        p2 = s2.get(Plan, 1)
        rows = sl.list_shares(s2, p2)
        assert rows and rows[0]["status"] == "expired" and rows[0]["token"] is None
