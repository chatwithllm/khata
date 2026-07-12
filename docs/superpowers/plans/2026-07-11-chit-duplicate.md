# Chit Duplicate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Duplicate" action to a chit fund that clones its terms into a new, empty chit under a user-chosen name.

**Architecture:** A thin service wrapper (`duplicate_chit_plan`) reads the source chit's terms and calls the existing `create_chit_plan`. A new owner-only endpoint `POST /api/plans/<id>/chit/duplicate` exposes it. The chit-detail page gets a Duplicate header button that prompts for a name (pre-filled with an incremented trailing number) and redirects to the new chit.

**Tech Stack:** Python / Flask (blueprint `bp` in `src/khata/api/plans.py`), SQLAlchemy models, pytest, vanilla-JS static page (`src/khata/static/chit-detail.html`).

## Global Constraints

- Terms copied: `chit_value_minor`, `n_members`, `commission_bps`, `currency`, `start_date` — nothing else.
- New chit has an **empty ledger** and **no shares** (private to owner).
- Duplicate is **owner-only** (`_owned_plan`), chit-type-only (`plan.type == "chit"`).
- No name-uniqueness enforcement (plan names are not unique in this app).
- Endpoint returns `_detail(new_plan)` → `{"plan": {...,"id"}, "state": {...}}`; client reads the new id at `d.plan.id`.
- Every code change updates `docs/specs/khata-AS-BUILT.md` in the same commit (project rule).
- Run `/build-screen` protocol before marking the screen done (project CLAUDE.md).

---

### Task 1: Service — `duplicate_chit_plan`

**Files:**
- Modify: `src/khata/services/chits.py` (add function after `create_chit_plan`, ~line 51)
- Test: `tests/test_chit_service.py`

**Interfaces:**
- Consumes: existing `create_chit_plan(session, *, owner_id, name, currency, chit_value_minor, n_members, commission_bps, start_date) -> Plan`
- Produces: `duplicate_chit_plan(session, *, source_plan, owner_id, name) -> Plan` — new chit Plan, terms copied from `source_plan.chit`, empty ledger.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chit_service.py` (it already imports from `khata.services.chits` and has the `ctx` fixture, `_dt`, and `_chit` helpers):

```python
def test_duplicate_copies_terms_empty_ledger(ctx):
    s, u = ctx
    src = _chit(s, u)  # value 10,00,000 minor=100000000, 20 members, 500 bps, 2026-01-01
    log_chit_entry(s, plan=src, user_id=u.id, kind="chit_contribution", amount_minor=5000000, occurred_at=_dt(1))
    s.commit()
    dup = duplicate_chit_plan(s, source_plan=src, owner_id=u.id, name="C -2")
    s.commit()
    assert dup.id != src.id
    assert dup.name == "C -2"
    assert dup.type == "chit"
    assert dup.currency == src.currency
    assert dup.chit.chit_value_minor == src.chit.chit_value_minor
    assert dup.chit.n_members == src.chit.n_members
    assert dup.chit.commission_bps == src.chit.commission_bps
    assert dup.chit.start_date == src.chit.start_date
    # empty ledger + no shares
    assert list(dup.ledger_entries) == []
    st = chit_state(s, dup.chit)
    assert st["months_recorded"] == 0
    assert st["total_contributed_minor"] == 0
