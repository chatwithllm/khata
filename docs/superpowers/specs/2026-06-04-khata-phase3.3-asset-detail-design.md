# Khata Phase 3 · Plan 3.3 — Asset Detail + Log-Payment Design Spec

**Status:** Approved (autonomous) 2026-06-04. Frontend-only.

## Goal
A real asset-plan detail page at `/asset/<id>`: total/paid/remaining cards, the installment schedule
(roll-forward status), funding breakdown, contributors, and a **log-payment** modal that posts to
`/api/plans/<id>/payments` and re-renders. Make the app shell's asset rows clickable.

## Decisions (autonomous)
- **Route:** `/asset/<int:plan_id>` → serves static `asset-detail.html`; JS reads the id from
  `location.pathname`. Auth guard (401→`/`); if the plan isn't type `asset`, redirect to `/app`.
- **Read contract (K5-confirmed):** `GET /api/plans/<id>` → `{plan:{id,type,name,currency,status,
  total_price_minor}, state:{total_price_minor, paid_to_date_minor, remaining_minor, overpaid_minor,
  next_due_seq, installments:[{seq,planned_amount_minor,applied_minor,status}],
  funding_breakdown:[{source,amount_minor,pct}], contributors:[{user_id,display_name,paid_minor,pct}]}}`.
- **Log payment:** modal with `amount`, `method`, `funding_source` (+ optional note) → `POST
  /api/plans/<id>/payments`; on ok close + re-fetch. Members can pay (the endpoint is owner-or-member).
- **Set-installments** (editing the schedule later) is out of 3.3 — the create flow already builds it.
- XSS-safe DOM throughout; money via the shared `fmtMinor`.
- App shell: `app.html` plan rows become clickable links by type (`/asset/<id>` now; `/loan/<id>` +
  `/holding/<id>` land in 3.4/3.5 — all three exist by the end of the Phase-3 branch).

## Components
- `web.py`: `/asset/<int:plan_id>` → `asset-detail.html`.
- `static/asset-detail.html`: header (name/status/currency), 3 stat cards (total/paid/remaining),
  installment schedule table (seq · planned · applied · status badge), funding breakdown bars,
  contributors list, "Log payment" button → modal.
- `app.html`: row → `<a href="/asset|loan|holding/<id>">` by `p.type`.

## Testing (TDD)
- `tests/test_web.py`: `GET /asset/1` → 200, body has `/api/plans`, `/payments`, `Log payment`,
  `ledger.css`. (The route serves the static page regardless of whether plan 1 exists; data loads client-side.)
- Done-gate (plan task): boot app, register, create an asset with an installment, log a payment via the
  page's payload, confirm `GET /api/plans/1` shows the payment in `paid_to_date_minor` + schedule.

## Out of scope
Editing the schedule · deleting payments · the loan/holding detail pages (3.4/3.5).

## Boundaries
Depends on `GET /api/plans/<id>` + `POST /api/plans/<id>/payments` + `/api/auth/me` + `ledger.css`. No
backend changes.
