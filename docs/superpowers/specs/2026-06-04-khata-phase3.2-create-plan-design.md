# Khata Phase 3 · Plan 3.2 — Create-Plan Flow Design Spec

**Status:** Approved (autonomous) 2026-06-04. Frontend-only. Makes the app shell's "New plan" button live.

## Goal
A real `/create` page: pick a plan **type** (asset · loan · holding), fill type-specific fields, submit
→ `POST /api/plans` → redirect to `/app`. Wires the create surface for every existing domain.

## Decisions (autonomous)
- **One page, type tabs.** Three tabs (Asset / Loan / Holding) reveal the relevant field group; a single
  submit posts the matching JSON shape. Matches the existing `POST /api/plans` type-dispatch.
- **Asset installments** are optional in 3.2: a minimal repeatable "amount + due date" row builder
  (add/remove rows). Empty → plain asset.
- **Money/qty/rate inputs are human strings** (server parses via `to_minor`/`to_micro`/`pct_to_bps`);
  the page does no float math. Errors from the API (`{error, detail}`) shown inline via `textContent`.
- **Auth guard** client-side (`GET /api/auth/me`, 401→`/`). On success redirect to `/app` (per-plan
  detail pages arrive in 3.3–3.5; deep-linking to them is a later enhancement).
- On `ledger.css` + the app-shell chrome (reuse the sidebar/topbar shell so create feels in-app).

## Field groups (match the create API exactly)
- **Asset:** `name`, `currency` (INR/USD), `total_price` (string), optional installments
  `[{amount, due_date?}]` → `{name, currency, total_price, installments?}`.
- **Loan:** `name`, `currency`, `direction` (given/taken), `counterparty?`, `interest_type`
  (none/monthly/yearly), `rate?` (percent string, shown only when interest_type≠none), `start_date`
  (date), `tenure_months?` → `{type:"loan", …}`.
- **Holding:** `name`, `currency`, `asset_class` (gold/silver/equity/mf/cash/other), `unit`
  (gram/share/unit), `symbol?`, `purity?` → `{type:"holding", …}`.

## Components
- `web.py`: add `/create` → `create-plan.html`.
- `static/create-plan.html`: the form page (shell chrome + tabbed form + submit).
- JS: auth guard → tab switch → build the right payload → `POST /api/plans` → on `ok` redirect `/app`,
  else show `detail`/`error` inline. XSS-safe (no user data via innerHTML; the form is static markup).

## Testing (TDD)
- `tests/test_web.py` (extend): `GET /create` → 200 and body contains `/api/plans`, the three type
  labels (`Asset`, `Loan`, `Holding`), `ledger.css`.
- Smoke (plan task): `GET /create` 200; create one of each type via the same payloads the page posts;
  confirm `/api/plans` then lists 3.

## Out of scope
Per-plan detail redirect targets (3.3–3.5) · editing/deleting plans · rich installment validation UI.

## Boundaries
Depends only on `POST /api/plans` (+ `/api/auth/me`) and `ledger.css`. No backend changes.
