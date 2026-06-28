# Asset Details Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add seller/buyer (text + optional contact link), custom info + links (JSON), and document attachments (+ video-as-link) to assets.

**Architecture:** `asset_purchases` gains seller/buyer columns + `extra_fields`/`links` JSON-Text columns; `attachments` gains a third parent `asset_plan_id`. New `update_asset_meta` service, `asset_state` extension, owner-only meta API + plan-member asset-doc access, asset-detail UI. Builds on Contacts + the generalized attachments. One migration.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy, Alembic (SQLite batch), pytest; vanilla-JS in `asset-detail.html`.

---

## File Structure

- **Modify** `src/khata/models/plan.py` (AssetPurchase columns) + `src/khata/models/attachment.py` (asset_plan_id) (T1).
- **Create** `alembic/versions/as1assetmeta01_asset_details.py` (T1).
- **Modify** `src/khata/services/assets.py` (`update_asset_meta`, `asset_state` ext) + `src/khata/services/attachments.py` (3-parent `add_attachment`, `list_for_asset`) (T2).
- **Modify** `src/khata/api/plans.py` (`PATCH /asset/meta`, asset attachment endpoints) + `src/khata/api/attachments.py` (download/delete asset branch) (T3).
- **Modify** `src/khata/services/sharing_links.py` (scrub keys) (T4).
- **Modify** `src/khata/static/asset-detail.html` (T5).
- **Modify** `docs/specs/khata-AS-BUILT.md` (T6).
- **Tests:** `tests/test_asset_meta.py` (T2), `tests/test_asset_meta_api.py` (T3), extend `tests/test_public_share_api.py` (T4), extend `tests/test_backup.py` (T2).

Verified facts:
- Current alembic head `ct1contact01`. `AssetPurchase(plan_id PK, total_price_minor)`. `Attachment` has `ledger_entry_id?`, `contact_id?` (both nullable, ON DELETE CASCADE). `EXPORT_MODELS` already contains `AssetPurchase` and `Attachment` (new columns ride along).
- `attachments.add_attachment(session,*,uploaded_by,filename,raw,entry=None,contact=None)` with `(entry is None)==(contact is None)` guard; `_sniff`, `MAX_SIZE`, `meta`, `get`, `list_for_entry`, `list_for_contact`, `delete`. `INLINE_MIMES`.
- `api/attachments.py` `download_attachment`/`delete_attachment` branch on `ledger_entry_id`/`contact_id` (entry→`sharing.accessible`; contact→owner-only). `Plan`, `Contact`, `LedgerEntry`, `sharing` imported there.
- `assets.asset_state(session, plan, viewer_id=None)`. `contacts.get_contact(session,*,owner_id,contact_id)` → Contact|None. `_owned_plan(user, plan_id)` in plans.py. SQLite needs `op.batch_alter_table` to add FK columns.

Test cmd: `cd /tmp/khata-asset-details && PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest <args>`.

---

### Task 1: Model + migration

**Files:** modify `src/khata/models/plan.py`, `src/khata/models/attachment.py`; create `alembic/versions/as1assetmeta01_asset_details.py`.

- [ ] **Step 1: AssetPurchase columns** — in `src/khata/models/plan.py`, add to `class AssetPurchase` (after `total_price_minor`), and add `Text`/`ForeignKey` to its imports if missing (`from sqlalchemy import BigInteger, Date, ForeignKey, Integer, Text` etc.):
```python
    seller_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    seller_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    buyer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    buyer_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    extra_fields: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON [{label,value}]
    links: Mapped[str | None] = mapped_column(Text, nullable=True)         # JSON [{label,url,video?}]
```

- [ ] **Step 2: Attachment third parent** — in `src/khata/models/attachment.py`, add after `contact_id`:
```python
    asset_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=True, index=True)
```

