# Loan backfill — mark historical payments (paid / received)

**Date:** 2026-06-19
**Branch:** `feat/loan-backfill-payments`
**Status:** approved design

## Problem

Loans often pre-date Khata: money was lent (or borrowed) and payments were made
for months before the loan was ever entered. The loan detail screen shows those
months as `due` with a growing `running due`, "30 behind", "0% of accrued interest
paid" — there is no quick way to record that those past months were in fact settled.

A single backdated payment is already possible via the existing **Add entry** form
(`loan-detail.html:184,190` → `POST /loan/entries`). The gap is the *friction* of
backfilling many months one-by-one, and wanting it framed as "this month's due →
received/paid" directly on the schedule.

## Goal

Two ways to clear historical interest dues on a loan:

1. **Individual** — a per-month "Mark received / Mark paid" action on each past,
   unpaid schedule row.
2. **Bulk** — "Mark paid through Month N / a date" — clears every unmarked month up
   to a chosen cutoff in one action.

## How the existing model works (constraints we build on)

In `loans.py :: loan_state` (`loans.py:373–417`):

- `interest_paid` = **sum of all `interest_payment` ledger entries** — a single pool.
- The pool is applied **greedily, oldest month first**. Each schedule row's
  `status` (`paid` / `partial` / `due`) is **derived** from the pool, not stored.
- `principal_repayment` entries dated within a month lower that month's opening
  balance, so they reduce **later** months' accrued interest.
- Schedule rows: `{month_index, period_start, expected_minor, applied_minor, status}`.
- `log_loan_entry(session, *, plan, user_id, kind, amount_minor, occurred_at, ...)`
  already records `interest_payment` / `principal_repayment` with a backdatable
  `occurred_at`, and sets `direction` via `_direction_for(loan.direction, kind)`.

**Implication:** "mark a month paid" = add a backdated `interest_payment` entry
(+ optional `principal_repayment`) dated in that month. **No new table / migration.**

## Approach (A — per-month backdated entries)

### Backend

**Individual** — no backend change. The existing `POST /plans/<id>/loan/entries`
(`log_loan_entry`) already records a backdated `interest_payment` /
`principal_repayment`. The work is purely a UI quick-action that prefills it.

**Bulk** — new service + endpoint:

- `loans.backfill_loan_interest(session, *, plan, user_id, through_month=None, through_date=None) -> dict`
  - Compute current `loan_state`.
  - Resolve the cutoff: `through_month` (a `month_index`) **or** `through_date`
    (clamped to the latest `period_start` ≤ that date). Exactly one is required.
  - For each schedule row with `status in {due, partial}` and `month_index ≤ cutoff`:
    create an `interest_payment` of `remaining = expected_minor − applied_minor`,
    `occurred_at = period_start @ 12:00`, `note = "Backfill — Month {N} interest"`.
  - **Idempotent:** `paid` months have `remaining == 0` → skipped; re-running adds 0.
  - Returns `{"count": int, "total_minor": int}`.
- `POST /plans/<id>/loan/backfill` — body `{"through_month": N}` **or**
  `{"through_date": "YYYY-MM-DD"}`. Owner-only (mirrors the guard on other loan
  mutations in `api/plans.py`). Validation: loan plan, interest-bearing, exactly one
  cutoff field, cutoff not in the future. Returns the refreshed loan state (so the UI
  re-renders in one round-trip) plus the `{count, total_minor}` summary.

### Frontend (`static/loan-detail.html`)

- **Direction wording:** lent (`direction == "given"`) → "received"; borrowed
  (`"taken"`) → "paid". Reuse the existing `interestWord(st.direction)` helper.
- **Per-row action:** each schedule row that is **past** (`period_start ≤ today`)
  and `status != "paid"` gets a small `Mark received` / `Mark paid` button. Click
  opens a compact prefilled form:
  - interest amount = `remaining` (`expected − applied`), editable;
  - optional principal amount (blank by default);
  - date = `period_start`, editable.
  - Confirm → `POST /loan/entries` (`interest_payment`); if principal > 0, a second
    `POST` (`principal_repayment`). Then refresh state.
- **Bulk control:** above the schedule, a "Mark paid through …" control with a month
  selector (and/or date). On submit, a confirm dialog shows the impact
  (`N months · ₹total`), then `POST /loan/backfill`. Refresh state from the response.
- Interest-free loans (no schedule rows) show neither control.

## Edge cases

- **Interest-free loan** (`monthly_rate == 0`): no schedule rows → no buttons, no bulk.
- **Future / not-yet-accrued months:** no per-row button; bulk cutoff cannot be in
  the future.
- **Partial month:** top up only the `remaining`, never double-count.
- **Bulk re-run:** idempotent — already-`paid` months contribute 0.
- **Multi-currency:** entries recorded in `plan.currency` (loan's own currency).
- **Optional principal** dated in a month correctly lowers later months' accrual —
  this is desired behavior, not a bug.
- **Greedy-pool wrinkle (accepted):** because `interest_paid` applies oldest-first,
  individual marking effectively clears the oldest outstanding month. Natural for
  backfilling from the start; totals always reconcile even if marked out of order.

## Testing

Unit (`tests/`, pytest — matches existing loan tests):

- Loan lent, 5 complete months elapsed, no payments → `backfill_loan_interest(through_month=4)`
  creates 5 `interest_payment` entries; `loan_state` then reports `months_behind == 0`,
  `interest_paid == interest_accrued`, each entry dated at its `period_start`.
- **Idempotent:** immediate re-run returns `count == 0`, no new entries.
- **Partial top-up:** a month with a pre-existing partial `interest_payment` is topped
  up to exactly `expected` (one new entry of the remainder).
- **Cutoff respected:** `through_month=2` clears only months 0–2; months 3–4 stay `due`.
- **`through_date`** resolves to the right cutoff month.
- **Principal effect:** a `principal_repayment` dated in month 1 lowers month 2+ `expected`.
- **API:** non-owner gets the standard forbidden response; future cutoff rejected;
  missing/both cutoff fields rejected.

UI: headless jsdom verify per the `/build-screen` protocol before marking the screen
done (per project `CLAUDE.md` and `record-changes-in-asbuilt-doc`).

## Out of scope

- No new per-month "paid" model/table (approach C) — the pool model is sufficient.
- No change to how interest accrues or how `interest_paid` is summed.
- No bulk **principal** backfill (principal stays the optional per-row field / existing
  Add-entry form).

## Docs

Update `docs/specs/khata-AS-BUILT.md` (§9 enhancements + change log) in the same commit
as the implementation, per the project rule.
