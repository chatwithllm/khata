# Khata Phase 1 · Plan 2 — Plan + Ledger Core + Asset Purchase (Design Spec)

**Status:** Approved 2026-06-04. Builds on Plan 1 (auth + Flask/SQLAlchemy/Alembic foundation).

## Goal
Introduce the shared plan/ledger spine and the first concrete plan type — **Asset purchase** —
with an installment schedule, a money ledger, and **derived** roll-forward state, exposed over a
JSON API. One currency per plan. Test-first.

## Scope
**In:** asset-purchase plans, installment schedule (the original plan), money ledger entries
(method + funding source + timestamp + optional proof reference), derived balances and
roll-forward, owner-scoped JSON API, wiring into the app factory + Alembic migration.

**Out (later plans):** chit/loan plan types · contributors / ownership-share (Plan 4) ·
proof **file upload** + Attachment storage (separate plan — we keep a nullable `proof_ref`
string now) · cross-currency FX roll-up (holdings phase) · Google OAuth (Plan 5).

## Locked rules honored
- **Money = integer minor units** (`amount_minor`, BIGINT) + a `currency` code; never float. (rule #2)
- **Balances are derived, never stored** — roll-forward and totals are computed from ledger rows. (rule #3)
- **Original currency + amount immutable on a ledger entry**; the installment schedule is never
  mutated by payments (the original plan is preserved for comparison). (rule #4)

## Data model (Alembic migration — joined base + detail)
- **`plans`** (shared spine) — `id`, `owner_user_id`→`users`, `type` (`'asset'` now), `name`,
  `currency` (e.g. `'INR'`), `status` (`'active'`/`'closed'`), `created_at`.
- **`asset_purchases`** (detail) — `plan_id` (PK, FK→`plans`), `total_price_minor` (BIGINT).
- **`installments`** (ScheduleItem for assets — the original schedule) — `id`, `plan_id`→`plans`,
  `seq` (1..N), `planned_amount_minor` (BIGINT), `due_date` (date), `note` (nullable).
- **`ledger_entries`** (actual money movements) — `id`, `plan_id`→`plans`,
  `logged_by_user_id`→`users`, `direction` (`'out'`/`'in'`), `amount_minor` (BIGINT),
  `currency`, `occurred_at` (datetime, precise), `method` (`cash`/`upi`/`transfer`/`cheque`),
  `funding_source` (`savings`/`loan`/`borrowed`/`sold_asset`/`chit_payout`/`other`),
  `proof_ref` (nullable text), `note` (nullable), `created_at`.

Foreign keys cascade on plan delete. Indexes on `plans.owner_user_id`,
`installments.plan_id`, `ledger_entries.plan_id`.

## Money helper (`src/khata/money.py`)
Pure functions over integer minor units — no float, no Flask, no DB:
- `to_minor(text_or_decimal, currency) -> int` (parse "12,40,000" / "12.50" → minor units)
- `format_minor(amount_minor, currency) -> str` (group + symbol for display)
- minor-unit exponent per currency (INR/USD = 2). Used by services and API.

## Derived roll-forward (`src/khata/services/assets.py:asset_state`)
Pure function `asset_state(session, plan) -> dict`. Reads the installments and the plan's
`'out'` ledger entries (sorted by `occurred_at`), then:
1. `paid_to_date` = Σ out-entry `amount_minor`.
2. Walk installments in `seq` order, consuming the paid pool: each installment absorbs up to its
   `planned_amount_minor`; a shortfall leaves it `partial`/`due` and the deficit is **carried in**
   to the next; a surplus on the pool **rolls forward** to later installments.
3. Emit per-installment `{seq, planned, applied, carried_in, rolled_fwd, status}` where status ∈
   `paid | partial | due | upcoming`, plus top-level `{total_price, paid_to_date, remaining,
   installments[], next_due, funding_breakdown}`.
   `funding_breakdown` = paid amount grouped by `funding_source` (the mockup's funding-sources
   donut), each `{source, amount_minor, pct}`.

Only **`'out'`** entries (payments toward the asset, each tagged with a `funding_source`) count
toward `paid_to_date`, roll-forward, and the funding breakdown. The `'in'` direction exists for
generality but is **reserved for later cross-plan funding links** (e.g. a loan disbursement that
funds an asset payment) and does not affect asset roll-forward in this plan.

No carried/applied values are stored — recomputed each read from the immutable schedule + ledger.

## Services (pure, session-injected, no Flask)
`src/khata/services/assets.py`:
- `create_asset_plan(session, *, owner_id, name, currency, total_price_minor) -> Plan`
- `set_installments(session, *, plan, items)` — replace the schedule (list of {amount, due_date, note})
- `log_payment(session, *, plan, user_id, amount_minor, occurred_at, method, funding_source,
  direction='out', proof_ref=None, note=None) -> LedgerEntry`
- `asset_state(session, plan) -> dict`
- `list_plans(session, owner_id) -> list[Plan]`
Validation (amount > 0, known method/source, currency matches plan) raises typed errors
(`PlanError` hierarchy), mirroring the auth service style.

## API (`src/khata/api/plans.py`, blueprint `/api/plans`, auth-gated, owner-scoped)
All require a session user (else `401`); non-owner access → `403`.
- `POST /api/plans` → create asset plan `{name, currency, total_price, installments?}` → `201` + plan
- `GET  /api/plans` → `{plans: [summary...]}` for the current user
- `GET  /api/plans/<id>` → plan + `asset_state` (derived) → `200` / `404` / `403`
- `POST /api/plans/<id>/installments` → replace schedule → `200`
- `POST /api/plans/<id>/payments` → log payment `{amount, occurred_at, method, funding_source,
  proof_ref?, note?}` → `201` + the entry + refreshed `asset_state`

Amounts cross the API as human strings/decimals and are converted to minor units server-side via
`money.to_minor`; responses include both `amount_minor` and a formatted display string.

## Testing (TDD, pytest)
- `test_money.py` — parse/format round-trips, grouping, no-float invariants.
- `test_plan_models.py` — plans/asset_purchases/installments/ledger_entries persist; FKs.
- `test_asset_service.py` — create plan; set schedule; log payments; **roll-forward scenarios**:
  exact pay, short pay → carry-in to next, surplus → roll-forward, multiple payments across
  installments, fully-paid status. Asserts derived totals + per-installment states.
- `test_plans_api.py` — full flow (register → create plan → set schedule → log payment → get state);
  auth required (`401`); non-owner blocked (`403`); validation (`400`).

## Migration & wiring
- New Alembic autogenerated revision adds the four tables.
- Register the `plans` blueprint in the app factory.
- `models/__init__.py` imports the new models so Alembic + `create_all` see them.

## Component boundaries
`money.py` (pure math) ← `services/assets.py` (business logic, session-injected) ← `api/plans.py`
(HTTP + auth/ownership). Models are pure data. Each is unit-testable without the layer above.
