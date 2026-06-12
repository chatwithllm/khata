# Restore = Replace + Plan Delete Everywhere — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POST /api/restore` wipe-and-load (no more duplicates) and add the plan-level Delete button to asset/chit/holding/retirement detail pages.

**Architecture:** New `import_replace()` in `services/backup.py` deletes every backed-up table child-first, then inserts the backup's rows verbatim (original ids preserved — tables are empty, no FK remap needed). `import_merge` is deleted. The API endpoint keeps its pre-restore snapshot, then re-points the operator's session by email (or logs them out). Frontend: copy the loan-detail `planacts` ghost-button pattern to the four other detail pages; the backend `DELETE /api/plans/<id>` is already type-generic.

**Tech Stack:** Flask + SQLAlchemy 2.0, pytest, vanilla-JS static pages (K4: textContent only, never innerHTML on user/API data).

**Spec:** `docs/specs/2026-06-11-restore-replace-and-plan-delete-design.md`

**Branch:** `feat/restore-replace-plan-delete` (already created). Run tests as:
`/Users/assistant/dev/active/khata/.venv/bin/python -m pytest` from `/private/tmp/khata-landing`.

**Standing rules:** commit trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`; stage files explicitly (never `git add -A`); update `docs/specs/khata-AS-BUILT.md` in the same commit as the change it documents.

---

### Task 1: `import_replace` service (replaces `import_merge`)

**Files:**
- Modify: `src/khata/services/backup.py` (docstring lines 1–10, replace `import_merge` lines 86–187)
- Test: `tests/test_backup.py` (rewrite)
- Modify: `tests/test_attachments.py:13,190-192` (import + stats key)

- [ ] **Step 1: Rewrite `tests/test_backup.py`**

Replace the whole file with:

```python
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
```

- [ ] **Step 2: Run new tests, verify they fail on the import**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_backup.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'import_replace'`

- [ ] **Step 3: Implement `import_replace`, delete `import_merge`**

In `src/khata/services/backup.py`:

Replace the module docstring (lines 1–10) with:

```python
"""Whole-instance backup / restore.

Backup = a versioned JSON snapshot of every table (export_all). Restore = a REPLACE
(import_replace): every backed-up table is wiped, then the backup's rows are inserted
verbatim — original ids preserved (tables are empty, so nothing needs remapping, and
stale session cookies / bearer tokens keep pointing at the same person when the backup
came from this instance). Restoring the same file twice is idempotent.

Operational state stays untouched: backup_config and fx_refresh_state are not part of
backup files and are never wiped.

The raw-SQLite CLI path (scripts/backup.sh / restore.sh) is the offline alternative.
"""
```

Add `delete` to the sqlalchemy import (line 14):

```python
from sqlalchemy import select, inspect, delete
```

Delete the whole `import_merge` function (lines 86–187) and add:

```python
def import_replace(session: Session, data: dict) -> dict:
    """Wipe ALL existing data, then load the backup verbatim (ids preserved).
    Returns per-table insert counts keyed by table name. The caller owns the
    transaction — any failure raises and a rollback leaves the instance untouched."""
    if not isinstance(data, dict) or "tables" not in data:
        raise BackupError("not a Khata backup file")
    if data.get("version") != BACKUP_VERSION:
        raise BackupError(f"unsupported backup version: {data.get('version')!r}")
    t = data["tables"]
    if not t.get("users"):
        raise BackupError("backup contains no users — restoring it would brick every login")

    # Wipe children before parents (reverse of the FK-ordered EXPORT_MODELS).
    # Explicit order — never trust relationship cascade config for this.
    for model in reversed(EXPORT_MODELS):
        session.execute(delete(model))
    session.flush()

    # Insert verbatim, parents first. _parse keeps the "id" column, so every row
    # lands with the id it had when the backup was taken.
    stats: dict[str, int] = {}
    for model in EXPORT_MODELS:
        n = 0
        for raw in t.get(model.__tablename__, []):
            session.add(model(**_parse(model, raw)))
            n += 1
        session.flush()
        stats[model.__tablename__] = n
    return stats
```

