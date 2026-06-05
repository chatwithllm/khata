# Khata Phase 6 · Plan 6.4 — Loan + Chit + Retirement Detail Fidelity

> REQUIRED SUB-SKILL: subagent-driven-development. Harness: read `agent-rules.md` (K1–K8); done-gate = real end-to-end. Do NOT touch `build_status.json`, `khata_live.db*`, `.env.live`, `OD_khata_mockup/`. Branch `feat/phase6-fidelity`. Stage files explicitly (never `git add -A` — the live server rewrites `build_status.json`).

**Goal:** Port `loan-detail.html`, `chit-detail.html`, `retirement-detail.html` to the editorial mockups
(`docs/mockups/loan-detail.html` / `chit-detail.html` / `retirement-401k.html`) using the shared
`static/assets/app.css` shell + `grid2` panels, wired to live state, XSS-safe (K4), honest degradation where
the backend lacks data. Keep the existing entry/update modals + `mountSharing`. Same proven recipe as 6.1/6.3.

**Architecture:** Frontend-only. Reuse read endpoints + existing mutation endpoints. No backend/migration.

## Shared recipe (all three pages — mirror `asset-detail.html` from 6.3)
- Link `/static/assets/app.css`; build the mockup `.app` (sidebar) + `.main` (topbar + `.content` > `.grid2`).
- Auth guard: `GET /api/auth/me` 401→`/`; `GET /api/plans/<id>` 401→`/`, `!ok`→`/app`, wrong `plan.type`→`/app`.
- Sidebar counts from `/api/plans` grouped by type; the matching nav item gets `.on`.
- Topbar: `h1`=`plan.name` (textContent), curtog (→`POST /api/base-currency`+reload), avatar (localStorage).
- Currency: the `.cv[data-inr]`+`.symword`+`applyCurrency`/`renderCV` machinery from app.html — **no fake RATE**;
  render real base currency (Indian grouping INR / en-US USD).
- **K4:** every dynamic string via createElement+textContent; zero innerHTML on data. Bar widths set post-load.
- Honest degradation: render ONLY fields present in the live `state`; omit mockup panels with no backing data
  (do NOT fabricate per-round auction wins, projection sparklines with invented points, loan-offset planners).

---

### Task 1: Loan-detail fidelity (`/loan/<id>`)

**Files:** Modify `src/khata/static/loan-detail.html`; Test `tests/test_web.py`. Read first:
`docs/mockups/loan-detail.html`, current `src/khata/static/loan-detail.html` (preserve its entry modal:
disbursement / interest_payment / principal_repayment wiring).

`loan_state` = `{direction, currency, principal_outstanding_minor, interest_accrued_minor, interest_paid_minor,
interest_due_minor, total_minor, as_of, schedule:[{month_index, period_start, expected_minor, applied_minor,
status∈paid/partial/due}], next_due_month, months_behind, secured, collateral|null:{plan_id,name,asset_class,
currency,value_minor,ltv_pct}}`. `plan` = `{id,type,name,currency,status}` + loan summary fields
(direction, counterparty, rate — confirm via `_summary`).

Panels:
- **Header KPIs (3):** Principal outstanding (`principal_outstanding_minor`), Interest due (`interest_due_minor`),
  Total (`total_minor`). `.planhead` caption: `{direction} · {counterparty}` + (if interest) rate; if a
  schedule exists, a progress bar = interest_paid / (interest_paid+interest_due) OR months paid / total months
  — whichever is honestly derivable (label it accurately). The mockup's "Repayment style" meta = humanized
  `interest_type` + rate.
- **Release tracker (`.sched`):** one `.srow` per `schedule` row. dot by `status` (paid ✓ / partial ~ / due
  month_index). `.nm` = `Month {month_index}` + `period_start` (date is REAL — show it). `.sv .pa` =
  `applied_minor`, `.pl` = `expected {expected_minor}`. Foot/meta: `{months_behind} behind · next due month
  {next_due_month}` when applicable.
- **Collateral panel (only if `state.collateral`):** name (textContent), asset_class, `value_minor`, and an
  **LTV** readout (`ltv_pct`%) with a `.miniprog`/bar (LTV fill). If `secured` but no collateral linked, show
  "secured · no collateral linked". If unsecured, omit the panel.
- **Loan terms panel:** direction, counterparty, interest type + rate, start date, tenure, `as_of` — all real.
- **Entry modal (keep + restyle to slide-over like asset-detail):** kind select (disbursement /
  interest_payment / principal_repayment — exact service kinds), amount, occurred_at (optional), method
  (optional), note. Disbursement → `POST /loan/disbursements`; interest/principal → `POST /loan/entries`
  `{kind,amount,method,note}`. Collateral-link control may stay as the existing simple control (or in terms
  panel) → `POST /loan/collateral {collateral_plan_id}`.
- **OMIT (no endpoint / not tracked):** a raw entry ledger list (no GET for loan entries — the release tracker
  is the schedule view), any invented projection.
- **Members:** `mountSharing(pid, box)` panel.
- `tests/test_web.py`: `/loan/1` 200 + markers (`/api/plans/`, `app.css`, `curtog`, `Release`/schedule marker,
  `/loan/entries`, `/api/auth/me`). Done-gate: live `/api/plans/2` (Gold loan HDFC, taken, ₹5,00,000 disbursed,
  1 interest payment) renders principal/interest/total + a schedule; grep `innerHTML`→only static. Commit
  `feat(web): loan-detail UI fidelity — editorial shell + live panels`.

### Task 2: Chit-detail fidelity (`/chit/<id>`)

