# Khata Phase 5 · Plan 5.2 — Hardening Sweep Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8); done-gate = real end-to-end. **money.py is core → review Task 1.** Do NOT touch `build_status.json`, `khata_live.db*`, `OD_khata_mockup/`.

**Goal:** Robustness fixes — malformed numeric input → 400 (not 500) app-wide; holdings None-qty guard + edge tests; frontend `fmtMicro` null guard.

---

### Task 1: money.py parse hardening + holdings guards  ⟶ REVIEW (core money.py)

**Files:** Modify `src/khata/money.py`, `src/khata/services/holdings.py`; Test `tests/test_money.py`, `tests/test_holding_service.py`, `tests/test_plans_api.py`

- [ ] **Step 1: Append failing tests to `tests/test_money.py`**
```python
def test_to_minor_rejects_garbage_with_valueerror():
    import pytest
    from khata.money import to_minor, to_micro, pct_to_bps
    with pytest.raises(ValueError):
        to_minor("abc", "INR")
    with pytest.raises(ValueError):
        to_micro("abc")
    with pytest.raises(ValueError):
        pct_to_bps("abc")
    # valid input still parses
    assert to_minor("12.50", "INR") == 1250
    assert to_micro("3.5") == 3500000
    assert pct_to_bps("8.5") == 850
```

- [ ] **Step 2: Run → FAIL** (garbage raises `decimal.InvalidOperation`, not `ValueError`).

- [ ] **Step 3: Modify `src/khata/money.py`** — change the import:
```python
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
```
In **each** of `to_minor`, `to_micro`, `pct_to_bps`, replace the bare `d = Decimal(s)` line with:
```python
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"invalid number: {s!r}")
```
(Leave the surrounding empty-string and `is_finite()` checks unchanged.)

- [ ] **Step 4: Append failing tests to `tests/test_holding_service.py`** (reuse its `ctx` fixture + helpers; check the real fixture/helper names first):
```python
def test_none_quantity_rejected(ctx):
    s, u = ctx
    from khata.services.holdings import create_holding_plan, add_buy, ValidationError
    import pytest
    plan = create_holding_plan(s, owner_id=u.id, name="G", currency="INR", asset_class="gold", unit="gram")
    with pytest.raises(ValidationError):
        add_buy(s, plan=plan, user_id=u.id, quantity_micro=None, amount_minor=1000000, occurred_at=_now())


def test_sell_to_zero_then_state(ctx):
    s, u = ctx
    from khata.services.holdings import create_holding_plan, add_buy, add_sell, holding_state
    plan = create_holding_plan(s, owner_id=u.id, name="G", currency="INR", asset_class="gold", unit="gram")
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=5_000_000, amount_minor=25000000, occurred_at=_now())
    add_sell(s, plan=plan, user_id=u.id, quantity_micro=2_000_000, amount_minor=11000000, occurred_at=_now())
    add_sell(s, plan=plan, user_id=u.id, quantity_micro=3_000_000, amount_minor=16000000, occurred_at=_now())
    st = holding_state(s, plan.holding)
    assert st["qty_held_micro"] == 0
    assert st["cost_of_held_minor"] == 0


def test_quote_zero_values_at_zero(ctx):
    s, u = ctx
    from khata.services.holdings import create_holding_plan, add_buy, set_quote, holding_state
    plan = create_holding_plan(s, owner_id=u.id, name="G", currency="INR", asset_class="gold", unit="gram")
    add_buy(s, plan=plan, user_id=u.id, quantity_micro=1_000_000, amount_minor=5000000, occurred_at=_now())
    set_quote(s, plan=plan, price_minor=0, as_of=_now())
    st = holding_state(s, plan.holding)
    assert st["current_value_minor"] == 0           # quoted at 0 → value 0, not None
    assert st["unrealized_gain_minor"] == 0 - st["cost_of_held_minor"]
```
NOTE: if the file's helper for "now" is named differently than `_now()`, adapt. If `ctx` yields a
different shape, adapt the unpacking. Read the file first.