(The `PLAN_SUBTABLES` constant at lines 28–30 was only used by `import_merge` — delete it too.)

- [ ] **Step 4: Fix `tests/test_attachments.py`**

Line 13: `from khata.services.backup import export_all, import_replace`
Line 190: `stats = import_replace(s, data)`
(`stats["attachments"] == 1` on line 192 still holds — same key in the new stats dict.)

- [ ] **Step 5: Run backup + attachment tests**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_backup.py tests/test_attachments.py -q`
Expected: all PASS. (`tests/test_backup_api.py` will FAIL on `backup.import_merge` — that's Task 2; do not touch it here.)

- [ ] **Step 6: Commit**

```bash
git add src/khata/services/backup.py tests/test_backup.py tests/test_attachments.py
git commit -m "feat(backup): import_replace — restore wipes and loads, ids preserved

Replaces import_merge. Merge semantics duplicated every plan on re-import
(no natural key); replace is idempotent and matches the user's mental model
of restore. Validates the backup contains users before wiping (an empty
backup would brick every login).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(Note: `src/khata/api/backup.py` still calls `import_merge` after this commit — the API
is broken until Task 2, which is the very next commit on this branch. Acceptable
intermediate state; tests for the API are updated there.)

---

### Task 2: `POST /api/restore` uses replace + session re-point

**Files:**
- Modify: `src/khata/api/backup.py` (imports line 5, restore handler lines 73–118)
- Test: `tests/test_backup_api.py` (lines 48–87 rewritten + new tests)

- [ ] **Step 1: Update `tests/test_backup_api.py`**

Keep the fixture, `_setup`, `test_backup_requires_auth`, `test_backup_operator_only`
unchanged. Replace `test_backup_download_and_restore_roundtrip`,
`test_restore_via_multipart_file`, `test_restore_rejects_garbage` and add the new tests:

```python
def test_backup_download_and_restore_replaces(client):
    _setup(client)
    r = client.get("/api/backup")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    data = json.loads(r.data)
    assert data["version"] == 1
    assert len(data["tables"]["plans"]) == 1
    assert len(data["tables"]["users"]) == 1

    # restore the same backup (raw JSON body) -> REPLACES: still exactly one plan
    resp = client.post("/api/restore", json=data)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["logged_out"] is False
    assert body["stats"]["users"] == 1
    assert body["stats"]["plans"] == 1
    plans = client.get("/api/plans").get_json()["plans"]
    assert sum(1 for p in plans if p["name"] == "Plot") == 1


def test_restore_removes_data_not_in_backup(client):
    _setup(client)
    data = json.loads(client.get("/api/backup").data)
    # create a second plan AFTER taking the backup
    client.post("/api/plans", json={"name": "Later", "currency": "INR", "total_price": "1,000"})
    assert len(client.get("/api/plans").get_json()["plans"]) == 2
    resp = client.post("/api/restore", json=data)
    assert resp.status_code == 200
    plans = client.get("/api/plans").get_json()["plans"]
    assert [p["name"] for p in plans] == ["Plot"]


def test_restore_session_survives_when_operator_in_backup(client):
    _setup(client)
    data = json.loads(client.get("/api/backup").data)
    assert client.post("/api/restore", json=data).status_code == 200
    # same cookie still authenticates (session re-pointed by email)
    assert client.get("/api/backup").status_code == 200


def test_restore_logs_out_when_operator_absent_from_backup(client):
    _setup(client)
    data = json.loads(client.get("/api/backup").data)
    data["tables"]["users"][0]["email"] = "someone-else@b.com"
    resp = client.post("/api/restore", json=data)
    assert resp.status_code == 200
    assert resp.get_json()["logged_out"] is True
    # session cleared — next request is unauthenticated
    assert client.get("/api/backup").status_code == 401


def test_restore_rejects_backup_with_no_users(client):
    _setup(client)
    r = client.post("/api/restore", json={"version": 1, "tables": {"users": []}})
    assert r.status_code == 400
    # instance untouched
    assert len(client.get("/api/plans").get_json()["plans"]) == 1


def test_restore_via_multipart_file(client):
    _setup(client)
    data = json.loads(client.get("/api/backup").data)
    buf = io.BytesIO(json.dumps(data).encode())
    resp = client.post("/api/restore", data={"file": (buf, "backup.json")},
                       content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["stats"]["plans"] == 1


def test_restore_rejects_garbage(client):
    _setup(client)
    assert client.post("/api/restore", json={"not": "a backup"}).status_code == 400
    buf = io.BytesIO(b"this is not json")
    r = client.post("/api/restore", data={"file": (buf, "x.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
```

