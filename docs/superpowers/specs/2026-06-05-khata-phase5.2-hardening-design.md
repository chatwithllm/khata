# Khata Phase 5 · Plan 5.2 — Hardening Sweep Design Spec

**Status:** Approved (autonomous) 2026-06-05. Burns down the highest-value deferred follow-ups logged in
`AGENT_LEARNINGS.md`. No new features — correctness/robustness only.

## Items (scoped to high-value, low-risk)
1. **Malformed numeric input → 400, not 500 (systemic).** `money.to_minor`/`to_micro`/`pct_to_bps` call
   `Decimal(s)`, which raises `decimal.InvalidOperation` (an `ArithmeticError`, NOT `ValueError`) on
   garbage like `"abc"`. The API `except (… ValueError, TypeError)` tuples don't catch it → **every**
   money endpoint returns 500 on a non-numeric amount/rate/quantity. **Fix centrally:** wrap the
   `Decimal(s)` parse in each of the three helpers and raise `ValueError` on `InvalidOperation`. This
   fixes all endpoints at once (no per-endpoint change).
2. **Holdings `None`/0 quantity → `ValidationError`, not `TypeError`.** `add_buy`/`add_sell` do
   `quantity_micro <= 0`, which raises `TypeError` when `quantity_micro is None`. Add an explicit
   `if quantity_micro is None: raise ValidationError(...)` in the shared `_add_entry` (and simplify the
   `add_sell` oversell guard). Same for `amount_minor` None. (API-reachable only via a missing field, but
   makes the service self-consistent.)
3. **Holdings edge-case tests** (close the coverage gaps the reviews flagged): sell-to-zero then
   re-value; multiple sequential sells; `quote = 0` (current_value 0, not None).
4. **Frontend `fmtMicro` null guard.** In `holding-detail.html` (and any page using it),
   `fmtMicro(null)` would render `"NaN"`. Add the same null-guard `fmtMinor` has.

**Deliberately NOT in scope (low value / premature):** the unused `session` arg on `*_state`/`net_worth`
(intentional symmetry); exposing `loan_state` `as_of`; a `ledger_entries(plan_id, kind)` index
(premature at personal scale); DB `CHECK`/extra unique constraints (the API already enforces);
`verify_google_credential` transport-error handling (network-only, returns 500 which is arguably correct
for "Google unreachable"). These stay logged for later.

## Changes
### `src/khata/money.py`
In `to_minor`, `to_micro`, `pct_to_bps`: replace the bare `d = Decimal(s)` with
```python
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"invalid number: {s!r}")
```
Add `InvalidOperation` to the `from decimal import …` line. (Empty-string still raises `ValueError`
before the parse, unchanged.)

### `src/khata/services/holdings.py`
In `_add_entry`, before the `<= 0` checks:
```python
    if quantity_micro is None or amount_minor is None:
        raise ValidationError("quantity and amount are required")
```
Then `add_sell`'s oversell guard simplifies to `if quantity_micro > _qty_held_micro(plan):` (the None
case is already handled).

### `src/khata/static/holding-detail.html`
`fmtMicro(q)` → return `"—"` when `q == null || q === undefined` (mirror `fmtMinor`).

## Testing (TDD)
- `test_money.py` (extend) — `to_minor("abc","INR")` / `to_micro("abc")` / `pct_to_bps("abc")` each raise
  **`ValueError`** (not `InvalidOperation`); valid input still works.
- `test_plans_api.py` (or holdings/chits api) — a malformed amount on a real money endpoint (e.g. asset
  payment `amount:"abc"`, holding buy `amount:"x"`) returns **400** (was 500). At least one endpoint test.
- `test_holding_service.py` (extend) — `None` quantity → `ValidationError`; sell-to-zero then state;
  multiple sells; `quote=0` → `current_value_minor == 0` (not None), `unrealized_gain` computed.
- `test_web.py` — unchanged (the fmtMicro guard is JS; assert the page still serves 200 — already covered).

## Migration & wiring
None — pure code hardening.

## Boundaries
`money.py` parse hardening is the load-bearing fix (one change, app-wide effect). Holdings + frontend
guards are local. All verified by tests + a real 400-not-500 check.
