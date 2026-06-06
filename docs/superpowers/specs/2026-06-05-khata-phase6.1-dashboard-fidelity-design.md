# Khata Phase 6 · Plan 6.1 — Dashboard Fidelity Design Spec

**Status:** Approved (autonomous) 2026-06-05. Rebuild `/app` (`static/app.html`) to match
`docs/mockups/app.html` while wired to real APIs. Frontend-only.

## Goal
Make the real dashboard look like the editorial mockup — sidebar with icons + counts, rich topbar
(time greeting · active-plan count · INR/USD toggle · Log payment · avatar), hero stat cards with
sub-captions, and the `grid2` rich panels — populated with **live** data, XSS-safe, degrading gracefully
where the backend doesn't (yet) expose mockup-level detail.

## Approach (faithful port + live wiring)
- **Port the mockup's `<style>` and DOM structure essentially verbatim** (sidebar `.side`, topbar `.top`,
  `.stats`, `.grid2`, `.panel`, `.sched`, `.ledger`, `.posbox`, `.rounds`, `.liab`, etc.). This is the
  fidelity backbone.
- **Reuse the mockup's currency machinery:** the `.cv[data-inr]` + `.symword` spans + `apply()` /
  `renderCV()` / Indian-grouping / INR↔USD toggle. We set `data-inr` from real values (minor ÷ 100) and
  call `apply()`. Dynamic panels build rows with `createElement`, putting numbers in `.cv[data-inr]`
  spans and **all text (plan names, counterparties) via `textContent`** (XSS — K4).
- **Currency toggle:** clicking INR/USD switches the user's **base currency** via `POST /api/base-currency`
  then reloads (real conversion through stored FX). The `data-cur` palette shifts (the greenback theme).
  No fake fixed rate.
- **Avatar:** keep the mockup's localStorage photo-upload (display-only initial = first letter of
  display_name); no backend.

## Data mapping (mockup element → real source)
- **Greeting:** "Good {morning<12 / afternoon<17 / evening}, {display_name}" from `/api/auth/me`. Sub:
  today's date + "{N} active plans" from `/api/plans` count.
- **Sidebar counts:** Assets/Loans/Holdings/Chit/401(k) counts from `/api/plans` grouped by type. Items
  link to real routes (`/holdings`, type filters / detail). "New plan"→`/create`, "Settings"→`/settings`,
  "Log payment"→opens the featured asset's log-payment (or `/app`’s first asset detail).
- **Stat cards (4):** hero **Net worth** (`/api/networth.net_worth_minor`) · **Paid to date** ·
  **I owe** · **Owed to me** (`/api/dashboard`). Sub-captions: real, generic copy ("across all plans",
  "loans you've taken", "loans given + chit dividends"); the mockup's "▲ X this month" delta is NOT
  tracked — replace with a non-fabricated caption (e.g. "across N asset plans") — never invent a number.
- **Left column — Featured asset panel:** the user's **first asset plan** → `GET /api/plans/<id>`:
  planhead amounts (total/paid/remaining), the big progress bar (paid/total %), and the installment
  `.sched` rows with `paid/part/due` dots + the real `applied`/`planned` amounts. If no asset → show a
  friendly empty panel ("No asset plans yet — create one").
- **Right column (`fillcol`):**
  - **Liabilities panel:** the user's **loans with direction=taken** → each loan's `loan_state`
    (`total_minor` outstanding, miniprog = paid-fraction if derivable, counterparty, rate). 
  - **Chit panel** (if any chit): `chit_state` → `My net position` (`net_position_minor`), the rounds
    strip rendered from `months_recorded` vs `n_members` (done/now/upcoming — NOT per-auction wins, which
    aren't tracked; the "mine/took" markers are omitted or shown only if `won`), foot = dividends +
    contribution/mo.
  - **Loan-given panel** (if any given loan): `loan_state` principal outstanding + interest due.
  - Panels render only for plan types the user has; the column fills gracefully.
- **No raw cross-plan Ledger panel** (no endpoint exposes a combined ledger) — replaced by the featured
  asset's schedule + a compact "your plans" list styled as `.panel` rows linking to details. (Backend
  ledger-feed is a later enhancement; do not fake it.)

## Components
- `static/app.html` fully rebuilt (mockup CSS + structure + real-data JS). `web.py` `/app` route
  unchanged. Sidebar/topbar/stat CSS will be extracted to `static/assets/app.css` in Plan 6.3 for reuse;
  for 6.1 it lives inline in `app.html` (port from the mockup).

## Testing (TDD)
- `test_web.py` (extend): `/app` 200 + markers (`/api/dashboard`, `/api/networth`, `/api/plans`,
  `/api/auth/me`, "Good ", `curtog`, `Log payment`, `Liabilities`, `ledger.css` OR inline styles ok).
- Done-gate: boot, log in as the seeded demo (has an asset+loan+holding+…), confirm `/app` renders the
  featured asset schedule + liabilities + stat cards with real numbers; XSS-safe (grep app.html for
  `innerHTML` → only static clears).

## Graceful degradation (no fabrication)
Where the backend lacks data (this-month delta, per-round chit wins, cross-plan ledger feed, proof
links), show honest substitutes or omit — **never invent numbers**. These gaps are logged for a later
backend pass.

## Boundaries
Depends only on existing read endpoints + `POST /api/base-currency`. No backend changes. Pure visual
fidelity + live wiring.