- [ ] **Step 2: Run, verify failures**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_backup_api.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'import_merge'` (and the new assertions).

- [ ] **Step 3: Update the endpoint**

In `src/khata/api/backup.py` line 5, add `session`:

```python
from flask import Blueprint, Response, current_app, g, jsonify, request, session
```

Replace the handler body from the `try:` at line 108 through the `return` at line 118 with:

```python
    try:
        stats = backup.import_replace(g.db, data)
        g.db.commit()
    except backup.BackupError as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    except Exception:
        g.db.rollback()
        raise

    # The restore may have removed or re-id'd the operator's account. Re-point the
    # session at the restored row (matched by email) — or log them out if it's gone.
    logged_out = False
    restored = g.db.scalar(select(User).where(User.email == user.email))
    if restored is not None:
        session["user_id"] = restored.id
    else:
        session.clear()
        logged_out = True
    # Note: do NOT leak the absolute server path — just whether the safety net was written.
    return jsonify(ok=True, stats=stats, pre_restore_saved=pre_restore_saved,
                   logged_out=logged_out), 200
```

Also update the handler docstring (lines 75–78) to:

```python
    """REPLACE this instance's data with an uploaded backup (wipe + load). Operator-only —
    a restore recreates users with arbitrary password hashes, so an untrusted caller could
    inject a backdoor account. Auto-saves a pre-restore snapshot first. Accepts a
    multipart file field 'file' or a raw JSON body."""
```

- [ ] **Step 4: Run API tests**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_backup_api.py -q`
Expected: all PASS.

- [ ] **Step 5: Full suite**

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q`
Expected: all PASS (326+ tests).

- [ ] **Step 6: Commit**

```bash
git add src/khata/api/backup.py tests/test_backup_api.py
git commit -m "feat(api): restore replaces instance data; session re-pointed by email

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Settings UI — replace copy + logout redirect (+ AS-BUILT)

**Files:**
- Modify: `src/khata/static/settings.html:154,342,349-354`
- Modify: `docs/specs/khata-AS-BUILT.md` (restore section + change log)

- [ ] **Step 1: Update the hint (line 154)**

```html
              <div class="hint" style="margin-top:18px">Restore <strong>replaces</strong> everything with the backup's contents — all current users, plans, and entries are deleted first. A pre-restore snapshot is auto-saved on the server.</div>
```

- [ ] **Step 2: Update the confirm (line 342)**

```js
  if(!confirm('Restore from "'+f.name+'"? This REPLACES all current data with the backup\'s contents. A pre-restore snapshot is saved on the server first.')) return;
```

- [ ] **Step 3: Update the success handler (lines 349–354)**

```js
    if(r.ok){
      if(j.logged_out){ window.location.href='/'; return; }
      const s=j.stats||{};
      show($('rmsg'), true, 'Restored: '+(s.plans||0)+' plans, '+(s.ledger_entries||0)+' entries, '+(s.users||0)+' user(s). Previous data replaced.');
      fileEl.value='';
    } else {
```

(`stats` keys are now table names — `users`, `plans`, `ledger_entries` — per Task 1.)

- [ ] **Step 4: Update AS-BUILT**

