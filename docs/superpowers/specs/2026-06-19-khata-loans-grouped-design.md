# Loans grouped by contact + Sankey breakdown

**Date:** 2026-06-19
**Branch:** `feat/loans-grouped`
**Status:** approved design

## Problem

The Loans page lists every loan and groups them only by **Borrowed / Lent out**. When you
lend to the same person across many loans (the user has several to "Sunil Manohar",
"Srikanth Yerra"), there's no one-glance per-person rollup, and no visual of where the
money sits. You want, per contact: total principal, expected monthly interest, next-month
due — plus a chart showing the breakdown.

## Goal

On `/app?type=loan`:
1. A **grouping toggle**: *By direction* (today's view, default) ↔ *By contact* (new).
2. **By contact** mode: contact-first groups (given/taken split inside), each with a
   one-glance summary — **principal**, **expected interest** (monthly), **next-month due**.
3. A **Sankey chart** of the loan book: Direction → Contact → Loan, weighted by outstanding.

## Decisions (locked in brainstorming)

- **Grouping:** contact-first, then given/taken within each group.
- **Group key:** the linked contact's name (`contact_id`) if set, else the loan's
  `counterparty` text; **same names merge** (case-insensitive, trimmed). Neither → "Unlabeled".
- **Per-group figures:** principal (outstanding), expected interest (monthly accrual),
  next-month due (= next month's interest). Computed **distinctly** (they coincide for
  interest-only loans but differ for amortizing ones).
- **Chart:** **Sankey**, Direction → Contact → Loan, link width = outstanding, base currency.
  Hand-rolled SVG (no chart library). Included now (not deferred).

## Architecture

The money aggregation lives in a **backend endpoint** (so it's unit-testable); the frontend
renders. No new tables, no migration.

### 1. Service — `services/loan_groups.py` (new)

`grouped_loans(session, *, owner_id, base_currency, as_of=None) -> dict`:

- Gather the owner's loan plans (owner-scoped). For each, compute `loan_state` once and read
  `direction`, `currency`, `principal_outstanding_minor`, the **monthly interest** (next
  month's accrual = `outstanding × monthly_rate`, reuse the loan's rate math), and the loan's
  `contact_id` / `counterparty`.
- **Group key:** `contact_id` → resolve to the contact's `name`; else `counterparty` (trimmed);
  merge by a normalized key `lower(strip(name))`. A group carries `{key, name, contact_id?}`
  (contact_id present only when every loan in the group shares one linked contact).
- Per group, split **given** vs **taken**; each side aggregates, in **base currency** (FX via
  `fx`), `{count, principal_minor, interest_monthly_minor, next_due_minor}` plus a per-loan
  list `[{plan_id, name, direction, currency, outstanding_minor, interest_monthly_minor}]`.
  `next_due_minor == interest_monthly_minor` for interest-only loans; kept as its own field.
- A `base_total` across all groups (lent vs borrowed). A `partial` flag when any currency
  lacked an FX rate (bucket contributed 0), mirroring the contacts rollup.
- **Sankey structure** `{nodes:[{id,label,kind}], links:[{source,target,value_minor}]}`:
  - nodes: two direction nodes (`Lent`, `Borrowed`), one per group (contact), one per loan;
  - links: Direction→Contact (sum of that contact's loans in that direction) and
    Contact→Loan (each loan's outstanding); **value = outstanding in base currency**.
  - Invariant (tested): for every contact node, Σ incoming (from directions) == Σ outgoing
    (to its loans).

### 2. API — `GET /api/plans/loans/grouped` (in `api/plans.py`, owner-only)

`current_user()` → returns `grouped_loans(g.db, owner_id=user.id, base_currency=<user base>)`
as JSON. Read-only. (Base currency from the user's `base_currency`, default INR.)

### 3. Frontend — `static/app.html` (loan view)

- A small **segmented toggle** at the top of the Loans card: `By direction` | `By contact`.
  Default *By direction* (unchanged behaviour). Choice persists in `localStorage`.
- **By contact** mode fetches `/api/plans/loans/grouped` and renders:
  - The **Sankey** in a panel above the list (see §4).
  - Collapsible **contact groups** (sorted by total outstanding desc). Group header: name
    (→ `/contacts/<id>` link when `contact_id`), and the three figures (principal · interest/mo
    · next-month due) with lent(+)/borrowed(−) signing. Inside: a *Lent* and/or *Borrowed*
    subsection listing each loan (native amount + → to `/loan/<id>`).
- *By direction* mode keeps today's exact rendering (no regression).

### 4. Sankey rendering (hand-rolled SVG, `app.html`)

- Three+ columns: Direction (2 nodes) → Contact (N) → Loan (M). Node height ∝ its total
  base-currency outstanding; links are quadratic-bezier ribbons with width ∝ `value_minor`.
- Ink/ivory palette; lent = green family, borrowed = red family. Hover a link/node → tooltip
  with the ₹ amount. Click a contact node → scroll to its group.
- Guard rails: if there are 0 loans, hide the chart. On very small screens or
  `prefers-reduced-motion`, fall back to a compact stacked-bar list (outstanding per contact,
  lent/borrowed split) — same data, simpler SVG.
- All text escaped; values formatted with the page's existing money helpers.

## Multi-currency

Group totals and Sankey weights are in **base currency** (FX-converted, matching the existing
loans list). Each loan row still shows its **native** amount. The `partial` flag surfaces when
a rate is missing.

## Testing

Service (`tests/test_loan_groups.py`):
- group by linked contact; fallback to counterparty text; **same-name merge** (a contact
  "Sunil" + an unlinked loan with counterparty "sunil" land in one group).
- given/taken split + per-side sums (principal, interest_monthly, next_due) correct.
- multi-currency: INR + USD loans for one contact → base-currency totals via a seeded rate;
  `partial` true when a rate is missing.
- `next_due_minor == interest_monthly_minor` for interest-only; both present.
- **Sankey invariant:** per contact node, Σ Direction→Contact == Σ Contact→Loan == that
  contact's outstanding; total of Direction→Contact links == base_total outstanding.
- owner scoping (only the caller's loans).

API (`tests/test_loan_groups_api.py`): owner-only; shape (`groups`, `base_total`, `sankey`);
non-owner/unauth guarded; empty (no loans) → empty groups + empty sankey.

UI: headless verify the By-contact toggle renders groups + Sankey with 0 JS throws, the
three per-group figures show, By-direction mode unchanged, per `/build-screen`.

## Out of scope

- Grouping for non-loan plans.
- Editing/assigning contacts from this view (use the loan detail picker).
- Animated/transitioning Sankey; interactivity beyond hover + click-to-scroll.
- Persisting the chart as an image/export.

## Docs

Update `docs/specs/khata-AS-BUILT.md` (§9 + change log; note the new read-only
`/api/plans/loans/grouped` endpoint) in the same commit as the implementation.
