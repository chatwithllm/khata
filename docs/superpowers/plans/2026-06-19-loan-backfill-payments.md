# Loan Backfill Payments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let owners clear historical interest dues on pre-Khata loans — individually per month or in bulk up to a cutoff — by recording backdated `interest_payment` entries.

**Architecture:** Reuse the existing greedy `interest_paid` pool in `loans.loan_state`. Bulk is a new service `backfill_loan_interest` + `POST /loan/backfill` that adds one backdated `interest_payment` per unmarked month. Individual marking reuses the existing `POST /loan/entries`; only the loan-detail UI gains row-level + bulk controls. No schema change.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy, pytest; vanilla-JS static page (`loan-detail.html`).

---

## File Structure

- **Modify** `src/khata/services/loans.py` — add `backfill_loan_interest(...)` (Task 1). Add `datetime, timezone` to the `datetime` import.
- **Modify** `src/khata/api/plans.py` — add `POST /<int:plan_id>/loan/backfill` route (Task 2).
- **Modify** `src/khata/static/loan-detail.html` — per-row mark button + form, bulk control, wiring (Task 3).
- **Test** `tests/test_loan_service.py` — service tests (Task 1).
- **Test** `tests/test_loan_backfill_api.py` — new API test file (Task 2).
- **Modify** `docs/specs/khata-AS-BUILT.md` — §9 + change log (Task 4).

Existing facts the implementation relies on (verified):
- `loan_state(session, loan, as_of: date) -> dict` returns `schedule` rows
  `{month_index, period_start (ISO date str), expected_minor, applied_minor, status}`,
  plus `interest_accrued_minor`, `interest_paid_minor`, `months_behind`, `next_due_month`.
- `log_loan_entry(session, *, plan, user_id, kind, amount_minor, occurred_at, method=None, note=None, acting_user_id=None, fx_rate_micro=None)` records the entry and sets `direction` via `_direction_for(loan.direction, kind)`.
- `_month_add(d: date, n: int) -> date` gives month `n`'s date from `loan.start_date`.
- `ValidationError(LoanError)` is caught by route handlers' `except (LoanError, ValueError, TypeError)` → HTTP 400.
- Schedule only contains *complete elapsed* months (all rows are in the past).
- Pool is greedy oldest-first, so adding exactly `expected − applied` for each due/partial month up to the cutoff clears precisely those months.

---

### Task 1: `backfill_loan_interest` service

**Files:**
- Modify: `src/khata/services/loans.py:1-4` (import) and append the function near `log_loan_entry`.
- Test: `tests/test_loan_service.py` (append).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_loan_service.py`:

```python
from khata.services.loans import backfill_loan_interest


def _lent_loan(s, u, start):
    plan = create_loan_plan(s, owner_id=u.id, name="Lent Sunil", currency="INR",
                            direction="given", interest_type="monthly", rate_bps=300,
                            start_date=start)
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=220000000,
                     occurred_at=_dt(start.year, start.month, start.day))
    s.flush()
    return plan


def test_backfill_through_month_clears_all(ctx):
    s, u = ctx
    plan = _lent_loan(s, u, date(2023, 12, 12))
    as_of = date(2024, 5, 12)  # 5 complete months -> months 0..4
    before = loan_state(s, plan.loan, as_of=as_of)
    assert len(before["schedule"]) == 5 and before["months_behind"] == 5

    res = backfill_loan_interest(s, plan=plan, user_id=u.id, through_month=4, as_of=as_of)
    s.flush()
    assert res["count"] == 5
    after = loan_state(s, plan.loan, as_of=as_of)
    assert after["months_behind"] == 0
    assert after["interest_paid_minor"] == after["interest_accrued_minor"]
    # each backfilled entry is an interest_payment dated at its month's period_start
    pays = [e for e in plan.ledger_entries if e.kind == "interest_payment"]
    assert len(pays) == 5
    assert {e.occurred_at.date() for e in pays} == {
        date(2023, 12, 12), date(2024, 1, 12), date(2024, 2, 12),
        date(2024, 3, 12), date(2024, 4, 12)}
    assert all(e.direction == "in" for e in pays)  # given -> repaid to me


def test_backfill_is_idempotent(ctx):
    s, u = ctx
    plan = _lent_loan(s, u, date(2023, 12, 12))
    as_of = date(2024, 5, 12)
    backfill_loan_interest(s, plan=plan, user_id=u.id, through_month=4, as_of=as_of)
    s.flush()
    res2 = backfill_loan_interest(s, plan=plan, user_id=u.id, through_month=4, as_of=as_of)
    assert res2 == {"count": 0, "total_minor": 0}


