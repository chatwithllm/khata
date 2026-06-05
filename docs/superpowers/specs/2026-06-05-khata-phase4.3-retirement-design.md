# Khata Phase 4 · Plan 4.3 — Retirement / 401(k) Planner Design Spec

**Status:** Approved (autonomous) 2026-06-05. New `retirement` plan type — a forward-looking projection
planner. Backend + UI.

## Goal
Project a retirement corpus: starting balance + monthly contributions (with employer match) compounding
at an assumed return until retirement age, reported **nominal** and in **today's money** (inflation-
discounted). A planner, not a transaction log — all derived, no float.

## Decisions (recommended, locked)
- **Pure projection planner.** The retirement plan stores the inputs (current balance + assumptions);
  `retirement_state` derives the projected corpus on each read. The user updates `current_balance` as
  their real 401(k)/NPS balance moves (like a holding quote). No per-contribution ledger in v1 — keeps
  it a clean compound-growth calculator.
- **Assumptions are editable** by the user (annual return %, inflation %, employer match %, monthly
  contribution, ages). Defaults suggested in the UI (return 8%, inflation 6%, match 0).
- **Compound math, monthly, with `Decimal`** (`Decimal ** int` for the growth factor — exact, no float,
  no roots). Nominal monthly rate = annual/12.

## Data model
- Reuse **`plans`** (`type='retirement'`).
- New **`retirements`** detail table: `plan_id` (PK, FK→plans CASCADE), `current_balance_minor`
  (BigInteger, default 0), `monthly_contribution_minor` (BigInteger, default 0), `employer_match_bps`
  (Integer, default 0), `annual_return_bps` (Integer, default 800), `inflation_bps` (Integer, default 600),
  `current_age` (Integer), `retirement_age` (Integer).
- `Plan` gains a `retirement` relationship (1:1, cascade delete-orphan). No ledger kinds.

## Derived projection (`services/retirement.py:retirement_state(session, retirement)`)
Pure; nothing stored. Let `r = retirement`. All `Decimal`; `_round` = ROUND_HALF_UP.
- `n` (months) = `max(0, (retirement_age − current_age)) × 12`.
- `monthly_rate` = `Decimal(annual_return_bps) / 120000` (= annual%/100/12).
- `infl_monthly` = `Decimal(inflation_bps) / 120000`.
- `eff_contrib` = `Decimal(monthly_contribution_minor) × (1 + Decimal(employer_match_bps)/10000)`
  (your contribution + employer match).
- `g = 1 + monthly_rate`; `gn = g ** n`.
- `fv_current` = `Decimal(current_balance_minor) × gn`.
- `annuity_factor` = `(gn − 1) / monthly_rate` if `monthly_rate > 0` else `Decimal(n)` (ordinary
  annuity, end-of-month).
- `fv_contrib` = `eff_contrib × annuity_factor`.
- `projected_corpus_minor` = `_round(fv_current + fv_contrib)`.
- `infl_factor` = `(1 + infl_monthly) ** n`; `projected_corpus_real_minor` =
  `_round((fv_current + fv_contrib) / infl_factor)` (today's purchasing power).
- `effective_monthly_minor` = `_round(eff_contrib)`; `total_contributions_minor` =
  `_round(eff_contrib × n)` (principal you'll put in, employer-matched).
Returns `{currency, current_balance_minor, monthly_contribution_minor, employer_match_bps,
annual_return_bps, inflation_bps, current_age, retirement_age, months_to_retirement,
effective_monthly_minor, total_contributions_minor, projected_corpus_minor,
projected_corpus_real_minor}`.

**Worked example (for tests):** balance 0, contribution ₹10,000/mo (1000000 minor), match 0, return 8%,
inflation 0, age 30→60 (n=360). monthly_rate = 800/120000 = 0.00666…; gn = 1.0066̅^360 ≈ 10.9357;
annuity = (gn−1)/rate ≈ 1490.36; projected ≈ ₹1,49,03,xxx. (The test asserts the impl's exact integer;
the reviewer recomputes with the same Decimal precision.)

## Service (`src/khata/services/retirement.py`, pure)
- `create_retirement_plan(session, *, owner_id, name, currency, current_balance_minor=0,
  monthly_contribution_minor=0, employer_match_bps=0, annual_return_bps=800, inflation_bps=600,
  current_age, retirement_age) -> Plan` — validates currency, `retirement_age > current_age ≥ 0`,
  bps ≥ 0, amounts ≥ 0.
- `update_retirement(session, *, plan, **fields) -> Retirement` — set any of the settable fields
  (current_balance_minor, monthly_contribution_minor, employer_match_bps, annual_return_bps,
  inflation_bps, current_age, retirement_age) with the same validation; ignores unknown keys.
- `retirement_state(session, retirement) -> dict` (above).
Typed `RetirementError`/`ValidationError`.

## API (extend `/api/plans` dispatch)
- `POST /api/plans` `type='retirement'` `{name, currency, current_balance?, monthly_contribution?,
  employer_match?, annual_return?, inflation?, current_age, retirement_age}` → 201 `{plan, state}`.
  Percent fields (`employer_match`/`annual_return`/`inflation`) → bps via `pct_to_bps`; money via
  `to_minor`; ages via `int(...)`.
- `GET /api/plans/<id>` dispatch → `retirement_state`.
- `POST /api/plans/<id>/retirement/update` `{...same settable fields...}` (owner-only) → 200 `{state}`.
- `_summary` retirement adds `{retirement_age, projected_hint?}` (keep light: `current_age,
  retirement_age`).

## Frontend (`static/retirement-detail.html` at `/retirement/<id>`, + create tab)
- `retirement-detail.html`: hero cards — **Projected corpus** (nominal) · **In today's money** (real) ·
  **Years to retirement**; an assumptions line (balance · contribution+match · return% · inflation%); an
  **Update** modal (current balance, monthly contribution, employer match %, annual return %, inflation
  %, current age, retirement age) → `POST /retirement/update` → reload. `sharing.js`.
- `create-plan.html`: a **Retirement** tab (current_balance, monthly_contribution, employer_match %,
  annual_return %, inflation %, current_age, retirement_age).
- `app.html`: retirement filter chip + count; rows already link by type → `/retirement/<id>`.
- `web.py`: `/retirement/<int:plan_id>` → `retirement-detail.html`.

## Testing (TDD)
- `test_retirement_models.py` — Retirement persists; cascade.
- `test_retirement_service.py` — create + validation; `retirement_state` projection (the worked example;
  monthly_rate=0 fallback → annuity = n; match increases effective contribution; real < nominal when
  inflation>0; n=0 when already at retirement age → corpus = current_balance); `update_retirement`.
- `test_retirement_api.py` — create dispatch; `/retirement/update`; auth/ownership; other types still work.
- `test_web.py` — `/retirement/1` 200 + markers.

## Migration & wiring
One revision: `retirements` table (`down_revision` = the loan-collateral head). `models/__init__` imports
`Retirement`; `Plan.retirement`; api dispatch extends to asset|loan|holding|chit|retirement.

## Out of scope
Per-contribution ledger · tax modelling · variable return sequences · withdrawal/drawdown phase ·
real return via geometric (we discount nominal by inflation, the standard simple approach).

## Boundaries
`money` (pure) ← `services/retirement.py` (compound FV, Decimal**int) ← `api/plans.py` (dispatch). The
projection is independently testable with fixed inputs; the reviewer recomputes with matching Decimal
precision.