In `docs/specs/khata-AS-BUILT.md`: rewrite the backup/restore section's restore
description from merge-by-email to wipe-and-load (mention: ids preserved verbatim,
operator session re-pointed by email / `logged_out` flag, empty-users backups rejected,
pre-restore snapshot unchanged, `backup_config` + `fx_refresh_state` untouched). Add a
change-log entry dated 2026-06-11: "Restore is now replace (wipe + load), was merge —
re-importing a backup no longer duplicates plans."

- [ ] **Step 5: Verify headless**

Run: `grep -n "REPLACES all current data" src/khata/static/settings.html && grep -n "logged_out" src/khata/static/settings.html`
Expected: both match.
Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest tests/test_web.py -q`
Expected: PASS (static pages still served).

- [ ] **Step 6: Commit**

```bash
git add src/khata/static/settings.html docs/specs/khata-AS-BUILT.md
git commit -m "feat(web): settings restore copy + logout redirect for replace semantics

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Delete button on asset / chit / holding / retirement detail pages (+ AS-BUILT)

Backend untouched — `DELETE /api/plans/<id>` (`api/plans.py:311`) is owner-only and
type-generic. This task is four parallel copies of the loan-detail pattern
(`loan-detail.html:90-94,372-381,1235-1243`). Button rendered for any viewer; the API
enforces owner-only (member click → error alert). K4: textContent only.

**Files:**
- Modify: `src/khata/static/asset-detail.html` (CSS block + `renderHeader` line 293–300 + new `deletePlan`)
- Modify: `src/khata/static/chit-detail.html` (CSS block + `renderHeader` line 323–331 + new `deletePlan`)
- Modify: `src/khata/static/holding-detail.html` (CSS block + `renderHeader` line 186–195 + new `deletePlan`)
- Modify: `src/khata/static/retirement-detail.html` (CSS block + `renderHeader` line 203–211 + new `deletePlan`)
- Modify: `docs/specs/khata-AS-BUILT.md` (plan-delete coverage + change log)

- [ ] **Step 1: Add shared CSS to each of the four pages**

Add inside each page's `<style>` block (near its `.ph`/header styles):

```css
/* plan-level actions (delete) — ghost button, right of the meta (loan-detail pattern) */
.planacts{display:flex;gap:8px;align-items:center;flex:none}
.planacts .plandel{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600;padding:5px 11px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink-soft);cursor:pointer;user-select:none;transition:border-color .2s,color .2s,background .2s}
.planacts svg{width:13px;height:13px;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.planacts .plandel:hover{border-color:var(--neg);color:var(--neg);background:color-mix(in srgb,var(--neg) 6%,transparent)}
@media(pointer:coarse){ .planacts .plandel{min-height:44px;padding:10px 14px} }
.ph-right{display:flex;align-items:center;gap:14px;flex-wrap:wrap;justify-content:flex-end}
```

- [ ] **Step 2: Add `deletePlan()` + header wiring to `asset-detail.html`**

Add above `async function boot()` (line 712):

```js
// ── delete the whole asset plan ──
async function deletePlan(){
  if(!confirm('Delete this asset and all its entries? This cannot be undone.')) return;
  const r = await fetch('/api/plans/'+pid, { method:'DELETE' });
  if(r.ok){ window.location.href='/app'; return; }
  const e = await r.json().catch(()=>({}));
  alert(e.detail || e.error || 'Could not delete this asset.');
}
```

In `renderHeader` (line 299), replace:

```js
  ph.append(t, el('div','meta', insts.length+' installments'));
```

with:

```js
  const SVGNS='http://www.w3.org/2000/svg';
  const icon=(d)=>{ const s=document.createElementNS(SVGNS,'svg'); s.setAttribute('viewBox','0 0 24 24'); const p=document.createElementNS(SVGNS,'path'); p.setAttribute('d',d); s.append(p); return s; };
  const actBtn=(cls, label, dPath, fn)=>{ const b=el('span',cls); b.tabIndex=0; b.setAttribute('role','button'); b.append(icon(dPath), document.createTextNode(label));
    b.addEventListener('click', fn); b.addEventListener('keydown', (ev)=>{ if(ev.key==='Enter'||ev.key===' '){ ev.preventDefault(); fn(); } }); return b; };
  const acts=el('div','planacts');
  acts.append(actBtn('plandel','Delete','M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6', deletePlan));
  const right=el('div','ph-right');
  right.append(el('div','meta', insts.length+' installments'), acts);
  ph.append(t, right);
```

