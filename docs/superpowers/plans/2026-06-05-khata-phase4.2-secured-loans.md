# Khata Phase 4 · Plan 4.2 — Secured Loans / Collateral Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8) per task; done-gate = real end-to-end. **Money/derived logic → dual review on Tasks 2–3.** Do NOT touch `build_status.json`, `khata_live.db*`, `OD_khata_mockup/`.

**Goal:** Secure a loan with a pledged holding; derive collateral value + LTV. Net worth unchanged (collateral is informational, not double-counted).

---

### Task 1: Loan `secured` + `collateral_plan_id` + migration

**Files:** Modify `src/khata/models/loan.py`; Create `alembic/versions/<rev>_loan_collateral.py`; Test `tests/test_loan_models.py`

- [ ] **Step 1: Append failing test to `tests/test_loan_models.py`** (read the file first; reuse its session helper):
```python
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
```

- [ ] **Step 2: Run → FAIL** (unexpected kwargs).

- [ ] **Step 3: Add columns to `src/khata/models/loan.py`** — add the import `Boolean` to the sqlalchemy import line and `from sqlalchemy.sql import expression`, then in `Loan` after `tenure_months` add:
```python
    secured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=expression.false())
    collateral_plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
```
(`ForeignKey` is already imported.)

- [ ] **Step 4: Migration** (scratch DB; free nothing — uses khata.db):
```bash
rm -f khata.db khata.db-wal khata.db-shm
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic revision --autogenerate -m "loan collateral"
```
Confirm: `down_revision = 'dacfeed37679'`; `upgrade()` adds ONLY `loans.secured` (with `server_default`)
+ `loans.collateral_plan_id` (inside `batch_alter_table('loans')`); `downgrade()` drops them. No other
table. **Verify the `secured` add carries a `server_default`** (existing loan rows need it). Apply +
round-trip:
```bash
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic downgrade -1 && KHATA_DATABASE_URL=sqlite:///khata.db .venv/bin/alembic upgrade head
rm -f khata.db khata.db-wal khata.db-shm
```

- [ ] **Step 5: Full suite** — `pytest -q` (expect 128 — 127 + 1).

- [ ] **Step 6: Commit**
```bash
git add src/khata/models/loan.py alembic/versions/ tests/test_loan_models.py
git commit -m "feat(models+db): loan secured flag + collateral_plan_id (pledge a holding)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Service — set_collateral + loan_state LTV  ⟶ DUAL REVIEW

**Files:** Modify `src/khata/services/loans.py`; Test `tests/test_loan_service.py`

- [ ] **Step 1: Append failing tests to `tests/test_loan_service.py`** (reuse its fixtures; add `from khata.services.holdings import create_holding_plan, add_buy, set_quote` + the existing loan helpers):
```python
def test_set_collateral_and_ltv(loan_ctx_or_session_fixture):
    # ADAPT to the file's actual fixture name. Build: a user, a holding worth ₹10,00,000 (quoted),
    # a taken loan disbursed ₹6,00,000. Then set the holding as collateral and check LTV = 60%.
    pass
```
NOTE: read `tests/test_loan_service.py` to learn its fixture/helper names, then write REAL tests
(replace the stub) covering: `set_collateral` links a same-currency quoted holding → `loan_state`
returns `secured=True` and `collateral={value_minor: 100000000, ltv_pct: 60}` for a ₹6,00,000 principal;
non-holding collateral → `ValidationError`; cross-currency → `ValidationError`; cross-owner →
`ValidationError`; unlink (`collateral_plan_id=None`) → `secured=False`, `collateral=None`; unquoted
collateral → `ltv_pct` is `None`. (Principal ₹6,00,000 = 60000000 minor; collateral value 100000000 →
LTV = round(60000000*100/100000000) = 60.)

- [ ] **Step 2: Run → FAIL**.

- [ ] **Step 3: Add to `src/khata/services/loans.py`**:
```python
def set_collateral(session: Session, *, plan: Plan, collateral_plan_id):
    loan = plan.loan
    if collateral_plan_id is None:
        loan.secured = False
        loan.collateral_plan_id = None
        session.flush()
        return loan
    coll = session.get(Plan, collateral_plan_id)
    if coll is None or coll.type != "holding":
        raise ValidationError("collateral must be a holding plan")
    if coll.owner_user_id != plan.owner_user_id:
        raise ValidationError("collateral must be owned by you")
    if coll.currency != plan.currency:
        raise ValidationError("collateral must match the loan currency")
    loan.secured = True
    loan.collateral_plan_id = coll.id
    session.flush()
    return loan