```

Update the import line at the top of the file to include the new name:

```python
from khata.services.chits import (create_chit_plan, duplicate_chit_plan, log_chit_entry,
                                  chit_state, auction_dividend, ChitError, ValidationError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_chit_service.py::test_duplicate_copies_terms_empty_ledger -v`
Expected: FAIL — `ImportError: cannot import name 'duplicate_chit_plan'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/khata/services/chits.py` immediately after `create_chit_plan` (after line 50):

```python
def duplicate_chit_plan(session: Session, *, source_plan: Plan, owner_id, name) -> Plan:
    """Clone a chit's terms into a new empty chit. Ledger and shares are NOT copied."""
    if source_plan.type != "chit" or source_plan.chit is None:
        raise ValidationError("source plan is not a chit")
    chit = source_plan.chit
    return create_chit_plan(
        session, owner_id=owner_id, name=name, currency=source_plan.currency,
        chit_value_minor=chit.chit_value_minor, n_members=chit.n_members,
        commission_bps=chit.commission_bps, start_date=chit.start_date)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_chit_service.py::test_duplicate_copies_terms_empty_ledger -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/khata/services/chits.py tests/test_chit_service.py
git commit -m "feat(chit): duplicate_chit_plan service — clone terms, empty ledger"
```

---

### Task 2: Endpoint — `POST /<plan_id>/chit/duplicate`

**Files:**
- Modify: `src/khata/api/plans.py` (add route after `chit_dividend`, ~line 938)
- Test: `tests/test_chits_api.py`

**Interfaces:**
- Consumes: `chits.duplicate_chit_plan(...)` (Task 1); helpers `_owned_plan`, `_detail`, `current_user`.
- Produces: `POST /api/plans/<int:plan_id>/chit/duplicate` accepting `{"name": str}`, returning `_detail(new_plan)` with 201.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_chits_api.py` (reuses `client`, `_reg`, `_mk`):

```python
def test_chit_duplicate(client):
    _reg(client); src = _mk(client).get_json()["plan"]
    pid = src["id"]
    # record a contribution on the source so we can prove the copy is empty
    client.post(f"/api/plans/{pid}/chit/entries", json={"kind": "chit_contribution", "amount": "50,000"})
    r = client.post(f"/api/plans/{pid}/chit/duplicate", json={"name": "C -2"})
    assert r.status_code == 201
    b = r.get_json()
    new_id = b["plan"]["id"]
    assert new_id != pid
    assert b["plan"]["name"] == "C -2"
    assert b["state"]["chit_value_minor"] == 100000000
    assert b["state"]["n_members"] == 20
    assert b["state"]["months_recorded"] == 0          # empty ledger
    assert b["state"]["total_contributed_minor"] == 0


def test_chit_duplicate_blank_name_falls_back(client):
    _reg(client); pid = _mk(client).get_json()["plan"]["id"]
    b = client.post(f"/api/plans/{pid}/chit/duplicate", json={"name": "  "}).get_json()
    assert b["plan"]["name"] == "C -copy"


def test_chit_duplicate_rejects_non_chit(client):
    _reg(client)
    aid = client.post("/api/plans", json={"type": "asset", "name": "A", "currency": "INR",
                                          "total_price": "1,000"}).get_json()["plan"]["id"]
    assert client.post(f"/api/plans/{aid}/chit/duplicate", json={"name": "x"}).status_code == 400


def test_chit_duplicate_auth(client):
    assert client.post("/api/plans/1/chit/duplicate", json={"name": "x"}).status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_chits_api.py::test_chit_duplicate -v`
Expected: FAIL — 404/405 (route not registered) rather than 201.

- [ ] **Step 3: Write minimal implementation**

Add to `src/khata/api/plans.py` after the `chit_dividend` function (after line 938), before the `shares` routes. `chits` is already imported; `ChitError` is already in the imported exception set used elsewhere in this file.

```python
@bp.post("/<int:plan_id>/chit/duplicate")
def chit_duplicate(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err:
        return err
    if plan.type != "chit":
        return jsonify(error="not_a_chit"), 400
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip() or f"{plan.name} -copy"
    try:
        new_plan = chits.duplicate_chit_plan(g.db, source_plan=plan, owner_id=user.id, name=name)
        g.db.commit()
    except (ChitError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(_detail(new_plan)), 201
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_chits_api.py -v -k duplicate`
Expected: 4 passed (`test_chit_duplicate`, `test_chit_duplicate_blank_name_falls_back`, `test_chit_duplicate_rejects_non_chit`, `test_chit_duplicate_auth`).

- [ ] **Step 5: Commit**

```bash
git add src/khata/api/plans.py tests/test_chits_api.py
git commit -m "feat(chit): POST /chit/duplicate endpoint (owner-only, terms-only clone)"
```

---

### Task 3: Frontend — Duplicate button + AS-BUILT doc

**Files:**
- Modify: `src/khata/static/chit-detail.html` (header actions ~line 364-370; add `duplicatePlan`/`nextChitName` near `deletePlan`)
- Modify: `docs/specs/khata-AS-BUILT.md`
- Test: `tests/test_web.py` (page-content assertion ~line 165)

**Interfaces:**
- Consumes: `POST /api/plans/<id>/chit/duplicate` (Task 2); page globals `plan`, `pid`, helper `actBtn(cls,label,dPath,fn)`.
- Produces: header `Duplicate` button; client redirects to `/chit/<newId>`.

- [ ] **Step 1: Write the failing test**

`tests/test_web.py` line 165-166 asserts the chit page HTML contains a list of needles. Add `"chit/duplicate"` to that list:

```python
    for needle in ["/api/plans/", "app.css", "curtog", "/chit/entries",
                   "/chit/dividend", "position", "/api/auth/me", "sharing.js",
                   "chit/duplicate"]:
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_web.py -v -k chit`
Expected: FAIL — the served HTML does not yet contain `chit/duplicate`.

- [ ] **Step 3: Add the button and handler**

In `src/khata/static/chit-detail.html`, in the header actions block, add a Duplicate button between Print and Delete (after line 366):

```javascript
  acts.append(actBtn('planduplicate','Duplicate','M8 8h11a1 1 0 011 1v11a1 1 0 01-1 1H8a1 1 0 01-1-1V9a1 1 0 011-1zM4 16V4a1 1 0 011-1h11', duplicatePlan));
```

Add these two functions near `deletePlan` (which is defined around the `plandel` usage):

```javascript
function nextChitName(name){
  const m = String(name||'').match(/^(.*?)(\d+)(\D*)$/);   // increment last digit run
  return m ? m[1] + (parseInt(m[2],10)+1) + m[3] : ((name||'Chit') + ' 2');
}
async function duplicatePlan(){
  const suggested = nextChitName(plan.name);
  const name = prompt('Name for the duplicated chit', suggested);
  if(name === null) return;                 // cancelled
  const trimmed = name.trim();
  if(!trimmed) return;                       // blank aborts
  const r = await fetch('/api/plans/'+pid+'/chit/duplicate', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ name: trimmed }) });
  const j = await r.json().catch(()=>({}));
  if(!r.ok){ alert(j.detail || j.error || 'Could not duplicate.'); return; }
  location.href = '/chit/' + j.plan.id;      // land on the new empty chit
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_web.py -v -k chit`
Expected: PASS.

- [ ] **Step 5: Update AS-BUILT doc**

Add a bullet to `docs/specs/khata-AS-BUILT.md` under the chit-funds section describing the Duplicate action:

```markdown
- **Duplicate chit** — header action clones a chit's terms (value, members,
  commission, currency, start date) into a new empty chit via
  `POST /api/plans/<id>/chit/duplicate` (owner-only). Ledger and shares are not
  copied. Name defaults to the source's trailing number incremented (editable);
  redirects to the new chit.
```

- [ ] **Step 6: Commit**

```bash
git add src/khata/static/chit-detail.html tests/test_web.py docs/specs/khata-AS-BUILT.md
git commit -m "feat(chit): Duplicate header action on chit detail + AS-BUILT"
```

---

### Task 4: Full suite + headless screen verify

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/pytest -q`
Expected: all pass (new chit-service, chit-api, and web tests included).

- [ ] **Step 2: Restart the app to pick up Python changes**

Run: `./run-app.sh`
Expected: `Khata up on :5057 ... -> 200`. (Static HTML edits are already live; the new endpoint needs the restart.)

- [ ] **Step 3: Headless screen verify per project protocol**

Follow `.claude/commands/build-screen.md` for the chit detail screen. Manually confirm in the browser on an existing chit (`/chit/16`):
- Duplicate button visible between Print and Delete.
- Clicking prompts with an incremented name (`1 Lakh -1` → `1 Lakh -2`).
- Confirming creates a new chit and redirects to it with an empty schedule (0 of N paid) and matching terms (value, members, commission, start).

- [ ] **Step 4: No commit** — verification only. If the build-screen protocol surfaces fixes, address them in a follow-up commit.

---

## Self-Review

**Spec coverage:**
- Service wrapper (terms-only clone) → Task 1. ✓
- Owner-only, chit-only endpoint returning `_detail` → Task 2. ✓
- Blank-name fallback `"<name> -copy"` → Task 2 (`test_chit_duplicate_blank_name_falls_back`). ✓
- Header button between Print/Delete, `prompt()` with incremented name, redirect to `/chit/<id>` reading `d.plan.id` → Task 3. ✓
- Non-goals (no members/shares, no ledger copy, no name-uniqueness) → asserted empty ledger in Tasks 1-2; nothing copies shares. ✓
- Tests (service, endpoint, web-content) + headless verify + AS-BUILT → Tasks 1-4. ✓

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `duplicate_chit_plan(session, *, source_plan, owner_id, name)` used identically in Task 1 (service) and Task 2 (endpoint call). Redirect reads `j.plan.id`, matching `_detail`'s `{"plan": _summary(plan), ...}` shape. Endpoint path `/<plan_id>/chit/duplicate` consistent across Task 2 and Task 3 fetch.
