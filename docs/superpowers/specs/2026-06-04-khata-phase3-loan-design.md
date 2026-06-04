# Khata Phase 1 · Plan 3 — Loan (given/taken, unsecured) Design Spec

**Status:** Approved 2026-06-04. Builds on Plan 2 (plan/ledger spine + Asset purchase).

## Goal
Add a `loan` plan type — given or taken, with tranches (top-up disbursements), reducing-balance
**simple** interest, **bullet/interest-only** repayment, a principal-vs-interest ledger, and a
fully **derived** loan state + monthly-interest schedule — reusing the Plan-2 spine.

## Scope
**In:** `loans` detail table; direction given/taken; counterparty; interest none / per-month /
per-year on a reducing balance, simple (non-compounding); tranches as disbursement ledger rows;
interest & principal payments; derived `loan_state`; monthly-interest schedule; loan-aware
`/api/plans` (create + state dispatch by type) + loan entry endpoints.

**Out (later plans):** EMI amortization schedule · flat-rate basis · capitalize-compounding ·
per-tranche rates · collateral / secured loans (holdings phase) · net-worth roll-up (Plan 4).

## Locked rules honored
- **Money = integer minor units; rates = integer basis points** (no float anywhere). Interest is
  computed with `Decimal` (exact) and converted to integer minor units. (rule #2)
- **Balances derived, never stored** — principal outstanding, interest accrued/due, schedule are
  all computed from the ledger + loan terms each read. No materialized accrual rows. (rule #3)
- **Original currency + amount immutable on a ledger entry.** (rule #4)
- **One honest ledger** — loan movements are `ledger_entries` rows distinguished by `kind`, not a
  separate table.

## Data model
- Reuse **`plans`** (`type='loan'`).
- New **`loans`** detail table: `plan_id` (PK, FK→plans ON DELETE CASCADE), `direction`
  (`'given'`/`'taken'`), `counterparty` (text, nullable), `interest_type`
  (`'none'`/`'monthly'`/`'yearly'`), `rate_bps` (Integer, basis points; e.g. 2%/mo=200, 8.5%/yr=850),
  `basis` (text, default `'reducing'`), `repayment` (text, default `'bullet'`),
  `start_date` (date), `tenure_months` (Integer, nullable).
- Extend **`ledger_entries`** (Alembic migration, SQLite batch mode):
  - ADD `kind` (String(24), nullable) — values `'payment'` (asset), `'disbursement'`,
    `'interest_payment'`, `'principal_repayment'`.
  - ALTER `method` and `funding_source` to **nullable** (loan entries needn't carry a funding
    source). Asset payments keep `kind='payment'` + their method/source (the asset API still
    requires them).

`alembic/env.py` `context.configure(...)` gains `render_as_batch=True` so SQLite can ALTER the
columns to nullable (SQLite needs table-recreate batch mode).

## Direction wiring (service sets ledger `direction` from loan.direction + kind)
| loan.direction | disbursement | interest_payment | principal_repayment |
|---|---|---|---|
| `taken` (I borrowed) | `in` (money to me) | `out` | `out` |
| `given` (I lent) | `out` (money I lend) | `in` | `in` |

Loan math uses `kind` + `amount_minor` magnitudes only; `direction` is for cashflow display.

## Derived loan state (`src/khata/services/loans.py:loan_state(session, loan, as_of)`)
`as_of` is a `date` (API passes `date.today()`). Pure; nothing stored.

1. `principal_outstanding` = Σ(`disbursement`.amount) − Σ(`principal_repayment`.amount).
2. **Interest accrued** (reducing balance, simple, whole-month):
   - `n` = complete months from `start_date` to `as_of` =
     `(as_of.year-start.year)*12 + (as_of.month-start.month)`, minus 1 if `as_of.day < start_date.day`.
   - `monthly_rate` (Decimal) = `rate_bps/10000` (monthly) · `rate_bps/120000` (yearly) · `0` (none).
   - For each month `m` in `0..n-1` with period-start date `pm = start_date + m months`:
     `opening_principal_m` = Σ(disbursements dated ≤ pm) − Σ(principal_repayments dated ≤ pm);
     `expected_m` = `int((Decimal(opening_principal_m) * monthly_rate).quantize(1, ROUND_HALF_UP))`.
   - `interest_accrued` = Σ `expected_m`.
3. `interest_paid` = Σ(`interest_payment`.amount). `interest_due` = `max(0, accrued − paid)`.
4. `total_minor` = `principal_outstanding + interest_due` (a liability if `taken`, a receivable if `given`).
5. **Schedule** = the per-month list `{month_index, period_start, expected_minor, applied_minor,
   status}` where `interest_paid` is applied **greedily** across months in order (paid / partial /
   due), plus `next_due_month` (first non-paid index or null) and `months_behind` (# non-paid months).
   (Same fungible-greedy pattern as the asset roll-forward.)

Return `{direction, currency, principal_outstanding_minor, interest_accrued_minor,
interest_paid_minor, interest_due_minor, total_minor, as_of, schedule:[...], next_due_month,
months_behind}`. `interest_type='none'` ⇒ all interest fields 0 and an empty schedule.

A `month_add(date, n)` helper adds whole months with day clamping (e.g. Jan-31 + 1mo → Feb-28).

## Services (pure, session-injected, no Flask) — `src/khata/services/loans.py`
- `create_loan_plan(session, *, owner_id, name, currency, direction, counterparty, interest_type,
  rate_bps, start_date, tenure_months=None) -> Plan` — validates direction/interest_type/currency,
  `rate_bps ≥ 0`; creates `Plan(type='loan')` + `Loan` row.
- `add_disbursement(session, *, plan, user_id, amount_minor, occurred_at, note=None) -> LedgerEntry`
  — a tranche; `kind='disbursement'`, direction per table above.
- `log_loan_entry(session, *, plan, user_id, kind, amount_minor, occurred_at, method=None,
  note=None) -> LedgerEntry` — `kind ∈ {interest_payment, principal_repayment}`; validates amount>0.
- `loan_state(session, loan, as_of) -> dict`.
Typed errors `LoanError`/`ValidationError` (mirrors the asset service).

## API (extend `/api/plans`, auth-gated, owner-scoped)
- `POST /api/plans` — dispatch on `type`: `'asset'` (existing path) or `'loan'`
  `{name, currency, direction, counterparty?, interest_type, rate, start_date, tenure_months?}`.
  `interest_type` (`none`/`monthly`/`yearly`) sets the period; `rate` is a human percent string →
  `rate_bps` server-side (e.g. `"8.5"` → 850). `rate` is ignored when `interest_type='none'`.
  → 201 `{plan, state}`.
- `GET /api/plans/<id>` — dispatch `state` by `plan.type` (`asset_state` | `loan_state`).
- `POST /api/plans/<id>/loan/disbursements` — `{amount, occurred_at?, note?}` → 201 `{entry, state}`.
- `POST /api/plans/<id>/loan/entries` — `{kind: interest_payment|principal_repayment, amount,
  occurred_at?, method?, note?}` → 201 `{entry, state}`.
The Plan-2 create/detail logic is refactored into a small `type`-dispatch (a Plan-2 follow-up).
Loan `_summary` adds `{direction, interest_type, rate_bps}`.

## Money/rate helpers (`src/khata/money.py`)
Add `pct_to_bps(value) -> int` (parse `"8.5"`/`8.5` → 850, `ROUND_HALF_UP`, reject float-noise the
same way `to_minor` does) and `format_bps(bps) -> str` (`850` → `"8.5"`). Keep pure, no float.

## Testing (TDD, pytest)
- `test_money.py` (extend) — `pct_to_bps`/`format_bps` round-trips, rejects bad input.
- `test_loan_models.py` — `Loan` + `kind` on `ledger_entries` persist; method/funding_source nullable.
- `test_loan_service.py` — create loan; add tranche(s); log interest/principal payments; direction
  wiring (taken vs given); **interest math** scenarios: single tranche monthly, single tranche yearly,
  top-up tranche mid-term changes accrual, partial principal repayment reduces later accrual,
  `interest_type='none'` ⇒ zero, interest-paid greedy schedule (paid/partial/due + months_behind).
- `test_loans_api.py` — create-loan flow → disbursement → interest payment → state; dispatch on
  type (asset still works); auth (401) + ownership (403) on the new endpoints; validation (400).
- Full suite stays green (asset tests unaffected by the nullable change + new `kind` default).

## Migration & wiring
- One Alembic revision (batch mode): add `loans` table; add `ledger_entries.kind`; alter
  `method`/`funding_source` nullable.
- `models/__init__.py` imports `Loan`; register no new blueprint (endpoints extend the `plans` bp).
- `env.py`: `render_as_batch=True`.

## Component boundaries
`money.py` (pure, +rate helpers) ← `services/loans.py` (interest math + ledger writes, session-injected)
← `api/plans.py` (HTTP + auth/ownership + type dispatch). `loan_state` is independently testable with
a fixed `as_of`. Loan interest math lives only in `loans.py`.
