# Khata Phase 4 · Plan 4.2 — Secured Loans / Collateral Design Spec

**Status:** Approved (autonomous) 2026-06-05. Extends the loan domain. Backend + UI.

## Goal
Let a loan be **secured by a pledged holding** — track the collateral, derive its current value, and a
**loan-to-value (LTV)** ratio. Surfaced on the loan-detail page; net worth is already correct (the
holding is an asset, the loan a liability) so collateral is **informational, never double-counted**.

## Decisions (recommended, locked)
- **Collateral = an existing holding plan** the user owns (e.g. the Gold 22K holding backs a gold loan).
  A loan links to at most one collateral holding. Same-currency required (v1) so LTV is unit-clean.
- **LTV** = `principal_outstanding / collateral_current_value` (derived, %). Computed only when the
  collateral is **quoted** (has a current value); else `null` with the value shown as unpriced.
- Collateral is set/changed/unlinked from the **loan-detail page** (where the user can see their
  holdings), not at create time (the create form has no holdings list). The create API still *accepts*
  optional collateral for completeness.

## Data model
- **`loans`** table: ADD `secured` (Boolean, NOT NULL, server_default false) + `collateral_plan_id`
  (Integer, FK→plans.id, nullable). One Alembic revision (batch mode; nullable add + boolean default).
- No new table. Collateral is a reference to a `holding` plan.

## Service (`src/khata/services/loans.py`)
- `create_loan_plan(...)` gains optional `secured=False`, `collateral_plan_id=None` (validated via
  `set_collateral` if provided).
- **`set_collateral(session, *, plan, collateral_plan_id) -> Loan`** — `collateral_plan_id=None`
  unlinks (`secured=False`, `collateral_plan_id=None`). Otherwise validates: the target plan exists, is
  `type='holding'`, is owned by the loan's owner, and has the **same currency** as the loan; then sets
  `secured=True`, `collateral_plan_id=…`. Raises `ValidationError` (`LoanError`) on any failure.
- **`loan_state(...)`** gains collateral fields. When `loan.collateral_plan_id` is set: look up the
  holding plan, compute `holdings.holding_state(session, h.holding)`, and add
  `collateral: {plan_id, name, asset_class, currency, value_minor (current_value_minor, may be null),
  ltv_pct (round(principal_outstanding*100/value) if value else null)}`. Add `secured` (bool) at the top
  level. When unsecured: `secured=False`, `collateral=None`. (Cross-service: `loans.py` imports
  `holdings` — one-directional, fine.)

## API (`src/khata/api/plans.py`)
- `POST /api/plans` loan create accepts optional `secured` + `collateral_plan_id`.
- **`POST /api/plans/<id>/loan/collateral`** `{collateral_plan_id}` (null to unlink) — owner-only;
  `set_collateral` → 200 `{state}`. Errors → 400.
- `loan_state` (already surfaced by `GET /api/plans/<id>`) now includes `secured` + `collateral`.
- `_summary` loan adds `secured`.

## Frontend (`loan-detail.html`)
- A **Collateral** section: when secured, show the pledged holding (name · asset_class · current value ·
  **LTV %** with a colored badge — green < 60%, amber 60–80%, red > 80%) + an "Unpledge" link. When
  unsecured, a "Pledge collateral" button → modal that `GET /api/plans` (filter `type==holding` &&
  same currency), lists them, and on pick `POST /loan/collateral {collateral_plan_id}` → reload.
- All DOM via createElement (K4).

## Testing (TDD)
- `test_loan_models.py` (extend) — `secured`/`collateral_plan_id` persist.
- `test_loan_service.py` (extend) — `set_collateral` links a same-currency holding; rejects non-holding,
  cross-owner, cross-currency; unlink resets; `loan_state` collateral value + LTV math (e.g. principal
  ₹6,00,000 vs collateral value ₹10,00,000 → LTV 60%); unquoted collateral → ltv null.
- `test_loans_api.py` (extend) — create secured loan; `/loan/collateral` link/unlink; auth/ownership;
  `loan_state` surfaces collateral.
- `test_web.py` — `/loan/1` still 200 + has `/loan/collateral`.

## Migration & wiring
One revision: `loans.secured` + `loans.collateral_plan_id` (`down_revision` = chits head
`dacfeed37679`). No `models/__init__` change (Loan already registered). `loans.py` imports `holdings`.

## Out of scope
Cross-currency collateral (require same currency v1) · multiple collateral items · auto-margin-call
alerts · collateral on asset/chit plans.

## Boundaries
`holdings.holding_state` (valuation) ← `loans.loan_state` (LTV) ← `api/plans.py`. LTV is a pure derived
ratio; collateral validation lives in `set_collateral`.