- [ ] **Step 3: Same for `chit-detail.html`**

`deletePlan` above `async function boot()` (line 808) — confirm copy:
`'Delete this chit and all its entries? This cannot be undone.'`, error fallback
`'Could not delete this chit.'`, otherwise identical to Step 2's function.

In `renderHeader` (line 330), replace:

```js
  ph.append(t, el('div','meta', 'auction · monthly'));
```

with the same SVGNS/icon/actBtn/acts block as Step 2, ending in:

```js
  const right=el('div','ph-right');
  right.append(el('div','meta', 'auction · monthly'), acts);
  ph.append(t, right);
```

- [ ] **Step 4: Same for `holding-detail.html`**

`deletePlan` above `async function boot()` (line 310) — confirm copy:
`'Delete this holding and all its entries? This cannot be undone.'`, fallback
`'Could not delete this holding.'`.

In `renderHeader` (line 194), replace:

```js
  ph.append(t, el('div','meta', metaBits.join(' · ')));
```

with the same block, ending in:

```js
  const right=el('div','ph-right');
  right.append(el('div','meta', metaBits.join(' · ')), acts);
  ph.append(t, right);
```

- [ ] **Step 5: Same for `retirement-detail.html`**

`deletePlan` above `async function boot()` (line 456) — confirm copy:
`'Delete this retirement plan and all its entries? This cannot be undone.'`, fallback
`'Could not delete this plan.'`.

In `renderHeader` (line 210), replace:

```js
  ph.append(t, el('div','meta', meta));
```

with the same block, ending in:

```js
  const right=el('div','ph-right');
  right.append(el('div','meta', meta), acts);
  ph.append(t, right);
```

- [ ] **Step 6: Update AS-BUILT**

`docs/specs/khata-AS-BUILT.md`: update the plan-delete coverage (was loan-detail only →
all five detail pages; button visible to any viewer, API enforces owner-only). Change-log
entry dated 2026-06-11.

- [ ] **Step 7: Verify headless**

```bash
for f in asset-detail chit-detail holding-detail retirement-detail; do
  grep -c "deletePlan\|plandel" src/khata/static/$f.html
done
```

Expected: ≥3 per file (CSS class, actBtn wiring, function). Then:

Run: `/Users/assistant/dev/active/khata/.venv/bin/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/khata/static/asset-detail.html src/khata/static/chit-detail.html src/khata/static/holding-detail.html src/khata/static/retirement-detail.html docs/specs/khata-AS-BUILT.md
git commit -m "feat(web): plan Delete button on asset/chit/holding/retirement detail pages

Loan-detail already had it; DELETE /api/plans/<id> was always type-generic.
Closes the gap that left restore-duplicated assets undeletable.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Live UI verification on :5057

**Files:** none (verification only)

- [ ] **Step 1: Restart the local test instance**

Run: `bash /Users/assistant/dev/active/khata/run-app.sh` (background; serves :5057 from
the `/tmp/khata-landing` worktree with `khata_app.db` — NEVER wipe that DB).

- [ ] **Step 2: Headless smoke**

```bash
curl -s http://127.0.0.1:5057/healthz
curl -s http://127.0.0.1:5057/asset/1 | grep -c plandel   # asset detail page source
```

Expected: healthz ok; static page source contains the delete wiring. Exercise the full
delete + restore flows in the browser against test data only (no prod writes).

- [ ] **Step 3: Done — hand off**

Use superpowers:finishing-a-development-branch (tests → options → PR with the standard
footer `🤖 Generated with [Claude Code](https://claude.com/claude-code)`).