def test_backfill_tops_up_partial(ctx):
    s, u = ctx
    plan = _lent_loan(s, u, date(2023, 12, 12))
    as_of = date(2024, 5, 12)
    # month 0 expected = 3% of 22,00,000 = 66,000.00 -> pay half first
    log_loan_entry(s, plan=plan, user_id=u.id, kind="interest_payment",
                   amount_minor=3300000, occurred_at=_dt(2023, 12, 12))
    s.flush()
    res = backfill_loan_interest(s, plan=plan, user_id=u.id, through_month=0, as_of=as_of)
    s.flush()
    assert res["count"] == 1 and res["total_minor"] == 3300000   # only the remainder
    after = loan_state(s, plan.loan, as_of=as_of)
    assert after["schedule"][0]["status"] == "paid"


def test_backfill_cutoff_respected(ctx):
    s, u = ctx
    plan = _lent_loan(s, u, date(2023, 12, 12))
    as_of = date(2024, 5, 12)
    res = backfill_loan_interest(s, plan=plan, user_id=u.id, through_month=2, as_of=as_of)
    s.flush()
    assert res["count"] == 3
    after = loan_state(s, plan.loan, as_of=as_of)
    statuses = [r["status"] for r in after["schedule"]]
    assert statuses == ["paid", "paid", "paid", "due", "due"]


def test_backfill_through_date(ctx):
    s, u = ctx
    plan = _lent_loan(s, u, date(2023, 12, 12))
    as_of = date(2024, 5, 12)
    res = backfill_loan_interest(s, plan=plan, user_id=u.id,
                                 through_date=date(2024, 2, 15), as_of=as_of)
    s.flush()
    assert res["count"] == 3  # months 0 (Dec), 1 (Jan), 2 (Feb)


def test_backfill_validates_cutoff(ctx):
    s, u = ctx
    plan = _lent_loan(s, u, date(2023, 12, 12))
    as_of = date(2024, 5, 12)
    with pytest.raises(ValidationError):   # neither cutoff
        backfill_loan_interest(s, plan=plan, user_id=u.id, as_of=as_of)
    with pytest.raises(ValidationError):   # both cutoffs
        backfill_loan_interest(s, plan=plan, user_id=u.id, through_month=1,
                               through_date=date(2024, 1, 1), as_of=as_of)
    with pytest.raises(ValidationError):   # future date
        backfill_loan_interest(s, plan=plan, user_id=u.id,
                               through_date=date(2024, 6, 1), as_of=as_of)


