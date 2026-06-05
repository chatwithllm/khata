# Khata Phase 3 · Plan 3.4 — Loan Detail Design Spec

**Status:** Approved (autonomous) 2026-06-04. Frontend-only.

## Goal
A loan-plan detail page at `/loan/<id>`: principal/interest/total cards, the derived monthly-interest
schedule, and an action modal to add a disbursement or log an interest/principal payment.

## Decisions (autonomous)
- **Route:** `/loan/<int:plan_id>` → static `loan-detail.html`; id from `location.pathname`; auth guard
  (401→`/`); non-loan → `/app`.
- **Read contract (K5-confirmed):** `GET /api/plans/<id>` → `{plan:{…,direction,interest_type,rate_bps,
  counterparty}, state:{direction, currency, principal_outstanding_minor, interest_accrued_minor,
  interest_paid_minor, interest_due_minor, total_minor, as_of, schedule:[{month_index,period_start,
  expected_minor,applied_minor,status}], next_due_month, months_behind}}`.
- **Actions:** one modal with a **type** select →
  - *Disbursement* → `POST /api/plans/<id>/loan/disbursements` `{amount, note?}`.
  - *Interest payment* → `POST /api/plans/<id>/loan/entries` `{kind:"interest_payment", amount, method?}`.
  - *Principal repayment* → `POST …/loan/entries` `{kind:"principal_repayment", amount, method?}`.
  The method select (values from `METHODS={cash,upi,transfer,cheque}`) shows only for the two entry
  kinds. These are **owner-only** endpoints — a member sees a clean 403 surfaced inline.
- XSS-safe DOM; money via shared `fmtMinor`. `months_behind`/`next_due_month` shown as a status line.

## Components
- `web.py`: `/loan/<int:plan_id>` → `loan-detail.html`.
- `static/loan-detail.html`: header (name, direction, counterparty, rate), cards (principal
  outstanding · interest due · total owed), schedule table, the action modal.

## Testing (TDD)
- `tests/test_web.py`: `GET /loan/1` → 200, body has `/api/plans`, `/loan/disbursements`, `/loan/entries`,
  `ledger.css`.
- Done-gate: boot app, register, create a monthly-interest loan, add a disbursement, GET `/api/plans/1`,
  confirm `principal_outstanding_minor` reflects it.

## Out of scope
Editing/deleting entries · as-of date picker. Loan dropdown enums mirror service sets (K5 enum rule).

## Boundaries
`GET /api/plans/<id>` + `/loan/disbursements` + `/loan/entries` + `/api/auth/me` + `ledger.css`. No backend changes.