**Files:** Modify `src/khata/static/chit-detail.html`; Test `tests/test_web.py`. Read first:
`docs/mockups/chit-detail.html`, current `src/khata/static/chit-detail.html` (preserve the chit entry modal:
chit_contribution / chit_dividend / chit_prize).

`chit_state` = `{currency, chit_value_minor, n_members, commission_bps, subscription_minor,
total_contributed_minor, total_dividends_minor, prize_received_minor, net_contributed_minor,
net_position_minor, won, months_recorded, ledger:[{kind, direction∈in/out, amount_minor, occurred_at, note}]}`.

Panels:
- **Header KPIs (3):** Chit value (`chit_value_minor`), My net position (`net_position_minor`, color by sign),
  Net contributed (`net_contributed_minor`). Meta: `{n_members}-member · {commission_bps/100}% commission ·
  subscription {subscription_minor}/mo`.
- **Auction rounds strip (`.rounds`/`.rd` from app.html's chit panel):** render `months_recorded` of
  `n_members` rounds — done / next / upcoming dots. **Do NOT** render per-round winner/bid (not tracked); the
  "mine/took" markers only if `won` (single aggregate flag). Honest.
- **My position panel:** total_contributed, total_dividends, prize_received, net_position — all real. `won`
  → a "Prize won" badge.
- **Ledger panel (chit DOES expose `ledger`):** one row per entry — kind (humanized), direction (in/out color +
  sign), `amount_minor`, `occurred_at` (real date), note (textContent). This is the one detail page WITH a real
  ledger — render it (unlike asset/loan).
- **Chit terms panel:** value, members, commission, subscription, months recorded — real.
- **Member roster:** `mountSharing(pid, box)`.
- **OMIT:** the mockup's "Net position over rounds" sparkline UNLESS derived honestly from cumulative `ledger`
  (acceptable: compute running net from ledger entries in order — that IS real data; if you draw it, the points
  must come from the ledger, not invented).
- **Entry modal (keep + slide-over restyle):** kind (chit_contribution/chit_dividend/chit_prize), amount,
  occurred_at, note → `POST /chit/entries`.
- `tests/test_web.py`: `/chit/1`... use the live chit (plan id 5). Markers (`/api/plans/`, `app.css`, `curtog`,
  `/chit/entries`, `position`, `/api/auth/me`). Done-gate: live `/api/plans/5` (12-member, 5 contributions + 5
  dividends) renders net position + rounds strip (5 of 12) + ledger rows; grep innerHTML. Commit
  `feat(web): chit-detail UI fidelity — editorial shell + live panels`.

### Task 3: Retirement-detail fidelity (`/retirement/<id>`)

**Files:** Modify `src/khata/static/retirement-detail.html`; Test `tests/test_web.py`. Read first:
`docs/mockups/retirement-401k.html`, current `src/khata/static/retirement-detail.html` (preserve the update form
→ `POST /retirement/update`).

`retirement_state` = `{currency, current_balance_minor, monthly_contribution_minor, employer_match_bps,
annual_return_bps, inflation_bps, current_age, retirement_age, months_to_retirement, effective_monthly_minor,
total_contributions_minor, projected_corpus_minor, projected_corpus_real_minor}`.

Panels:
- **Header KPIs (3):** Projected corpus (`projected_corpus_minor`), In today's money (`projected_corpus_real_minor`),
  Current balance (`current_balance_minor`). Meta: `age {current_age}→{retirement_age} · {months_to_retirement/12}
  yrs · {annual_return_bps/100}% return`.
- **Contribution maximizer / Per-paycheck breakdown panel:** monthly_contribution, employer match (bps→%),
  effective_monthly (your + match), total_contributions over horizon — all real. A simple bar comparing
  your contribution vs employer match vs growth (corpus − total_contributions = projected growth) — derived,
  honest.
- **Projection panel:** projected_corpus nominal vs real, months_to_retirement. If a growth curve is drawn, the
  endpoints (current_balance → projected_corpus) are real; intermediate points only if computed from the same
  compound formula (acceptable) — otherwise show just the two figures + a bar. Do NOT fabricate.
- **Assumptions / update form (keep, restyle):** editable fields (current_balance, monthly_contribution,
  employer_match %, annual_return %, inflation %, current_age, retirement_age) → `POST /retirement/update`;
  reload on success.
- **OMIT:** the mockup's "401(k)-loan offset planner" (no backing model — honest omission).
- `tests/test_web.py`: `/retirement/1`... live plan id 6 (NPS). Markers (`/api/plans/`, `app.css`,
  `/retirement/update`, `corpus`/projection marker, `/api/auth/me`). Done-gate: live `/api/plans/6` renders a
  projected corpus > current balance; update form posts. grep innerHTML. Commit
  `feat(web): retirement-detail UI fidelity — editorial shell + live panels`.

### Task 4: Review + docs
- Dispatch a reviewer over all three commits (spec-compliance + K1/K4/K5 + no fabrication + tests green).
- Append `docs/AGENT_LEARNINGS.md` (6.4 notes). Flip 6.4 box in `ROADMAP.md`; update `Progress.md` + tests
  count. Orchestrator owns `build_status.json`. Commit `docs: phase 6.4 progress`.

## Self-Review
Three detail pages gain the editorial shell + live panels. Loan: KPIs + release tracker (real schedule) +
collateral/LTV (when present) + terms; ledger omitted (no GET). Chit: KPIs + rounds strip (aggregate, no fake
wins) + my position + **real ledger** + terms + roster. Retirement: KPIs + contribution/projection from real
compound state + update form; loan-offset planner omitted. Entry/update modals reuse real endpoints with exact
enums. XSS-safe; no fabrication; no backend changes. ✓