def test_backfill_interest_free_noop(ctx):
    s, u = ctx
    plan = create_loan_plan(s, owner_id=u.id, name="Free", currency="INR",
                            direction="given", interest_type="none", rate_bps=0,
                            start_date=date(2024, 1, 1))
    add_disbursement(s, plan=plan, user_id=u.id, amount_minor=100000000,
                     occurred_at=_dt(2024, 1, 1))
    s.flush()
    res = backfill_loan_interest(s, plan=plan, user_id=u.id, through_month=5,
                                 as_of=date(2024, 6, 1))
    assert res == {"count": 0, "total_minor": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_loan_service.py -k backfill -v`
Expected: FAIL — `ImportError: cannot import name 'backfill_loan_interest'`.

- [ ] **Step 3: Update the datetime import**

In `src/khata/services/loans.py` change line 2:

```python
from datetime import date, datetime, timezone
```

- [ ] **Step 4: Implement `backfill_loan_interest`**

Append in `src/khata/services/loans.py` right after `log_loan_entry`:

```python
def backfill_loan_interest(session: Session, *, plan: Plan, user_id,
                           through_month: int | None = None,
                           through_date: date | None = None,
                           as_of: date | None = None,
                           acting_user_id=None) -> dict:
    """Record backdated interest payments to clear historical dues on a loan, oldest
    month first, up to a cutoff. Each unmarked schedule month (status due/partial) at or
    before the cutoff gets one `interest_payment` of its REMAINING expected interest,
    dated at that month's period_start (12:00 UTC). Idempotent: already-paid months add
    nothing. Returns {count, total_minor}.

    Provide exactly one cutoff: `through_month` (a month_index) or `through_date`.
    """
    loan = plan.loan
    if loan is None:
        raise ValidationError("not a loan plan")
    if (through_month is None) == (through_date is None):
        raise ValidationError("provide exactly one of through_month / through_date")
    as_of = as_of or date.today()
    if through_date is not None and through_date > as_of:
        raise ValidationError("cutoff date cannot be in the future")

    st = loan_state(session, loan, as_of=as_of)
    schedule = st["schedule"]
    if not schedule:
        return {"count": 0, "total_minor": 0}

    if through_month is not None:
        cutoff_index = int(through_month)
    else:
        cutoff_index = -1
        for row in schedule:
            if date.fromisoformat(row["period_start"]) <= through_date:
                cutoff_index = row["month_index"]

    count = 0
    total = 0
    for row in schedule:
        if row["month_index"] > cutoff_index:
            break
        if row["status"] == "paid":
            continue
        remaining = row["expected_minor"] - row["applied_minor"]
        if remaining <= 0:
            continue
        pm = _month_add(loan.start_date, row["month_index"])
        occurred = datetime(pm.year, pm.month, pm.day, 12, 0, tzinfo=timezone.utc)
        log_loan_entry(session, plan=plan, user_id=user_id, kind="interest_payment",
                       amount_minor=remaining, occurred_at=occurred,
                       note=f"Backfill — Month {row['month_index']} interest",
                       acting_user_id=acting_user_id)
        count += 1
        total += remaining
    return {"count": count, "total_minor": total}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_loan_service.py -k backfill -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add src/khata/services/loans.py tests/test_loan_service.py
git commit -m "feat(loan): backfill_loan_interest service for historical dues"
```

---

### Task 2: `POST /loan/backfill` endpoint

**Files:**
- Modify: `src/khata/api/plans.py` (append route after `loan_entry`, ~line 757).
- Test: `tests/test_loan_backfill_api.py` (create).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_loan_backfill_api.py`:

```python
from datetime import date

import pytest

from khata.db import Base, make_engine, make_session_factory
from khata.models import User
from khata.services.loans import create_loan_plan, add_disbursement
from khata.services.auth import issue_token  # used to authenticate the client


@pytest.fixture
def seeded(app):
    # app fixture builds the Flask app on an in-memory/temp DB (see conftest.py)
    engine = app.config["ENGINE"] if "ENGINE" in app.config else None
    # Fall back: create the loan via the service using the app's session factory.
    from khata.db import get_session_factory
    Session = get_session_factory()
    with Session() as s:
        u = User(email="owner@x.com", display_name="Owner", password_hash="x")
        s.add(u); s.flush()
        plan = create_loan_plan(s, owner_id=u.id, name="Lent", currency="INR",
                                direction="given", interest_type="monthly", rate_bps=300,
                                start_date=date(2023, 12, 12))
        add_disbursement(s, plan=plan, user_id=u.id, amount_minor=220000000,
                         occurred_at=__import__("datetime").datetime(2023, 12, 12))
        s.commit()
        return u.id, plan.id


def _auth(client, uid):
    client.set_cookie("localhost", "session", issue_token(uid))
```

> NOTE TO IMPLEMENTER: `tests/conftest.py` already provides `app` and `client`
> fixtures and disables live FX. Before writing these tests, open `conftest.py` and
> `tests/test_secured_loans_api.py` and copy their exact auth/seed pattern (how they
> create a user, log in the test client, and create a loan through the API or session).
> Replace the `seeded`/`_auth` placeholders above with that project pattern — do not
> invent `issue_token`/`get_session_factory` if the project uses a different mechanism.
> The assertions below are the contract to preserve:

```python
def test_backfill_owner_clears_dues(client, seeded):
    uid, pid = seeded
    _auth(client, uid)
    r = client.post(f"/api/plans/{pid}/loan/backfill", json={"through_month": 4})
    assert r.status_code == 201
    body = r.get_json()
    assert body["result"]["count"] >= 1
    assert body["state"]["months_behind"] == 0


def test_backfill_requires_a_cutoff(client, seeded):
    uid, pid = seeded
    _auth(client, uid)
    r = client.post(f"/api/plans/{pid}/loan/backfill", json={})
    assert r.status_code == 400


def test_backfill_rejects_both_cutoffs(client, seeded):
    uid, pid = seeded
    _auth(client, uid)
    r = client.post(f"/api/plans/{pid}/loan/backfill",
                    json={"through_month": 1, "through_date": "2024-01-01"})
    assert r.status_code == 400


def test_backfill_forbidden_for_non_owner(client, seeded):
    uid, pid = seeded
    # a different, non-owner user
    from khata.db import get_session_factory
    Session = get_session_factory()
    with Session() as s:
        other = User(email="stranger@x.com", display_name="S", password_hash="x")
        s.add(other); s.commit(); oid = other.id
    _auth(client, oid)
    r = client.post(f"/api/plans/{pid}/loan/backfill", json={"through_month": 4})
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_loan_backfill_api.py -v`
Expected: FAIL — 404/405 on the route (not yet defined) or fixture errors to be reconciled against `conftest.py`.

- [ ] **Step 3: Implement the route**

Append in `src/khata/api/plans.py` after the `loan_entry` route (after ~line 757):

```python
@bp.post("/<int:plan_id>/loan/backfill")
def loan_backfill(plan_id):
    user = current_user()
    if user is None:
        return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)   # owner-only
    if err:
        return err
    if plan.type != "loan":
        return jsonify(error="not_a_loan"), 400
    data = request.get_json(silent=True) or {}
    tm = data.get("through_month")
    td = data.get("through_date")
    try:
        through_month = int(tm) if tm not in (None, "") else None
        through_date = date.fromisoformat(td) if td else None
        result = loans.backfill_loan_interest(
            g.db, plan=plan, user_id=user.id, acting_user_id=user.id,
            through_month=through_month, through_date=through_date)
        g.db.commit()
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback()
        return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(result=result,
                   state=loans.loan_state(g.db, plan.loan, as_of=date.today())), 201
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_loan_backfill_api.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/khata/api/plans.py tests/test_loan_backfill_api.py
git commit -m "feat(loan): POST /loan/backfill endpoint (owner-only)"
```

---

### Task 3: loan-detail UI — per-row mark + bulk control

**Files:**
- Modify: `src/khata/static/loan-detail.html` — `renderSchedule` (~573–620) and a new bulk control; reuse `$`, `el`, `amtSpan`, `fmtMonthYear`, `boot()` (full reload at line 1263), and the loan's `direction` from `st.direction`.

Wording helper (lent → "received", borrowed → "paid"):

```js
function markVerb(st){ return st.direction === 'taken' ? 'paid' : 'received'; }
```

- [ ] **Step 1: Add the per-row mark button**

In `renderSchedule`, inside the `for (const it of rows)` loop, after the `sv` block is appended to `srow`, add a button for past, unpaid rows. `today` ISO compare against `it.period_start`:

```js
    const todayIso = new Date().toISOString().slice(0,10);
    if (it.status !== 'paid' && it.period_start.slice(0,10) <= todayIso) {
      const remaining = (it.expected_minor||0) - (it.applied_minor||0);
      const b = el('button','smark','Mark '+markVerb(st));
      b.type='button';
      b.addEventListener('click', ()=>openMark(it, remaining, st));
      srow.append(b);
    }
```

- [ ] **Step 2: Add the mark form (modal) handler**

Add near the other handlers. It reuses the existing entry POST (`/loan/entries`) — interest first, optional principal second — then `boot()`:

```js
async function openMark(it, remaining, st){
  const verb = markVerb(st);
  const amt = prompt('Interest '+verb+' for Month '+it.month_index+' (₹):',
                     (remaining/100).toFixed(2));
  if (amt === null) return;
  const prin = prompt('Optional principal '+verb+' this month (₹, blank for none):','');
  const when = it.period_start.slice(0,10) + 'T12:00:00';
  const post = (kind, rupees) => fetch('/api/plans/'+pid+'/loan/entries', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ kind, amount: rupees, occurred_at: when,
                             note: 'Backfill — Month '+it.month_index }) });
  try {
    let r = await post('interest_payment', amt);
    if (!r.ok) throw new Error('interest');
    if (prin && Number(prin) > 0) {
      r = await post('principal_repayment', prin);
      if (!r.ok) throw new Error('principal');
    }
    await boot();
  } catch(e){ alert('Could not record payment.'); }
}
```

> The two `prompt()` calls are a deliberately minimal first cut that matches "expected
> but editable + optional principal". If a richer inline form is preferred, build it
> with `el(...)` mirroring the existing edit-entry modal — same POST contract.

- [ ] **Step 3: Add the bulk control**

In `renderSchedule`, after `box.append(ph)` and before building `sched`, add a bulk button when there is at least one unpaid past month:

```js
  const behind = st.months_behind||0;
  if (rows.length && behind > 0) {
    const bulk = el('button','sbulk','Mark '+markVerb(st)+' through…');
    bulk.type='button';
    bulk.addEventListener('click', ()=>openBulk(rows, st));
    ph.append(bulk);
  }
```

Add the handler:

```js
async function openBulk(rows, st){
  const verb = markVerb(st);
  const maxM = rows[rows.length-1].month_index;
  const ans = prompt('Mark '+verb+' through which month? (0–'+maxM+')', String(maxM));
  if (ans === null) return;
  const m = parseInt(ans, 10);
  if (isNaN(m) || m < 0) return;
  // preview total of unmarked expected up to m
  let n=0, total=0;
  for (const it of rows){ if(it.month_index>m) break;
    if(it.status!=='paid'){ n++; total += (it.expected_minor||0)-(it.applied_minor||0); } }
  if (!n){ alert('Nothing to mark in that range.'); return; }
  if (!confirm('Mark '+n+' month(s) '+verb+' · '+sym(st.currency)+(total/100).toLocaleString()+'?')) return;
  try {
    const r = await fetch('/api/plans/'+pid+'/loan/backfill', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ through_month: m }) });
    if (!r.ok) throw new Error();
    await boot();
  } catch(e){ alert('Bulk mark failed.'); }
}
```

- [ ] **Step 4: Minimal styles**

Append to the page's `<style>` (scoped to existing schedule classes — do NOT touch `ledger.css`):

```css
.smark{ font:inherit; font-size:12px; padding:4px 10px; border-radius:8px;
  border:1px solid var(--line); background:transparent; color:var(--ink); cursor:pointer; }
.smark:hover{ background:color-mix(in srgb, var(--gold) 14%, transparent); }
.sbulk{ font:inherit; font-size:12px; margin-left:auto; padding:4px 10px;
  border-radius:8px; border:1px solid var(--line); background:transparent;
  color:var(--ink); cursor:pointer; }
```

- [ ] **Step 5: Headless verify (build-screen Phase 4 / verify-screen)**

Start the dev instance (`run-app.sh`) and run the project's `/build-screen` → `verify-screen` 6 steps against the loan-detail route for a lent loan with months behind. Required to pass:
- Headless DOM render: zero JS throws; `Mark received` buttons present on due rows; `Mark received through…` present.
- Click-path (in the headless harness or manually): per-row mark reduces `months_behind`; bulk clears through the chosen month.
- All existing tests green.

Expected: `Headless ✅`, no console errors, schedule re-renders after `boot()`.

- [ ] **Step 6: Commit**

```bash
git add src/khata/static/loan-detail.html
git commit -m "feat(loan): mark historical interest paid/received (row + bulk) on loan detail"
```

---

### Task 4: AS-BUILT doc + final verification

**Files:**
- Modify: `docs/specs/khata-AS-BUILT.md` — §9 (enhancements) + change log.

- [ ] **Step 1: Add the change-log + §9 entry**

Add to the top of `## Change log`:

```markdown
- 2026-06-19 — Backfill historical loan payments. Loan detail can now mark past
  interest dues as paid/received (wording follows loan direction): a per-month button
  on each unpaid schedule row (interest = remaining expected, editable, + optional
  principal, dated in that month) and a bulk "mark through Month N" control. Backend:
  new `loans.backfill_loan_interest` + owner-only `POST /loan/backfill`; both record
  backdated `interest_payment` entries against the existing greedy interest pool — no
  schema change. Idempotent (paid months skipped).
```

Add a matching one-paragraph entry under `## 9` (enhancements) following the section's existing style.

- [ ] **Step 2: Full suite + headless once more**

Run: `.venv/bin/pytest -q`
Expected: all green. Re-run the loan-detail headless check; confirm `DONE ✅` per build-screen.

- [ ] **Step 3: Commit**

```bash
git add docs/specs/khata-AS-BUILT.md
git commit -m "docs(loan): record backfill historical payments in AS-BUILT"
```

---

## Self-Review

**Spec coverage:**
- Individual per-month mark → Task 3 Step 1–2 (reuses existing `POST /loan/entries`). ✅
- Bulk mark through cutoff → Task 1 (service) + Task 2 (endpoint) + Task 3 Step 3. ✅
- Expected-but-editable interest + optional principal → Task 3 Step 2 (two prompts). ✅
- Direction wording (paid/received) → `markVerb` helper. ✅
- Idempotent / partial top-up / cutoff / interest-free / future-guard → Task 1 tests. ✅
- Owner-only → Task 2 (`_owned_plan`) + test. ✅
- No migration → confirmed; only ledger entries created. ✅
- Docs rule → Task 4. ✅
- Headless verify per build-screen → Task 3 Step 5, Task 4 Step 2. ✅

**Placeholder scan:** The only intentional "fill-in" is the API test fixture (Task 2 Step 1), explicitly flagged because `conftest.py`'s exact auth/seed mechanism must be copied rather than guessed; the behavioral assertions are concrete. All code steps include real code.

**Type consistency:** `backfill_loan_interest(through_month, through_date, as_of, acting_user_id)` is used identically in service tests, the endpoint, and the plan text. Return shape `{count, total_minor}` consistent across Task 1/2. Schedule keys (`month_index`, `period_start`, `expected_minor`, `applied_minor`, `status`) match `loan_state`. `markVerb`, `openMark`, `openBulk` referenced consistently in Task 3.