```
And in `loan_state`, just before the `return {`, compute collateral (uses `principal_outstanding`
already computed above; lazy-import holdings to keep module load clean):
```python
    secured = bool(loan.secured)
    collateral = None
    if loan.collateral_plan_id is not None:
        from . import holdings
        cp = session.get(Plan, loan.collateral_plan_id)
        if cp is not None and cp.holding is not None:
            hs = holdings.holding_state(session, cp.holding)
            val = hs["current_value_minor"]
            ltv = (int((Decimal(max(0, principal_outstanding)) * 100 / val)
                       .quantize(Decimal(1), rounding=ROUND_HALF_UP)) if val else None)
            collateral = {"plan_id": cp.id, "name": cp.name, "asset_class": hs["asset_class"],
                          "currency": cp.currency, "value_minor": val, "ltv_pct": ltv}
```
Then add `"secured": secured, "collateral": collateral,` to the returned dict. (`Decimal`,
`ROUND_HALF_UP` are already imported in loans.py.)

- [ ] **Step 4: Full suite** — `pytest tests/test_loan_service.py -q`, then `pytest -q` (expect ~133, count per your added tests).

- [ ] **Step 5: Commit** `feat(loans): set_collateral + derived LTV in loan_state`.

---

### Task 3: API — create collateral + /loan/collateral  ⟶ DUAL REVIEW

**Files:** Modify `src/khata/api/plans.py`; Test `tests/test_loans_api.py`

- [ ] Wire: loan `create()` branch accepts `secured`/`collateral_plan_id` (after creating the loan,
  if `data.get("collateral_plan_id")`, call `loans.set_collateral(g.db, plan=plan, collateral_plan_id=...)`);
  `_summary` loan adds `secured`. Add endpoint:
```python
@bp.post("/<int:plan_id>/loan/collateral")
def loan_collateral(plan_id):
    user = current_user()
    if user is None: return jsonify(error="unauthenticated"), 401
    plan, err = _owned_plan(user, plan_id)
    if err: return err
    if plan.type != "loan": return jsonify(error="not_a_loan"), 400
    data = request.get_json(silent=True) or {}
    try:
        loans.set_collateral(g.db, plan=plan, collateral_plan_id=data.get("collateral_plan_id"))
        g.db.commit()
    except (LoanError, ValueError, TypeError) as e:
        g.db.rollback(); return jsonify(error="invalid", detail=str(e)), 400
    return jsonify(state=loans.loan_state(g.db, plan.loan, as_of=date.today())), 200
```
- [ ] Tests (`tests/test_loans_api.py`): create a holding + a loan, POST `/loan/collateral
  {collateral_plan_id}` → 200 with `state.secured True` + `state.collateral.ltv_pct`; unlink with
  `null` → secured False; 401 unauth; 403 non-owner; 400 on a non-holding collateral id. Full suite green. Commit.

---

### Task 4: UI — loan-detail collateral section + pledge modal

**Files:** Modify `src/khata/static/loan-detail.html`; Test `tests/test_web.py`

- [ ] Read `loan-detail.html`. Add a **Collateral** `.sec`: if `state.secured && state.collateral`, render
  the pledged holding (name · asset_class · value via fmtMinor · **LTV badge** — green <60, amber 60–80,
  red >80, "—" if ltv null) + an "Unpledge" link (`POST /loan/collateral {collateral_plan_id:null}`).
  Else a "Pledge collateral" button → modal: `GET /api/plans`, filter `p.type==="holding" && p.currency===currency`,
  list them (name + asset_class); on pick `POST /loan/collateral {collateral_plan_id:p.id}` → reload.
  All DOM via createElement (K4); errors via textContent. Append a `test_web.py` assertion that `/loan/1`
  body contains `/loan/collateral`. Done-gate: create holding+loan, pledge via the endpoint, GET state
  shows secured + LTV. Commit.

---

### Task 5: Smoke + docs
- [ ] End-to-end smoke (create holding worth ₹10L quoted + a ₹6L loan, pledge, confirm LTV 60). Append
  4.2 learnings. Flip 4.2 boxes in Progress.md + ROADMAP.md. Commit (orchestrator owns build_status.json).

---

## Self-Review
LTV = round(principal_outstanding × 100 / collateral_value) (Decimal). Collateral validated same-owner/
same-currency/holding. Net worth untouched (no double-count). Cross-service holdings lazy-import.
Money/derived logic dual-reviewed (Tasks 2–3). ✓

## Next
4.3 Retirement / 401(k) planner.