- [ ] **Step 3: Migration** — `alembic/versions/as1assetmeta01_asset_details.py`:
```python
"""asset seller/buyer + extra_fields/links + attachments.asset_plan_id

Revision ID: as1assetmeta01
Revises: ct1contact01
Create Date: 2026-06-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "as1assetmeta01"
down_revision: Union[str, None] = "ct1contact01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("asset_purchases") as b:
        b.add_column(sa.Column("seller_name", sa.Text(), nullable=True))
        b.add_column(sa.Column("seller_contact_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("buyer_name", sa.Text(), nullable=True))
        b.add_column(sa.Column("buyer_contact_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("extra_fields", sa.Text(), nullable=True))
        b.add_column(sa.Column("links", sa.Text(), nullable=True))
        b.create_foreign_key("fk_asset_seller_contact", "contacts", ["seller_contact_id"], ["id"],
                             ondelete="SET NULL")
        b.create_foreign_key("fk_asset_buyer_contact", "contacts", ["buyer_contact_id"], ["id"],
                             ondelete="SET NULL")
    with op.batch_alter_table("attachments") as b:
        b.add_column(sa.Column("asset_plan_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_attachments_asset_plan", "plans", ["asset_plan_id"], ["id"],
                             ondelete="CASCADE")
        b.create_index("ix_attachments_asset_plan_id", ["asset_plan_id"])


def downgrade() -> None:
    with op.batch_alter_table("attachments") as b:
        b.drop_index("ix_attachments_asset_plan_id")
        b.drop_constraint("fk_attachments_asset_plan", type_="foreignkey")
        b.drop_column("asset_plan_id")
    with op.batch_alter_table("asset_purchases") as b:
        b.drop_constraint("fk_asset_buyer_contact", type_="foreignkey")
        b.drop_constraint("fk_asset_seller_contact", type_="foreignkey")
        for c in ("links", "extra_fields", "buyer_contact_id", "buyer_name",
                  "seller_contact_id", "seller_name"):
            b.drop_column(c)
```

