# Loan running-total pending interest — Design

**Date:** 2026-06-12
**Status:** Approved

## Problem

A loan accrues interest every month. The loan-detail repayment schedule shows the
interest **expected** each month (`₹3,600`) but never the **running total** — so you
can't read "by month 26, how much interest is pending, and what's the total owed
(principal + that pending interest)". The dashboard loans list has the same gap: it
shows interest/mo and principal outstanding, but not total accrued-unpaid interest or
total owed per loan.

## Decision

Show a cumulative **unpaid** (net of payments) running total of pending interest, plus a
principal+pending "total owed", on two surfaces:

1. The loan-detail repayment schedule — per month.
2. The dashboard loans list — per loan, with section running totals.

"Pending" = cumulative `Σ(interest accrued − interest paid)` through that point. It drops
when interest payments are logged. Equal to gross accrued when nothing has been paid.

## Part 1 — `src/khata/services/loans.py` `loan_state`

The schedule loop already computes, per month `m`:
- `expected_minor` — interest accrued that month (`opening × monthly_rate`, ROUND_HALF_UP),
- `applied_minor` — interest payment applied to that month (front-loaded from the paid pool),
- `opening` — principal outstanding at the month's start.

Add three integer-minor fields to each schedule row:
- `cum_due_minor` — running `Σ(expected_minor − applied_minor)` through this row. Monotonic
  in gross terms; reflects payments via `applied_minor`. All integer minor units — exact,
  no float, no rounding drift.
- `principal_minor` — the month's `opening` principal (max(0, …), already computed).
- `total_owed_minor` — `principal_minor + cum_due_minor`.

No new model, migration, or endpoint. Computed inside the existing schedule loop (a second
pass after `applied_minor` is known, or accumulated in the same `for row in schedule` loop
that sets status — that loop already walks rows in order and knows `applied`).

## Part 2 — `src/khata/static/loan-detail.html` repayment schedule

Each month row currently renders `expected ₹3,600` on the right (the `pl` element in the
schedule render, ~line 614). Add a second muted line beneath it:

`running due ₹7,200 · owed ₹1,27,200`

from `it.cum_due_minor` and `it.total_owed_minor`. textContent only (K4). Existing
height-cap / scroll-past-7-rows behavior unchanged. When `cum_due_minor` is 0 (interest
fully paid through that month) the line still renders honestly (`running due ₹0`).

## Part 3 — `src/khata/static/app.html` dashboard loans list

No backend change — each loan row already fetches `st` (`/api/plans/<id>`), which carries
`interest_due_minor` (total accrued-unpaid interest) and `total_minor` (principal
outstanding + interest due = total owed).

- Per loan row: add a sub-caption line under the existing caption:
  `pending int ₹93,600 · owed ₹2,13,600` from `st.interest_due_minor` / `st.total_minor`.
  Lives in the caption area (not a new column) so the existing mobile column-drop CSS
  (the interest/mo column hides on phones) keeps the row uncluttered.
- Section footers (BORROWED / LENT OUT `groupHeader`): accumulate `interest_due_minor` and
  `total_minor` per loan into the group aggregate, **converted to base currency** via the
  existing `toBase(...)` pattern (the `groupAgg.sum` / `groupAgg.interest` accumulation at
  ~line 819), and render the running totals in the footer next to the existing subtotals.
  Cross-currency sums must go through base — never a raw minor-unit sum across currencies.

Labels neutral for direction: a lent loan's "pending int / owed" is owed *to* the user; a
borrowed loan's is owed *by* the user. Same math, same caption — the BORROWED / LENT OUT
section header already states the direction.

## Tests

`tests/test_loans.py`:
- Schedule rows carry `cum_due_minor` monotonically non-decreasing across months when no
  interest is paid; `total_owed_minor == principal_minor + cum_due_minor` for every row.
- After logging an interest payment, later rows' `cum_due_minor` is lower than the
  no-payment case (payment reduces pending).
- A fully-paid-through month shows `cum_due_minor == 0` at that row.

UI: headless verification — schedule second line present and wired on loan-detail; dashboard
loan rows show the pending/owed caption and the section footers show running totals.

## Docs

`docs/specs/khata-AS-BUILT.md`: §9 loan-state/schedule fields + change-log entry, same
commits as the code.

## Out of scope

- Changing how interest accrues or how payments are applied (front-loaded pool unchanged).
- Projecting *future* pending interest past `as_of` (schedule is accrued-to-date only).
- Running totals on chit / asset / retirement surfaces.