- [ ] **Step 5: Run → FAIL** (None → TypeError).

- [ ] **Step 6: Modify `src/khata/services/holdings.py`** — in `_add_entry`, before the existing
  `if quantity_micro <= 0:` check, add:
```python
    if quantity_micro is None or amount_minor is None:
        raise ValidationError("quantity and amount are required")
```
And simplify `add_sell`'s oversell guard to (drop the now-redundant None/`> 0` pre-checks):
```python
    if quantity_micro is not None and quantity_micro > _qty_held_micro(plan):
        raise ValidationError("cannot sell more than currently held")
```

- [ ] **Step 7: Append a 400-not-500 API test to `tests/test_plans_api.py`** (use its `client`/`_register` helpers):
```python
def test_malformed_amount_is_400_not_500(client):
    _register(client, "a@b.com")
    pid = client.post("/api/plans", json={"name": "P", "currency": "INR", "total_price": "1000"}).get_json()["plan"]["id"]
    r = client.post(f"/api/plans/{pid}/payments", json={"amount": "abc", "method": "upi", "funding_source": "savings"})
    assert r.status_code == 400
```
(Confirm `_register`'s signature in the file; adapt the call if needed.)

- [ ] **Step 8: Run + full suite** — `pytest tests/test_money.py tests/test_holding_service.py tests/test_plans_api.py -q`, then `pytest -q` (expect 167 — 160 + 7).

- [ ] **Step 9: Commit**
```bash
git add src/khata/money.py src/khata/services/holdings.py tests/test_money.py tests/test_holding_service.py tests/test_plans_api.py
git commit -m "fix(hardening): malformed numbers → 400 not 500 (money parse); holdings None-qty guard + edge tests

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Frontend fmtMicro guard + docs

**Files:** Modify `src/khata/static/holding-detail.html`; Modify `docs/AGENT_LEARNINGS.md`, `docs/superpowers/Progress.md`, `docs/superpowers/ROADMAP.md`

- [ ] **Step 1: Guard `fmtMicro` in `src/khata/static/holding-detail.html`** — find the `fmtMicro` function and ensure it returns `"—"` for null/undefined:
```javascript
  function fmtMicro(q) { if (q === null || q === undefined) return "—"; return (q / 1e6).toLocaleString("en-IN"); }
```
(If it already has the guard, no change — verify and note it.) Full suite must stay green (`pytest -q`, 167).

- [ ] **Step 2: Commit** `fix(web): fmtMicro null guard (holding-detail)` (only if the file changed).

- [ ] **Step 3: Append to `docs/AGENT_LEARNINGS.md`**:
```markdown

## 2026-06-05 — Plan 5.2 (Hardening sweep)
- **Systemic 500→400 fix:** `money.to_minor`/`to_micro`/`pct_to_bps` now catch `decimal.InvalidOperation`
  and raise `ValueError`, so a non-numeric amount/rate/quantity on ANY money endpoint returns 400 (the
  API except tuples already catch ValueError) instead of a 500. One central change, app-wide effect.
- Holdings `_add_entry` rejects `None` quantity/amount with `ValidationError` (was `TypeError`); added
  edge tests (sell-to-zero, multiple sells, quote=0 → value 0 not None). `fmtMicro` null-guarded.
- Deliberately deferred (still logged): unused `session` arg on `*_state`/`net_worth`; `loan_state`
  `as_of`; `ledger_entries(plan_id,kind)` index; DB CHECK/unique constraints; google transport errors.
```

- [ ] **Step 4: Flip 5.2 boxes** in Progress.md + ROADMAP.md; bump tests to 167. Commit (orchestrator owns build_status.json).

---

## Self-Review
The money.py fix is the load-bearing item — one change makes every money endpoint return 400 (not 500)
on garbage, verified by a real API test. Holdings None-guard + edge tests close coverage gaps. fmtMicro
guarded. No migration. Tests 160→167. ✓

## Next
5.3 Analysis tools.