- [ ] **Step 4: Verify up+down + single head + suite:**
```
cd /tmp/khata-asset-details
KHATA_DATABASE_URL="sqlite:////tmp/as.db" PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/alembic upgrade head
PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/alembic heads     # single: as1assetmeta01
KHATA_DATABASE_URL="sqlite:////tmp/as.db" PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/alembic downgrade -1
rm -f /tmp/as.db
PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest -q
```
(If batch downgrade can't drop a constraint by name on SQLite, use `op.batch_alter_table(..., recreate="always")`.)

- [ ] **Step 5: Commit**
```bash
git add src/khata/models/plan.py src/khata/models/attachment.py alembic/versions/as1assetmeta01_asset_details.py
git commit -m "feat(asset): asset seller/buyer + extra_fields/links + attachments.asset_plan_id (migration)"
```

---

### Task 2: Service — update_asset_meta, asset_state, 3-parent attachments

**Files:** modify `src/khata/services/assets.py`, `src/khata/services/attachments.py`; test `tests/test_asset_meta.py`, extend `tests/test_backup.py`.

- [ ] **Step 1: Failing tests** — `tests/test_asset_meta.py`:
```python
import json
import pytest
from datetime import datetime, timezone
from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services import assets, contacts as c, attachments as att

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000154a24f9f0000000049454e44ae426082")


@pytest.fixture
def ctx():
    e = make_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    S = make_session_factory(e)
    with S() as s:
        u = User(email="a@b.com", display_name="A", password_hash="x")
        o = User(email="z@z.com", display_name="O", password_hash="x")
        s.add_all([u, o]); s.flush()
        yield s, u, o


def _asset(s, u, name="1 Acre", price=17500000):
    return assets.create_asset_plan(s, owner_id=u.id, name=name, currency="INR",
                                    total_price_minor=price)


def test_meta_seller_buyer_text_and_contact(ctx):
    s, u, o = ctx
    plan = _asset(s, u); s.flush()
    ct = c.create_contact(s, owner_id=u.id, name="Ramesh"); s.flush()
    assets.update_asset_meta(s, plan=plan, owner_id=u.id, seller_name="Ramesh",
                             seller_contact_id=ct.id, buyer_name="Me")
    s.flush()
    st = assets.asset_state(s, plan)
    assert st["seller"]["name"] == "Ramesh" and st["seller"]["contact_id"] == ct.id
    assert st["seller"]["contact_name"] == "Ramesh"
    assert st["buyer"]["name"] == "Me" and st["buyer"]["contact_id"] is None


def test_meta_rejects_foreign_contact(ctx):
    s, u, o = ctx
    plan = _asset(s, u); foreign = c.create_contact(s, owner_id=o.id, name="X"); s.flush()
    with pytest.raises(assets.PlanError):
        assets.update_asset_meta(s, plan=plan, owner_id=u.id, seller_contact_id=foreign.id)


def test_extra_fields_and_links_roundtrip(ctx):
    s, u, o = ctx
    plan = _asset(s, u); s.flush()
    assets.update_asset_meta(s, plan=plan, owner_id=u.id,
        extra_fields=[{"label":"Survey No","value":"123"}, {"label":"  ","value":"drop me"}],
        links=[{"label":"Walkthrough","url":"https://youtu.be/x","video":True}])
    s.flush()
    st = assets.asset_state(s, plan)
    assert st["extra_fields"] == [{"label":"Survey No","value":"123"}]   # blank-label dropped
    assert st["links"][0]["url"] == "https://youtu.be/x" and st["links"][0]["video"] is True


def test_links_reject_bad_scheme(ctx):
    s, u, o = ctx
    plan = _asset(s, u); s.flush()
    with pytest.raises(assets.PlanError):
        assets.update_asset_meta(s, plan=plan, owner_id=u.id,
                                 links=[{"label":"x","url":"javascript:alert(1)"}])


def test_asset_attachment_three_parents(ctx):
    s, u, o = ctx
    plan = _asset(s, u); s.flush()
    a = att.add_attachment(s, asset_plan=plan, uploaded_by=u.id, filename="deed.png", raw=PNG)
    s.flush()
    assert a.asset_plan_id == plan.id and a.ledger_entry_id is None and a.contact_id is None
    assert [x.id for x in att.list_for_asset(s, plan.id)] == [a.id]
    # exactly-one-of-three: zero parents and two parents both rejected
    with pytest.raises(att.AttachmentError):
        att.add_attachment(s, uploaded_by=u.id, filename="x.png", raw=PNG)
    ct = c.create_contact(s, owner_id=u.id, name="K"); s.flush()
    with pytest.raises(att.AttachmentError):
        att.add_attachment(s, asset_plan=plan, contact=ct, uploaded_by=u.id, filename="x.png", raw=PNG)


def test_delete_asset_cascades_attachments(ctx):
    s, u, o = ctx
    plan = _asset(s, u); s.flush()
    a = att.add_attachment(s, asset_plan=plan, uploaded_by=u.id, filename="d.png", raw=PNG)
    s.commit()
    from khata.models import Attachment, Plan
    s.delete(s.get(Plan, plan.id)); s.commit()
    assert s.get(Attachment, a.id) is None
```
(Check `assets.create_asset_plan`'s real signature in `src/khata/services/assets.py` and adapt `_asset` — it likely takes `owner_id, name, currency, total_price_minor` plus maybe installment args. Use the minimal valid call.)

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Generalize `add_attachment`** in `src/khata/services/attachments.py` to three parents:
```python
def add_attachment(session, *, uploaded_by, filename, raw, entry=None, contact=None, asset_plan=None):
    parents = [entry, contact, asset_plan]
    if sum(p is not None for p in parents) != 1:
        raise AttachmentError("attachment needs exactly one parent (entry, contact, or asset)")
    if not raw:
        raise AttachmentError("empty file")
    if len(raw) > MAX_SIZE:
        raise AttachmentError(f"file too large (max {MAX_SIZE // (1024 * 1024)} MB)")
    mime = _sniff(raw)
    if mime is None:
        raise AttachmentError("unsupported file type — images, PDF, or Office documents only")
    name = (filename or "file").strip()[:255] or "file"
    a = Attachment(
        ledger_entry_id=entry.id if entry is not None else None,
        contact_id=contact.id if contact is not None else None,
        asset_plan_id=asset_plan.id if asset_plan is not None else None,
        uploaded_by_user_id=uploaded_by, filename=name, mime=mime, size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(), data=raw)
    session.add(a); session.flush()
    return a


def list_for_asset(session, plan_id):
    return list(session.scalars(
        select(Attachment).where(Attachment.asset_plan_id == plan_id)
        .order_by(Attachment.created_at, Attachment.id)))
```

- [ ] **Step 4: `update_asset_meta` + `asset_state` ext** in `src/khata/services/assets.py`. Add `import json` and `from . import contacts as _contacts` (or lazy-import to avoid cycles). The validators:
```python
_FIELD_CAP = 40
_LABEL_MAX = 80
_VALUE_MAX = 500
_URL_MAX = 1000


def _clean_fields(rows):
    out = []
    for r in (rows or []):
        label = str(r.get("label", "")).strip()[:_LABEL_MAX]
        value = str(r.get("value", "")).strip()[:_VALUE_MAX]
        if not label:
            continue
        out.append({"label": label, "value": value})
        if len(out) >= _FIELD_CAP:
            break
    return out


def _clean_links(rows):
    out = []
    for r in (rows or []):
        url = str(r.get("url", "")).strip()[:_URL_MAX]
        low = url.lower()
        if not (low.startswith("http://") or low.startswith("https://")):
            raise ValidationError("links must be http(s) URLs")
        label = str(r.get("label", "")).strip()[:_LABEL_MAX] or url
        out.append({"label": label, "url": url, "video": bool(r.get("video"))})
        if len(out) >= _FIELD_CAP:
            break
    return out


def update_asset_meta(session, *, plan, owner_id, seller_name=None, seller_contact_id=None,
                      buyer_name=None, buyer_contact_id=None, extra_fields=None, links=None):
    ap = plan.asset
    if ap is None:
        raise ValidationError("not an asset plan")
    from . import contacts as _contacts
    def _ck(cid):
        if cid is None:
            return None
        ct = _contacts.get_contact(session, owner_id=owner_id, contact_id=cid)
        if ct is None:
            raise ValidationError("no such contact")
        return ct.id
    # Only overwrite a field when it's explicitly provided (None = leave as-is for names;
    # but the API always sends the full set, so treat None as 'set to null' for names).
    ap.seller_name = (seller_name or None)
    ap.seller_contact_id = _ck(seller_contact_id)
    ap.buyer_name = (buyer_name or None)
    ap.buyer_contact_id = _ck(buyer_contact_id)
    if extra_fields is not None:
        ap.extra_fields = json.dumps(_clean_fields(extra_fields))
    if links is not None:
        ap.links = json.dumps(_clean_links(links))
    session.flush()
    return ap
```
(`ValidationError` is the asset service's existing error — confirm its name in assets.py; the spec says `PlanError`. Use whatever the file defines as its validation error (likely `ValidationError(PlanError)`); the tests catch `assets.PlanError`, so make sure the raised class is a `PlanError` subclass — it is.)

Extend `asset_state` to include (parse JSON, resolve contact names):
```python
    ap = plan.asset
    def _party(name, cid):
        cn = None
        if cid is not None:
            from ..models import Contact
            ct = session.get(Contact, cid)
            cn = ct.name if ct else None
        return {"name": name, "contact_id": cid, "contact_name": cn}
    state["seller"] = _party(ap.seller_name, ap.seller_contact_id) if ap else None
    state["buyer"] = _party(ap.buyer_name, ap.buyer_contact_id) if ap else None
    state["extra_fields"] = json.loads(ap.extra_fields) if (ap and ap.extra_fields) else []
    state["links"] = json.loads(ap.links) if (ap and ap.links) else []
    from .attachments import list_for_asset, meta as _ameta
    state["attachments"] = [_ameta(a) for a in list_for_asset(session, plan.id)]
```
(Insert before `asset_state`'s `return`, using its actual local dict name — read the function; it builds a dict then returns it.)

- [ ] **Step 5: Backup round-trip test** — extend `tests/test_backup.py`: an asset with seller/buyer/extra_fields/links + an asset attachment exports + re-imports intact (asset_purchases + attachments already in EXPORT_MODELS; just assert the new columns + the asset_plan_id attachment survive).

- [ ] **Step 6: Run all (asset_meta + backup) → pass; full suite green. Commit:**
```bash
git add src/khata/services/assets.py src/khata/services/attachments.py tests/test_asset_meta.py tests/test_backup.py
git commit -m "feat(asset): update_asset_meta + asset_state parties/fields/links + asset attachments"
```

---

### Task 3: API — asset meta + asset documents

**Files:** modify `src/khata/api/plans.py`, `src/khata/api/attachments.py`; test `tests/test_asset_meta_api.py`.

- [ ] **Step 1: Failing tests** — `tests/test_asset_meta_api.py` (copy the `client` fixture/auth/seed idiom from `tests/test_secured_loans_api.py`/`test_contacts_api.py`; create an asset plan via `POST /api/plans {type:"asset", name, currency, total_price}`). Contract:
```python
def test_patch_meta_owner_only(client):
    pid = _make_asset(client)
    r = client.patch(f"/api/plans/{pid}/asset/meta", json={"seller_name":"Ramesh","buyer_name":"Me",
        "extra_fields":[{"label":"Survey No","value":"123"}],
        "links":[{"label":"Map","url":"https://maps.example/x"}]})
    assert r.status_code == 200
    st = r.get_json()["state"]
    assert st["seller"]["name"] == "Ramesh" and st["extra_fields"][0]["label"] == "Survey No"
    # non-owner
    _login_as_other_user(client)
    assert client.patch(f"/api/plans/{pid}/asset/meta", json={"seller_name":"hack"}).status_code == 403


def test_patch_meta_bad_url_400(client):
    pid = _make_asset(client)
    assert client.patch(f"/api/plans/{pid}/asset/meta",
        json={"links":[{"label":"x","url":"javascript:alert(1)"}]}).status_code == 400


def test_asset_doc_upload_list_download(client):
    pid = _make_asset(client)
    import io
    PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000002000154a24f9f0000000049454e44ae426082")
    r = client.post(f"/api/plans/{pid}/asset/attachments",
                    data={"file": (io.BytesIO(PNG), "deed.png")}, content_type="multipart/form-data")
    assert r.status_code == 201
    aid = r.get_json()["attachment"]["id"]
    assert len(client.get(f"/api/plans/{pid}/asset/attachments").get_json()["attachments"]) == 1
    assert client.get(f"/api/attachments/{aid}").status_code == 200   # owner can download
```
(For shared-member download you may add a test if the fixture supports a 2nd member; otherwise assert a stranger gets 403 — a non-member second user.)

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** in `src/khata/api/plans.py` (after the asset routes). `update_asset_meta` raises `PlanError` on bad input (caught → 400). Add to imports if needed (`assets` already imported):
```python
@bp.patch("/<int:plan_id>/asset/meta")
def asset_meta(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "asset":
        return jsonify(error="not_an_asset"), 400
    d = request.get_json(silent=True) or {}
    try:
        assets.update_asset_meta(g.db, plan=plan, owner_id=user.id,
            seller_name=d.get("seller_name"), seller_contact_id=d.get("seller_contact_id"),
            buyer_name=d.get("buyer_name"), buyer_contact_id=d.get("buyer_contact_id"),
            extra_fields=d.get("extra_fields"), links=d.get("links"))
        g.db.commit()
    except (PlanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(state=assets.asset_state(g.db, plan, viewer_id=user.id)), 200


@bp.get("/<int:plan_id>/asset/attachments")
def list_asset_docs(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _accessible_plan(user, plan_id)   # members can view
    if err:
        return err
    if plan.type != "asset":
        return jsonify(error="not_an_asset"), 400
    from ..services import attachments as _att
    return jsonify(attachments=[_att.meta(a) for a in _att.list_for_asset(g.db, plan.id)]), 200


@bp.post("/<int:plan_id>/asset/attachments")
def upload_asset_doc(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner uploads
    if err:
        return err
    if plan.type != "asset":
        return jsonify(error="not_an_asset"), 400
    f = request.files.get("file")
    if f is None:
        return jsonify(error="invalid", detail="no file"), 400
    from ..services import attachments as _att
    try:
        a = _att.add_attachment(g.db, asset_plan=plan, uploaded_by=user.id,
                                filename=f.filename, raw=f.read())
        g.db.commit()
    except _att.AttachmentError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(attachment=_att.meta(a)), 201
```
(Confirm `_accessible_plan` exists in plans.py — it does, used for member-accessible reads. `PlanError` imported as `from ..services.assets import PlanError`.)

- [ ] **Step 4: Download/delete asset branch** — in `src/khata/api/attachments.py`, extend BOTH `download_attachment` and `delete_attachment` to handle `asset_plan_id`:
  - In `download_attachment`, add a branch BEFORE the final `else`:
    ```python
    elif att.asset_plan_id is not None:
        plan = g.db.get(Plan, att.asset_plan_id)
        if plan is None or not sharing.accessible(g.db, plan=plan, user_id=user.id):
            return jsonify(error="forbidden"), 403
    ```
  - In `delete_attachment`, add:
    ```python
    elif att.asset_plan_id is not None:
        plan = g.db.get(Plan, att.asset_plan_id)
        if plan is None:
            return jsonify(error="not_found"), 404
        if not (user.id == plan.owner_user_id or user.id == att.uploaded_by_user_id):
            return jsonify(error="forbidden"), 403
    ```

- [ ] **Step 5: Run (asset_meta_api) → pass; full suite green. Commit:**
```bash
git add src/khata/api/plans.py src/khata/api/attachments.py tests/test_asset_meta_api.py
git commit -m "feat(asset): PATCH /asset/meta + asset document endpoints + access branches"
```

---

### Task 4: Privacy — asset PII out of public share

**Files:** modify `src/khata/services/sharing_links.py`; extend `tests/test_public_share_api.py`.

- [ ] **Step 1: Failing test** — extend `tests/test_public_share_api.py`: create an asset, set seller "PRIVATE_SELLER" + a link + an extra field, create a `full` public share of the asset, GET `/api/public/<token>`, assert "PRIVATE_SELLER", "seller", "extra_fields", "links", and the link URL are absent from the JSON.

- [ ] **Step 2: Run.** If it already passes (asset_state's new keys not reached because the public asset path differs), still add the scrub keys in Step 3. If it FAILS (asset_state exposes them publicly), Step 3 fixes it.

- [ ] **Step 3: Scrub keys** — in `src/khata/services/sharing_links.py`, add to `_SCRUB_KEYS`: `"seller"`, `"buyer"`, `"seller_name"`, `"buyer_name"`, `"extra_fields"`, `"links"`, `"url"`, `"contact_name"` (keep existing). These strip the asset parties/fields/links recursively from any public envelope.

- [ ] **Step 4: Run the test + full suite → green. Commit:**
```bash
git add src/khata/services/sharing_links.py tests/test_public_share_api.py
git commit -m "fix(asset): keep seller/buyer/fields/links out of public share links"
```

---

### Task 5: UI — asset detail edit panel + documents + links

**Files:** modify `src/khata/static/asset-detail.html`.

- [ ] **Step 1: Read** `asset-detail.html` — find `boot()`/the load fn, `pid`, `el`, money helpers, the header (where Edit/Delete sit), and how the contact-detail page did its docs (mirror that). Also `/api/contacts` for the seller/buyer typeahead.

- [ ] **Step 2: Parties + edit** — show seller & buyer read-only in the header area when set (name → `/contacts/<id>` link when `contact_id`). Add an **"Edit details"** button opening a panel/modal: seller & buyer text inputs + a "link contact" control (a `<select>`/typeahead from `/api/contacts` + a clear button); repeatable **custom-field rows** (label + value inputs, ＋add / ✕remove); repeatable **link rows** (label + URL inputs + an "is video" checkbox, ＋add / ✕remove). Save → `PATCH /api/plans/<pid>/asset/meta` with `{seller_name, seller_contact_id, buyer_name, buyer_contact_id, extra_fields:[{label,value}], links:[{label,url,video}]}`; refresh on success.

- [ ] **Step 3: Custom info + links display** — a read-only **Details** card listing `extra_fields` (label · value). A **Links** card: each link a row — label as `<a href=url target="_blank" rel="noopener noreferrer">`, video links prefixed with a ▶ marker. All values via `.textContent` (XSS). Do NOT embed/iframe.

- [ ] **Step 4: Documents card** — upload (`<input type=file>` → multipart POST `/api/plans/<pid>/asset/attachments`), list (`GET …/asset/attachments` → filename + download `/api/attachments/<id>` + delete `DELETE /api/attachments/<id>`), mirroring the contact-detail docs UI.

- [ ] **Step 5: Verify (you)** — extract inline `<script>`, `node --check` (clean); `pytest -q` green; self-review (XSS via textContent, links rel=noopener + http only shown, top-level fns, no app.css/ledger.css edits).

- [ ] **Step 6: Commit**
```bash
git add src/khata/static/asset-detail.html
git commit -m "feat(asset): asset-detail edit panel + custom info + links + documents"
```

- [ ] **Step 7: Headless verify (controller runs).** Per `/build-screen`: seed an asset, PATCH meta (seller text + contact link + a field + a link) via API, upload a doc; headless-render `/asset/<id>`: 0 JS throws; seller/buyer show; Details + Links cards render (link is an `<a target=_blank rel=noopener>`); Documents card lists the uploaded file; the Edit panel opens and saves. Report findings.

---

### Task 6: AS-BUILT doc

**Files:** modify `docs/specs/khata-AS-BUILT.md`.

- [ ] **Step 1: Update** data-model (asset_purchases new columns + `attachments` third parent `asset_plan_id`), §9, and a change-log entry at top:
```
- 2026-06-19 — Asset details. Assets gain seller & buyer (free text + optional Contact link),
  custom info rows + external links (JSON columns on asset_purchases), and document attachments
  (a third attachment parent `asset_plan_id`; video = a link, not an upload — keeps the one-file
  backup). Owner edits via `PATCH /api/plans/<id>/asset/meta`; asset docs upload owner-only,
  download plan-member. http(s)-only URLs; seller/buyer/fields/links scrubbed from public share
  links. Migration `as1assetmeta01`.
```

- [ ] **Step 2: Full suite green + commit**
```bash
PYTHONPATH=src /Users/assistant/dev/active/khata/.venv/bin/pytest -q
git add docs/specs/khata-AS-BUILT.md
git commit -m "docs(asset): record asset details (parties/fields/links/docs) in AS-BUILT"
```

---

## Self-Review

**Spec coverage:** seller/buyer text+contact (T1 cols, T2 service, T5 UI) ✅; extra_fields/links JSON (T1/T2/T5) ✅; documents via 3rd attachment parent (T1/T2/T3) ✅; video-as-link (T2 links + T5 UI) ✅; owner-edit / member-download access (T3) ✅; URL http-only validation (T2) ✅; asset_state surfaces all (T2) ✅; public-share scrub (T4) ✅; backup round-trip (T2) ✅; UI (T5) ✅; docs (T6) ✅; migration single head up/down (T1) ✅.

**Placeholder scan:** Flagged fill-ins: the asset service's exact validation-error class name (`PlanError`/`ValidationError`) and `create_asset_plan` signature (read assets.py — adapt), and the API test `client` fixture (copy conftest idiom). Behavioral assertions are concrete; all production code shown.

**Type consistency:** `update_asset_meta(plan, owner_id, seller_name, seller_contact_id, buyer_name, buyer_contact_id, extra_fields, links)` used identically in T2 service, T3 API, and asserted in tests. `asset_state` adds `seller`/`buyer` (`{name,contact_id,contact_name}`), `extra_fields` `[{label,value}]`, `links` `[{label,url,video}]`, `attachments` — consumed by T3 API + T5 UI + T4 scrub. `add_attachment(... entry,contact,asset_plan)` exactly-one-of-three used in T2/T3. Migration `as1assetmeta01` / down_revision `ct1contact01` consistent.
